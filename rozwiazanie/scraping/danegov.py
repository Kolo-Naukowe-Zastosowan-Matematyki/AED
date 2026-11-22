"""Źródło główne: zbiory o AED opublikowane w dane.gov.pl, pobierane przez publiczne API 1.4.

Przepływ:
  1. wyszukanie zbiorów (/datasets?q=...) i zasobów (/resources?q=...: wykaz AED bywa zasobem w zbiorze
     o innej nazwie), plus zbiory i zasoby wskazane wprost w config.json (dataset_ids / resource_ids),
  2. lista zasobów zbioru (/datasets/{id}/resources),
  3. odczyt: widok tabelaryczny /resources/{id}/data, a gdy go nie ma albo nic z niego nie wyszło – sam plik
     (czytniki.py: CSV/XLSX/ODS/XLS/JSON/GeoJSON/XML/KML/ZIP, format rozpoznawany po zawartości),
  4. standaryzacja do złotego standardu (standard.py + common/aed_columns.json): mapowanie kolumn po synonimach
     i po wartościach, normalizacja wartości, geokodowanie adresów bez współrzędnych (geokod.py, GUGiK),
  5. ten sam zestaw danych opublikowany w kilku formatach (np. CSV i XLSX) liczymy raz,
  6. raport dla każdego zasobu: mapowanie kolumn, nierozpoznane kolumny, odrzucone wiersze z powodem.

Każdy rekord zachowuje link do zasobu źródłowego i warunki licencji z metadanych zbioru.
Tylko biblioteka standardowa Pythona.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Iterable

from rozwiazanie.backend.schema import AED
from rozwiazanie.scraping.czytniki import NieobslugiwanyPlik, czytaj
from rozwiazanie.scraping.standard import braki, mapuj_kolumny, standaryzuj

log = logging.getLogger("aed.danegov")

NAME = "danegov"
LABEL = "dane.gov.pl"
API = "https://api.dane.gov.pl/1.4"
PORTAL = "https://dane.gov.pl"
HEADERS = {"Accept": "application/vnd.api+json, application/json", "User-Agent": "aed-prototyp/0.1"}
MAX_PAGES = 60  # 60 x 100 = 6000 wierszy na zasób – wystarczy na prototyp
_LAST_RAW: dict[str, bytes] = {}  # początek ostatnio pobranego pliku (do diagnozy pominiętych zasobów)


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


_DOSTEP_AED = {"24/7": "publiczny", "GODZINY_OTWARCIA": "w_godzinach", "TYLKO_PERSONEL": "ograniczony"}


def _std_to_aed(rec: dict, *, rid: str, n: int, ctx: dict) -> AED:
    """Rekord w złotym standardzie -> rekord mapy/rejestru (AED). Pełny rekord standardu jest w extra["std"]."""
    adres = ", ".join(x for x in (rec["street_address"], " ".join(y for y in (rec["postal_code"], rec["city"]) if y)) if x)
    return AED(
        id_aed=f"dgp-{rid}-{n}",
        szerokosc=rec["latitude"],
        dlugosc=rec["longitude"],
        zrodlo=NAME,
        zrodlo_url=ctx["resource_url"],
        licencja=ctx["license"],
        nazwa_obiektu=rec["building_name"],
        opis_lokalizacji=rec["exact_location"],
        adres=adres,
        wewnatrz=rec["is_indoor"],
        dostep=_DOSTEP_AED.get(rec["availability_type"], "nieznany"),
        godziny_dostepnosci=rec["opening_hours"] or ("24/7" if rec["availability_type"] == "24/7" else ""),
        dysponent=rec["operator_name"],
        data_weryfikacji=rec["record_updated_at"],
        extra={"zbior": ctx["dataset_title"], "std": rec},
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


def _rows_from_file(url: str, fmt: str) -> tuple[list[dict], list[str]]:
    raw = _get_bytes(url)
    _LAST_RAW["head"] = raw[:1500]
    return czytaj(raw, fmt)


def _license_of(dataset: dict) -> str:
    name = _text(_attr(dataset, "license_name", "license_title"))
    if name:
        return name
    if _attr(dataset, "license_condition_db_or_copyrighted") or _attr(dataset, "license_condition_cc"):
        return "Warunki ponownego wykorzystania – zob. zbiór w dane.gov.pl"
    return "Ponowne wykorzystanie bez warunków (ustawa o otwartych danych)"


def _relevant(dataset: dict) -> bool:
    blob = " ".join(_text(_attr(dataset, k)) for k in ("title", "notes", "description", "keywords")).lower()
    tags = _attr(dataset, "tags", "keywords", default=[])
    if isinstance(tags, list):
        blob += " " + " ".join(_text(t.get("name") if isinstance(t, dict) else t) for t in tags).lower()
    return "defibryl" in blob or re.search(r"\baed\b", blob) is not None


# wyszukiwarka dane.gov.pl nie zawsze odmienia wyrazy („defibrylator” nie znajduje „Wykaz defibrylatorów”),
# dlatego pytamy o kilka form; nadmiarowe trafienia odsiewa _relevant
QUERIES = ["defibrylator", "defibrylatory", "defibrylatorów", "defibrylatorach", "defibrylatora", "AED",
           "automatyczny defibrylator zewnętrzny", "automatycznych defibrylatorów zewnętrznych"]


def find_datasets(cfg: dict, trafienia: list | None = None) -> list[dict]:
    """Zbiory o AED. trafienia (opcjonalnie) dostaje (fraza, id, tytuł, czy_pasuje) do diagnozy wyszukiwania."""
    found: dict[str, dict] = {}
    queries = list(dict.fromkeys(QUERIES + list(cfg.get("queries", []))))
    for q in queries:
        url = f"{API}/datasets?q={urllib.parse.quote(q)}"
        try:
            for body in _paged(url, max_pages=3):
                for ds in body.get("data", []):
                    ok = _relevant(ds)
                    if trafienia is not None:
                        trafienia.append((q, str(ds["id"]), re.sub(r"<[^>]+>", "", _text(_attr(ds, "title"))), ok))
                    if ok:
                        found[str(ds["id"])] = ds
        except Exception as exc:  # noqa: BLE001
            log.warning("Wyszukiwanie „%s” w dane.gov.pl nie powiodło się: %s", q, exc)
    for did in cfg.get("dataset_ids", []):
        try:
            found[str(did)] = _get_json(f"{API}/datasets/{did}")["data"]
        except Exception as exc:  # noqa: BLE001
            log.warning("Nie udało się pobrać zbioru %s: %s", did, exc)
    return list(found.values())


def find_resources(cfg: dict, znane_zbiory: set[str], trafienia: list | None = None) -> list[str]:
    """Zasoby o AED w zbiorach, których wyszukiwarka zbiorów nie znalazła (np. „Wykaz defibrylatorów AED”
    w zbiorze urzędu miasta o ogólnej nazwie). Bierzemy tylko te zasoby, nie cały zbiór."""
    found: dict[str, None] = {}
    queries = list(dict.fromkeys(QUERIES + list(cfg.get("queries", []))))
    for q in queries:
        try:
            for body in _paged(f"{API}/resources?q={urllib.parse.quote(q)}", max_pages=3):
                for res in body.get("data", []):
                    ok = _relevant(res)
                    ds_id = str((((res.get("relationships") or {}).get("dataset") or {}).get("data") or {}).get("id", ""))
                    if trafienia is not None:
                        trafienia.append((q, f"z:{res['id']}", re.sub(r"<[^>]+>", "", _text(_attr(res, "title"))), ok))
                    if ok and ds_id not in znane_zbiory:
                        found[str(res["id"])] = None
        except Exception as exc:  # noqa: BLE001
            log.warning("Wyszukiwanie zasobów „%s” w dane.gov.pl nie powiodło się: %s", q, exc)
    return list(found)


def _miasto_z_instytucji(name: str) -> str:
    """„Urząd Miasta Marki” / „Gmina Miejska Krosno” -> „Marki” / „Krosno” (podpowiedź dla geokodera i kolumny city)."""
    m = re.search(r"(?:Miasta(?: i Gminy)?|Miejska|Gmina|Miasto|Gminy|m\.|st\.)\s+(?:st\.\s+)?([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż-]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż-]+)?)", name or "")
    return m.group(1) if m else ""


def _wypelnienie(recs: list[AED]) -> float:
    """Średnia liczba wypełnionych pól standardu na rekord (do wyboru lepszej wersji tego samego zbioru)."""
    if not recs:
        return 0.0
    return sum(sum(1 for v in r.extra["std"].values() if v not in ("", None)) for r in recs) / len(recs)


def _probka(rows: list[dict], geo_roles: dict, res: dict) -> dict:
    return {
        "naglowki": list(rows[0].keys()) if rows else [],
        "wiersze": [{k: (v if isinstance(v, (str, int, float, bool, type(None), dict, list)) else str(v))
                     for k, v in r.items()} for r in rows[:3]],
        "role_mapowe": geo_roles,
        "poczatek_pliku": _LAST_RAW.get("head", b"").decode("utf-8", "replace") if not rows else "",
        "download_url": _attr(res, "download_url", "file_url", "link"),
    }


MAX_KM_OD_ZBIORU = 30


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    dy = (lat2 - lat1) * 111.2
    dx = (lon2 - lon1) * 111.2 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def standaryzuj_wiersze(rows: list[dict], geo_roles: dict, ctx: dict, entry: dict, geokoder=None,
                        rid: str = "", start: int = 1) -> list[AED]:
    """Wiersze jednego zasobu -> rekordy AED w złotym standardzie; wszystko, co się nie udało, trafia do `entry`."""
    cols = list(dict.fromkeys(k for r in rows[:200] for k in r.keys()))
    mapa = mapuj_kolumny(cols, rows, geo_roles)
    entry["kolumny"] = dict(mapa["pola"])
    if mapa["para"]:
        entry["kolumny"]["latitude+longitude"] = mapa["para"]
    if mapa["uwagi"]:
        entry["mapowanie"] = mapa["uwagi"]
    if mapa["nierozpoznane"]:
        entry["nierozpoznane_kolumny"] = mapa["nierozpoznane"]
    out: list[AED] = []
    odrzucone: dict[str, int] = {}
    przyklady: list[dict] = []
    uwagi: dict[str, int] = {}
    brakuje: dict[str, int] = {}
    for n, row in enumerate(rows, start=start):
        try:
            rec, why, notes = standaryzuj(row, mapa, ctx, geokoder)
        except Exception as exc:  # noqa: BLE001  jeden zły wiersz nie wywraca importu
            rec, why, notes = None, f"błąd wiersza: {exc}", []
        for x in notes:
            uwagi[x] = uwagi.get(x, 0) + 1
        if rec is None:
            odrzucone[why] = odrzucone.get(why, 0) + 1
            if len(przyklady) < 3:
                przyklady.append({k: str(v)[:80] for k, v in list(row.items())[:12]})
            continue
        for b in braki(rec):
            brakuje[b] = brakuje.get(b, 0) + 1
        out.append(_std_to_aed(rec, rid=rid, n=n, ctx=ctx))
    # punkty daleko od reszty zbioru (np. współrzędne skopiowane z innego miasta): tylko zgłaszamy w raporcie,
    # nazw i miejscowości z pliku nie zmieniamy
    if len(out) >= 3:
        lat0 = sorted(r.szerokosc for r in out)[len(out) // 2]
        lon0 = sorted(r.dlugosc for r in out)[len(out) // 2]
        daleko = [f"wiersz {r.id_aed.rsplit('-', 1)[-1]}: {r.szerokosc}, {r.dlugosc} "
                  f"({round(_km(lat0, lon0, r.szerokosc, r.dlugosc))} km od pozostałych)"
                  for r in out if _km(lat0, lon0, r.szerokosc, r.dlugosc) > MAX_KM_OD_ZBIORU]
        if daleko:
            entry["podejrzane_wspolrzedne"] = daleko
    if odrzucone:
        entry["odrzucone"] = odrzucone
        entry["odrzucone_przyklady"] = przyklady
    if uwagi:
        entry["uwagi_wartosci"] = uwagi
    if brakuje:
        entry["braki_wymaganych"] = brakuje
    return out


def load(cfg: dict, progress=lambda msg: None, geokoder=None) -> tuple[list[AED], list[dict]]:
    """Zwraca (rekordy, raport_zasobów). Każdy zasób przechodzi przez czytniki.czytaj + standard.standaryzuj."""
    records: list[AED] = []
    report: list[dict] = []
    datasets = find_datasets(cfg)
    extra_resources = find_resources(cfg, {str(d["id"]) for d in datasets})
    progress(f"Znaleziono zbiorów: {len(datasets)}, osobnych zasobów: {len(extra_resources)}")
    jobs: list[tuple[dict, dict]] = []
    for ds in datasets:
        try:
            for body in _paged(f"{API}/datasets/{ds['id']}/resources", max_pages=2):
                jobs += [(ds, r) for r in body.get("data", [])]
        except Exception as exc:  # noqa: BLE001
            report.append({"zbior": _text(_attr(ds, "title")), "blad": str(exc)})
    for rid in list(dict.fromkeys(list(cfg.get("resource_ids", [])) + extra_resources)):
        try:
            res = _get_json(f"{API}/resources/{rid}")["data"]
            ds_id = ((res.get("relationships") or {}).get("dataset") or {}).get("data", {}).get("id")
            ds = _get_json(f"{API}/datasets/{ds_id}")["data"] if ds_id else {"id": "", "attributes": {}}
            jobs.append((ds, res))
        except Exception as exc:  # noqa: BLE001
            report.append({"zasob": rid, "blad": str(exc)})

    seen = set()
    seen_sets: dict[str, list[dict]] = {}
    for ds, res in jobs:
        rid = str(res["id"])
        if rid in seen:
            continue
        seen.add(rid)
        fmt = _text(_attr(res, "format")).lower()
        rel = res.get("relationships") or {}
        institution = _text(((rel.get("institution") or {}).get("data") or {}).get("title", "")) \
            or _text(_attr(ds, "institution_name", "organization_title"))
        ctx = {
            "resource_url": f"{PORTAL}/pl/dataset/{ds.get('id')}/resource/{rid}",
            "license": _license_of(ds),
            "institution": institution,
            "dataset_title": re.sub(r"<[^>]+>", "", _text(_attr(ds, "title"))),  # wyszukiwarka API dodaje <mark>
        }
        sctx = {**ctx, "zasob_url": ctx["resource_url"], "instytucja": institution,
                "miasto": _miasto_z_instytucji(institution) or _miasto_z_instytucji(ctx["dataset_title"]),
                "zmodyfikowano": _text(_attr(res, "data_date", "modified", "file_modified"))}
        entry = {"zbior": ctx["dataset_title"], "zasob": _text(_attr(res, "title")), "url": ctx["resource_url"],
                 "format": fmt, "rekordy": 0}
        rows: list[dict] = []
        geo_roles: dict[str, str] = {}
        _LAST_RAW.pop("head", None)
        try:
            url = _attr(res, "download_url", "file_url", "link")
            recs: list[AED] = []
            if "tabular_data" in rel or "geo_data" in rel:
                rows, geo_roles = _rows_from_table_api(rid)
                entry["metoda"] = "API /data"
                recs = standaryzuj_wiersze(rows, geo_roles, sctx, entry, geokoder, rid)
            if not recs and url:
                # brak widoku tabelarycznego albo nic z niego nie wyszło: czytamy sam plik, format po zawartości
                file_entry = {}
                rows, notes = _rows_from_file(url, fmt)
                geo_roles = {}
                recs = standaryzuj_wiersze(rows, {}, sctx, file_entry, geokoder, rid)
                if recs or "metoda" not in entry:
                    entry.update(file_entry)
                    entry["metoda"] = "plik: " + "; ".join(notes)
            if not url and "metoda" not in entry:
                entry["pominieto"] = "zasób bez pliku do pobrania"
            sig = {(round(r.szerokosc, 4), round(r.dlugosc, 4)) for r in recs}
            score = _wypelnienie(recs)
            group = seen_sets.setdefault(str(ds.get("id")), [])
            twin = next((t for t in group if sig and len(sig & t["sig"]) >= 0.9 * len(sig)), None)
            if twin and score <= twin["score"]:
                entry["pominieto"] = f"ten sam zestaw danych co zasób {twin['rid']} (inny format), liczony raz"
                recs = []
            elif twin:
                # ten sam zestaw w kilku formatach: zostaje wersja z większą liczbą wypełnionych pól
                # (np. GeoJSON z samą geometrią przegrywa z CSV, który ma nazwy i adresy)
                old_ids = {id(r) for r in twin["recs"]}
                records[:] = [r for r in records if id(r) not in old_ids]
                twin["entry"]["rekordy"] = 0
                twin["entry"]["pominieto"] = f"ten sam zestaw danych co zasób {rid} (inny format, mniej wypełnionych pól)"
                twin.update(rid=rid, sig=sig, recs=recs, score=score, entry=entry)
            else:
                group.append({"rid": rid, "sig": sig, "recs": recs, "score": score, "entry": entry})
            records += recs
            entry["rekordy"] = len(recs)
            if rows and not recs and "pominieto" not in entry:
                entry["pominieto"] = "żaden wiersz nie dał się sprowadzić do standardu"
            elif not rows and "pominieto" not in entry:
                entry["pominieto"] = "brak wierszy danych w pliku"
        except NieobslugiwanyPlik as exc:
            entry["pominieto"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            entry["blad"] = f"{type(exc).__name__}: {exc}"
        if not entry["rekordy"] and ("pominieto" in entry or "blad" in entry) and "ten sam zestaw" not in entry.get("pominieto", ""):
            entry["probka"] = _probka(rows, geo_roles, res)  # diagnoza: nagłówki, pierwsze wiersze, początek pliku
        report.append(entry)
        progress(f"{entry['zasob']}: {entry['rekordy']} rekordów")
    if geokoder is not None:
        geokoder.zapisz()
    return records, report
