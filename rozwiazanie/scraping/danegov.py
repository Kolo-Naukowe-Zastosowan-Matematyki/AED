"""Źródło główne: zbiory o AED opublikowane w dane.gov.pl, pobierane przez publiczne API 1.4.

Przepływ:
  1. wyszukanie zbiorów (/datasets?q=...) – frazy z config.json,
     plus zbiory i zasoby wskazane wprost (dataset_ids / resource_ids),
  2. lista zasobów zbioru (/datasets/{id}/resources),
  3. dla zasobu z danymi tabelarycznymi: /resources/{id}/data (stronicowanie, max 100/strona),
     w przeciwnym razie pobranie pliku CSV/GeoJSON z download_url,
  4. rozpoznanie kolumn ze współrzędnymi: najpierw role mapowe z data_schema (b/l/label,
     tak jak ustawia je dostawca w panelu dane.gov.pl), potem heurystyka po nazwach kolumn.

Każdy rekord zachowuje link do zasobu źródłowego i warunki licencji z metadanych zbioru.
Tylko biblioteka standardowa Pythona.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import Iterable

from rozwiazanie.backend.schema import AED, in_poland, map_access, to_float

log = logging.getLogger("aed.danegov")

NAME = "danegov"
LABEL = "dane.gov.pl"
API = "https://api.dane.gov.pl/1.4"
PORTAL = "https://dane.gov.pl"
HEADERS = {"Accept": "application/vnd.api+json, application/json", "User-Agent": "aed-prototyp/0.1"}
MAX_PAGES = 60  # 60 x 100 = 6000 wierszy na zasób – wystarczy na prototyp
KEYWORDS = ("defibryl", "aed")


# ---------------------------------------------------------------- HTTP

def _get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_bytes(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _paged(url: str, max_pages: int = MAX_PAGES) -> Iterable[dict]:
    """Iteruje po stronach odpowiedzi JSON:API, zwracając całe odpowiedzi."""
    sep = "&" if "?" in url else "?"
    for page in range(1, max_pages + 1):
        body = _get_json(f"{url}{sep}per_page=100&page={page}")
        yield body
        if not body.get("data") or not (body.get("links") or {}).get("next"):
            break


# ---------------------------------------------------------------- pomocnicze

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _attr(obj: dict, *keys, default=""):
    a = obj.get("attributes") or {}
    for k in keys:
        v = a.get(k)
        if v not in (None, ""):
            return v
    return default


def _text(v) -> str:
    if isinstance(v, dict):
        v = v.get("repr", v.get("val"))
    if isinstance(v, dict):  # tłumaczenia {"pl": ..., "en": ...}
        v = v.get("pl") or next(iter(v.values()), "")
    return "" if v is None else str(v).strip()


CANDIDATES = {
    "lat": ["szerokosc", "szerokosc_geograficzna", "szer", "lat", "latitude", "wsp_n", "n", "y", "wspolrzedna_y"],
    "lon": ["dlugosc", "dlugosc_geograficzna", "dl", "lon", "lng", "longitude", "wsp_e", "e", "x", "wspolrzedna_x"],
    "name": ["nazwa_obiektu", "nazwa", "obiekt", "nazwa_miejsca", "miejsce", "lokalizacja", "label", "jednostka"],
    "desc": ["opis_lokalizacji", "umiejscowienie", "opis", "lokalizacja_szczegolowa", "miejsce_zawieszenia"],
    "addr": ["adres", "ulica", "adres_obiektu"],
    "city": ["miejscowosc", "miasto", "gmina"],
    "hours": ["godziny_dostepnosci", "godziny", "dostepnosc", "godziny_otwarcia", "opening_hours"],
    "access": ["dostep", "rodzaj_dostepu", "access"],
    "owner": ["dysponent", "wlasciciel", "instytucja", "operator", "podmiot"],
    "verified": ["data_weryfikacji", "data_aktualizacji", "data_przegladu"],
    "indoor": ["wewnatrz", "wewnatrz_budynku", "indoor"],
    "level": ["pietro", "kondygnacja", "level"],
}


def _detect(columns: list[str], geo_roles: dict[str, str]) -> dict[str, str]:
    """Zwraca mapowanie rola -> nazwa kolumny."""
    found: dict[str, str] = {}
    # 1) role mapowe nadane przez dostawcę w panelu dane.gov.pl
    if "b" in geo_roles:
        found["lat"] = geo_roles["b"]
    if "l" in geo_roles:
        found["lon"] = geo_roles["l"]
    if "label" in geo_roles:
        found["name"] = geo_roles["label"]
    # 2) heurystyka po nazwach
    normed = {_norm(c): c for c in columns}
    for role, names in CANDIDATES.items():
        if role in found:
            continue
        for n in names:
            if n in normed:
                found[role] = normed[n]
                break
        else:
            for n in names:
                if len(n) > 3:
                    hit = next((orig for k, orig in normed.items() if k.startswith(n)), None)
                    if hit:
                        found[role] = hit
                        break
    return found


def _row_to_aed(row: dict, cols: dict[str, str], *, rid: str, n: int, ctx: dict) -> AED | None:
    lat, lon = to_float(row.get(cols.get("lat"))), to_float(row.get(cols.get("lon")))
    if lat is None or lon is None:
        return None
    if not in_poland(lat, lon) and in_poland(lon, lat):
        lat, lon = lon, lat  # zamienione kolumny X/Y
    if not in_poland(lat, lon):
        return None
    g = lambda role: _text(row.get(cols[role])) if role in cols else ""
    addr = g("addr")
    if g("city") and g("city") not in addr:
        addr = f"{addr}, {g('city')}" if addr else g("city")
    indoor_raw = g("indoor").lower()
    return AED(
        id_aed=f"dgp-{rid}-{n}",
        szerokosc=round(lat, 6),
        dlugosc=round(lon, 6),
        zrodlo=NAME,
        zrodlo_url=ctx["resource_url"],
        licencja=ctx["license"],
        nazwa_obiektu=g("name"),
        opis_lokalizacji=g("desc"),
        adres=addr,
        wewnatrz=None if not indoor_raw else indoor_raw in ("tak", "yes", "true", "1", "wewnatrz", "wewnątrz"),
        pietro=g("level"),
        dostep=map_access(g("access")) if g("access") else ("publiczny" if g("hours") == "24/7" else "nieznany"),
        godziny_dostepnosci=g("hours"),
        dysponent=g("owner") or ctx["institution"],
        data_weryfikacji=g("verified")[:10],
        extra={"zbior": ctx["dataset_title"]},
    )


# ---------------------------------------------------------------- odczyt zasobów

def _rows_from_table_api(rid: str) -> tuple[list[dict], dict[str, str]]:
    rows: list[dict] = []
    geo_roles: dict[str, str] = {}
    headers: dict[str, str] = {}
    for body in _paged(f"{API}/resources/{rid}/data"):
        meta = body.get("meta") or {}
        if not headers:
            hm = meta.get("headers_map") or {}
            # headers_map bywa w obu kierunkach: {"col1": "Nazwa"} lub {"Nazwa": "col1"}
            if hm and all(re.match(r"^col\d+$", str(k)) for k in hm):
                headers = {k: str(v) for k, v in hm.items()}
            else:
                headers = {str(v): str(k) for k, v in hm.items()}
            for i, f in enumerate((meta.get("data_schema") or {}).get("fields", []), start=1):
                if f.get("geo"):
                    name = f.get("name") or f"col{i}"
                    geo_roles[f["geo"]] = headers.get(name, name)  # nazwy wierszy są już przetłumaczone
        for item in body.get("data", []):
            attrs = item.get("attributes") or {}
            rows.append({headers.get(k, k): v for k, v in attrs.items()})
    return rows, geo_roles


def _rows_from_file(url: str, fmt: str) -> list[dict]:
    raw = _get_bytes(url)
    if fmt in ("geojson", "json"):
        data = json.loads(raw.decode("utf-8-sig"))
        rows = []
        for f in data.get("features", []) if isinstance(data, dict) else []:
            geom = f.get("geometry") or {}
            if geom.get("type") == "Point":
                props = dict(f.get("properties") or {})
                props["lon"], props["lat"] = geom["coordinates"][:2]
                rows.append(props)
        return rows
    text = None
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return []
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def _license_of(dataset: dict) -> str:
    name = _text(_attr(dataset, "license_name", "license_title"))
    if name:
        return name
    if _attr(dataset, "license_condition_db_or_copyrighted") or _attr(dataset, "license_condition_cc"):
        return "Warunki ponownego wykorzystania – zob. zbiór w dane.gov.pl"
    return "Ponowne wykorzystanie bez warunków (ustawa o otwartych danych)"


def _relevant(dataset: dict) -> bool:
    blob = " ".join(_text(_attr(dataset, k)) for k in ("title", "notes", "keywords")).lower()
    tags = _attr(dataset, "tags", "keywords", default=[])
    if isinstance(tags, list):
        blob += " " + " ".join(_text(t.get("name") if isinstance(t, dict) else t) for t in tags).lower()
    return any(k in blob for k in KEYWORDS)


def find_datasets(cfg: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for q in cfg.get("queries", ["defibrylator", "defibrylatory AED"]):
        url = f"{API}/datasets?q={urllib.parse.quote(q)}"
        for body in _paged(url, max_pages=3):
            for ds in body.get("data", []):
                if _relevant(ds):
                    found[str(ds["id"])] = ds
    for did in cfg.get("dataset_ids", []):
        try:
            found[str(did)] = _get_json(f"{API}/datasets/{did}")["data"]
        except Exception as exc:  # noqa: BLE001
            log.warning("Nie udało się pobrać zbioru %s: %s", did, exc)
    return list(found.values())


def load(cfg: dict, progress=lambda msg: None) -> tuple[list[AED], list[dict]]:
    """Zwraca (rekordy, raport_zasobów)."""
    records: list[AED] = []
    report: list[dict] = []
    datasets = find_datasets(cfg)
    progress(f"Znaleziono zbiorów: {len(datasets)}")
    jobs: list[tuple[dict, dict]] = []
    for ds in datasets:
        try:
            for body in _paged(f"{API}/datasets/{ds['id']}/resources", max_pages=2):
                jobs += [(ds, r) for r in body.get("data", [])]
        except Exception as exc:  # noqa: BLE001
            report.append({"zbior": _text(_attr(ds, "title")), "blad": str(exc)})
    for rid in cfg.get("resource_ids", []):
        try:
            res = _get_json(f"{API}/resources/{rid}")["data"]
            ds_id = ((res.get("relationships") or {}).get("dataset") or {}).get("data", {}).get("id")
            ds = _get_json(f"{API}/datasets/{ds_id}")["data"] if ds_id else {"id": "", "attributes": {}}
            jobs.append((ds, res))
        except Exception as exc:  # noqa: BLE001
            report.append({"zasob": rid, "blad": str(exc)})

    seen = set()
    for ds, res in jobs:
        rid = str(res["id"])
        if rid in seen:
            continue
        seen.add(rid)
        fmt = _text(_attr(res, "format")).lower()
        rel = res.get("relationships") or {}
        ctx = {
            "resource_url": f"{PORTAL}/pl/dataset/{ds.get('id')}/resource/{rid}",
            "license": _license_of(ds),
            "institution": _text(((rel.get("institution") or {}).get("data") or {}).get("title", ""))
            or _text(_attr(ds, "institution_name", "organization_title")),
            "dataset_title": re.sub(r"<[^>]+>", "", _text(_attr(ds, "title"))),  # wyszukiwarka API dodaje <mark>
        }
        entry = {"zbior": ctx["dataset_title"], "zasob": _text(_attr(res, "title")), "url": ctx["resource_url"],
                 "format": fmt, "rekordy": 0}
        try:
            geo_roles: dict[str, str] = {}
            if "tabular_data" in rel or "geo_data" in rel:
                rows, geo_roles = _rows_from_table_api(rid)
                entry["metoda"] = "API /data"
            elif fmt in ("csv", "geojson", "json") and _attr(res, "download_url", "file_url", "link"):
                rows = _rows_from_file(_attr(res, "download_url", "file_url", "link"), fmt)
                entry["metoda"] = "plik"
            else:
                entry["pominieto"] = "format nieobsługiwany w prototypie"
                report.append(entry)
                continue
            cols = _detect(list(rows[0].keys()) if rows else [], geo_roles)
            entry["kolumny"] = cols
            if "lat" not in cols or "lon" not in cols:
                entry["pominieto"] = "brak kolumn ze współrzędnymi"
            for n, row in enumerate(rows, start=1):
                aed = _row_to_aed(row, cols, rid=rid, n=n, ctx=ctx) if "lat" in cols and "lon" in cols else None
                if aed:
                    records.append(aed)
                    entry["rekordy"] += 1
        except Exception as exc:  # noqa: BLE001
            entry["blad"] = str(exc)
        report.append(entry)
        progress(f"{entry['zasob']}: {entry['rekordy']} rekordów")
    return records, report
