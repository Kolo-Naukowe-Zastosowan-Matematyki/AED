"""Zbiór „System Ewidencji Zasobów AED” w formacie API dane.gov.pl (JSON:API, wersja 1.4).

Frontend portalu pokazuje ten zbiór swoimi własnymi komponentami, tak jak każdy inny zbiór:
  * w wyszukiwarce „Dane” (zbiór jest dopisywany do wyników /search, gdy fraza dotyczy AED),
  * na stronie zbioru /pl/dataset/aed,system-ewidencji-zasobow-aed (metadane, zakładki Dane /
    Warunki wykorzystywania / Historia zbioru, „Wyświetl dane poprzez API”),
  * na stronach zasobów /pl/dataset/aed,.../resource/<id>.

Zasoby zbioru (w tej kolejności):
  1. Rejestr AED   – plik CSV/GeoJSON z widokiem tabelarycznym (dane z rejestru),
  2. Mapa AED      – plik HTML z interaktywną mapą do pobrania (bez widoku tabelarycznego).
Dane zasobów pochodzą z serwisu AED (instancja B), do którego prowadzą też linki „Przejdź”.
Ustawienia: config.json, sekcja „zbior_aed”.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
from datetime import datetime, timezone

# Słownik pola „dostep” wzorcowego zakresu (ten sam co w serwisie AED; portal nie importuje kodu serwisu).
DOSTEP = {"publiczny": "Publiczny", "w_godzinach": "W godzinach otwarcia obiektu",
          "ograniczony": "Ograniczony (na zgłoszenie)", "prywatny": "Prywatny", "nieznany": "Brak informacji"}

DATASET_ID = "aed"  # identyfikator w adresach portalu: /pl/dataset/aed,system-ewidencji-zasobow-aed
SLUG = "system-ewidencji-zasobow-aed"
DATASET_IDS = {DATASET_ID, SLUG}
TZ = "+01:00"

# Słowa, po których zbiór pojawia się w wyszukiwarce portalu (porównanie bez wielkości liter).
SEARCH_WORDS = ("aed", "defibrylat", "ewidencj", "resuscytac", "pierwsza pomoc", "nagłe zatrzymanie")

DEFAULTS = {
    "tytul": "System Ewidencji Zasobów AED",
    "opis": (
        "<p>Zbiór udostępnia informacje o automatycznych defibrylatorach zewnętrznych (AED) dostępnych w Polsce: "
        "lokalizację (współrzędne geograficzne), dokładny opis miejsca, godziny dostępności i zasady dostępu. "
        "Dane są łączone ze zbiorów publikowanych w dane.gov.pl przez instytucje, samorządy i podmioty lecznicze.</p>"
        "<p>Błąd w danych można zgłosić przez „Zgłoś uwagi do zbioru”. Uwaga trafia do dostawcy zbioru, "
        "który poprawia dane u źródła.</p>"
        "<p>W skład zbioru wchodzą: rejestr AED oraz interaktywna mapa AED.</p>"
    ),
    "slowa_kluczowe": ["AED", "defibrylator", "zdrowie", "pierwsza pomoc", "ratownictwo",
                       "System Ewidencji Zasobów AED"],
    "kategoria": "Zdrowie",
    "czestotliwosc": "Codziennie",
    "zrodlo_url": "",
    "dostawca": {"id": "", "nazwa": "", "slug": ""},
    "licencja": "CC0 1.0",
    "udostepniono": "2026-11-21T12:00:00",
    # Strony serwisu AED (instancja B). Adres względny = względem serwis_url.
    "rejestr_url": "/",
    "mapa_url": "/mapa",
    "wyswietlenia": 0,
    "pobrania": 0,
}

# Kolumny widoku tabelarycznego rejestru: (pole rekordu, nagłówek, typ)
TABLE = [
    ("id_aed", "Identyfikator AED", "string"),
    ("nazwa_obiektu", "Nazwa obiektu", "string"),
    ("adres", "Adres", "string"),
    ("opis_lokalizacji", "Opis lokalizacji", "string"),
    ("szerokosc", "Szerokość geograficzna", "number"),
    ("dlugosc", "Długość geograficzna", "number"),
    ("wewnatrz", "Wewnątrz budynku", "string"),
    ("pietro", "Piętro", "string"),
    ("dostep", "Dostęp", "string"),
    ("godziny_dostepnosci", "Godziny dostępności", "string"),
    ("dysponent", "Dysponent", "string"),
    ("data_weryfikacji", "Data weryfikacji", "string"),
    ("zrodlo", "Źródło", "string"),
]
COLS = {f"col{i + 1}": t for i, t in enumerate(TABLE)}
ORG_COLUMNS = ["URL dostawcy", "Rodzaj instytucji", "Nazwa", "Skrót", "Id Instytucji", "REGON", "EPUAP",
               "Adres do doręczeń elektronicznych", "Strona internetowa", "Data utworzenia dostawcy",
               "Data aktualizacji dostawcy", "Liczba zbiorów danych", "Liczba zasobów dostawcy", "Kod pocztowy",
               "Miasto", "Rodzaj ulicy", "Ulica", "Numer ulicy", "Numer mieszkania", "Email", "Telefon"]
RES_COLUMNS = ["URL danych", "Tytuł danych", "Opis danych", "Data udostępnienia danych", "Dane na dzień",
               "Poziom otwartości danych", "Typ", "Format pliku", "Rozmiar pliku", "Liczba wyświetleń danych",
               "Liczba pobrań danych", "Tabela", "Mapa", "Wykres", "Zasób zawiera dane o wysokiej wartości",
               "Zasób zawiera dane o wysokiej wartości z wykazu KE", "Zasób zawiera dane dynamiczne",
               "Zasób zawiera dane badawcze", "Zawiera wykaz chronionych danych", "Lokalizacje danych",
               "URL pliku (do pobrania)", "znaki umowne",
               "Dokumenty uzupełniające zasobu (nazwa, język, url, rozmiar pliku)"]
ERR404 = (404, "application/json", {"errors": [{"status": "404", "detail": "nie znaleziono"}]})


def _cfg(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg.get("zbior_aed") or {}).items() if v not in (None, "")})
    return out


def _iso(s: str) -> str:
    return s if re.search(r"[+-]\d\d:\d\d$|Z$", s) else s + TZ


def _strip(html_text: str) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()
    return re.sub(r"\s+([.,;:])", r"\1", text)


def _xml(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _human_size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _ident(s: str) -> str:
    """'aed,system-...' / 'system-...' / 'aed' -> 'aed' (dla innych zbiorów: pierwsza część)."""
    parts = s.split(",")
    return DATASET_ID if any(p in DATASET_IDS for p in parts) else parts[0]


class AedDataset:
    def __init__(self, cfg: dict, serwis=None, serwis_url: str = ""):
        """`serwis`: klient serwisu AED (portal/backend/serwis_client.py), z którego pochodzą dane zasobów.
        `serwis_url`: publiczny adres serwisu AED, do którego prowadzą linki zbioru."""
        self.c = _cfg(cfg)
        self.serwis = serwis
        self.serwis_url = (self.c.get("serwis_url") or serwis_url or "").rstrip("/")
        self._lock = threading.Lock()

    # ================================================================ dane (z serwisu AED)
    def _register(self) -> dict:
        if self.serwis is None:
            return {"pobrano": None, "rekordy": []}
        return self.serwis.register()

    def _records(self) -> list[dict]:
        return self._register()["rekordy"]

    @staticmethod
    def _row(r: dict) -> dict:
        d = dict(r)
        w = r.get("wewnatrz")
        d["wewnatrz"] = "" if w is None else ("tak" if w else "nie")
        d["dostep"] = DOSTEP.get(r.get("dostep"), r.get("dostep"))
        d["zrodlo"] = "dane.gov.pl"
        return d

    def _data_date(self) -> str:
        """„Dane na dzień”: ostatnie pobranie danych z dane.gov.pl przez serwis AED, a gdy go nie było – teraz."""
        pobrano = self._register().get("pobrano")
        return _iso(pobrano[:19]) if pobrano else _now_iso()

    def _site(self, url: str) -> str:
        """Adres strony serwisu AED (pełny adres zostaje bez zmian)."""
        return url if url.startswith("http") else self.serwis_url + url

    # ================================================================ adresy
    @staticmethod
    def _api(origin: str) -> str:
        # Nie „/aed-api”: frontend portalu szuka id zbioru („aed”) w tym adresie, żeby zbudować linki do metadanych.
        return f"{origin}/api/1.4"

    @staticmethod
    def _abs(origin: str, url: str) -> str:
        return url if url.startswith("http") else origin + url

    def _source_url(self, origin: str) -> str:
        return self._site(self.c["zrodlo_url"] or self.c["rejestr_url"])

    def _institution(self):
        d = self.c["dostawca"] or {}
        if not d.get("nazwa"):
            return None
        return {"id": str(d.get("id") or "0"), "type": "institution",
                "attributes": {"title": d["nazwa"], "slug": d.get("slug") or ""}, "links": {"self": ""}}

    # ================================================================ zasoby
    def _resource_defs(self, origin: str) -> list[dict]:
        api = self._api(origin)
        rejestr_desc = ("Rejestr defibrylatorów AED we wzorcowym zakresie danych: identyfikator, nazwa obiektu, adres, "
                        "dokładny opis miejsca, współrzędne geograficzne, dostęp, godziny dostępności, dysponent, "
                        "data weryfikacji i źródło.")
        if self.c["rejestr_url"]:
            url = self._site(self.c["rejestr_url"])
            rejestr_desc += f' Rejestr online: <a href="{url}">{url}</a>.'
        mapa_url = self._site(self.c["mapa_url"])
        return [
            {"id": "aed-rejestr", "slug": "rejestr-aed", "title": "Rejestr AED", "media_type": "file",
             "format": "csv", "openness_score": 3, "visualization_types": ["table"], "tabular": True,
             "link": f"{api}/resources/aed-rejestr/rejestr_aed.csv",
             "files": [
                 {"download_url": f"{api}/resources/aed-rejestr/rejestr_aed.csv",
                  "file_size": len(self.register_csv()), "format": "csv", "openness_score": 3},
                 {"download_url": f"{api}/resources/aed-rejestr/rejestr_aed.geojson",
                  "file_size": len(self.register_geojson()), "format": "geojson", "openness_score": 3},
             ],
             "page_url": self._site(self.c["rejestr_url"]),
             "description": rejestr_desc},
            {"id": "aed-mapa", "slug": "mapa-aed", "title": "Mapa AED", "media_type": "file",
             "format": "html", "openness_score": 1, "visualization_types": [], "tabular": False,
             "link": f"{api}/resources/aed-mapa/mapa_aed.html",
             "files": [{"download_url": f"{api}/resources/aed-mapa/mapa_aed.html",
                        "file_size": len(self.map_html(origin)), "format": "html", "openness_score": 1}],
             "page_url": mapa_url,
             "description": ("Interaktywna mapa wszystkich AED z ewidencji w jednym pliku HTML. Po pobraniu otwiera się "
                             "w przeglądarce: kliknięcie punktu pokazuje opis miejsca, dostęp i godziny, a przycisk "
                             "„Moja lokalizacja” pokazuje, gdzie jesteś. "
                             f'Mapa online: <a href="{mapa_url}">{mapa_url}</a>.')},
        ]

    def _resource(self, d: dict, origin: str) -> dict:
        date = self._data_date()
        api = self._api(origin)
        rel = {"dataset": {"data": {"id": DATASET_ID, "type": "dataset"},
                           "links": {"related": f"{api}/datasets/{DATASET_ID},{SLUG}"}}}
        if d["tabular"]:
            rel["tabular_data"] = {"links": {"related": f"{api}/resources/{d['id']}/data"},
                                   "meta": {"count": len(self._records())}}
        return {
            "id": d["id"], "type": "resource",
            "attributes": {
                "title": d["title"], "slug": d["slug"], "description": f"<p>{d['description']}</p>",
                "media_type": d["media_type"], "link": d["link"], "format": d["format"],
                "files": d["files"], "download_url": d["files"][0]["download_url"] if d["files"] else None,
                "file_size": d["files"][0]["file_size"] if d["files"] else None,
                "openness_score": d["openness_score"], "visualization_types": d["visualization_types"],
                "data_date": date[:10], "created": _iso(self.c["udostepniono"]), "modified": date, "verified": date,
                "views_count": 0, "downloads_count": 0, "language": "pl", "status": "published",
                "regions": [], "supplements": [], "special_signs": [],
                "has_dynamic_data": False, "has_high_value_data": False,
                "has_high_value_data_from_ec_list": False, "has_research_data": False,
                "contains_protected_data": False, "is_chart_creation_blocked": True,
                # AED-MODULE: podstrona zasobu („Przejdź: Strona internetowa” obok „Pobierz”)
                "aed_page_url": d.get("page_url"),
            },
            "relationships": rel,
            "links": {"self": f"{api}/resources/{d['id']},{d['slug']}"},
        }

    def _find(self, rid: str, origin: str) -> dict | None:
        rid = rid.split(",")[0]
        return next((d for d in self._resource_defs(origin) if d["id"] == rid), None)

    # ================================================================ odpowiedzi API: zbiór
    def dataset(self, origin: str) -> dict:
        c = self.c
        date = self._data_date()
        inst = self._institution()
        api = self._api(origin)
        attrs = {
            "title": c["tytul"], "slug": SLUG, "notes": c["opis"],
            "keywords": c["slowa_kluczowe"], "tags": c["slowa_kluczowe"],
            "categories": [{"id": "health", "code": "HEAL", "title": c["kategoria"]}],
            "category": {"id": "health", "title": c["kategoria"]},
            "update_frequency": c["czestotliwosc"], "url": self._source_url(origin), "source": None,
            "created": _iso(c["udostepniono"]), "modified": date, "verified": date,
            "views_count": c["wyswietlenia"], "downloads_count": c["pobrania"],
            "likes_count": 0, "is_liked_by_current_user": False,
            "license_name": c["licencja"], "license_chosen": 1,
            "license_condition_source": False, "license_condition_original": False,
            "license_condition_modification": False, "license_condition_responsibilities": None,
            "license_condition_db_or_copyrighted": None, "license_condition_personal_data": None,
            "license_condition_cc40_responsibilities": False, "license_condition_custom_description": None,
            "regions": [], "supplements": [], "formats": ["csv", "geojson", "html"], "types": ["file", "website"],
            "visualization_types": ["table"], "openness_scores": [1, 3], "archived_resources_files_url": None,
            "image_url": None, "image_alt": None,
            "has_dynamic_data": False, "has_high_value_data": False, "has_high_value_data_from_ec_list": False,
            "has_research_data": False, "contains_protected_data": False, "status": "published",
        }
        rel = {"resources": {"meta": {"count": 3}, "links": {"related": f"{api}/datasets/{DATASET_ID}/resources"}},
               "showcases": {"meta": {"count": 0}, "data": []}}
        if inst:
            rel["institution"] = {"data": {"id": inst["id"], "type": "institution"}}
        self_url = f"{api}/datasets/{DATASET_ID},{SLUG}"
        return {"jsonapi": {"version": "1.4"},
                "data": {"id": DATASET_ID, "type": "dataset", "attributes": attrs, "relationships": rel,
                         "links": {"self": self_url}},
                "included": [inst] if inst else [], "links": {"self": self_url},
                "meta": {"language": "pl", "params": {}, "path": f"/datasets/{DATASET_ID},{SLUG}"}}

    def resources(self, origin: str) -> dict:
        items = [self._resource(d, origin) for d in self._resource_defs(origin)]
        return {"jsonapi": {"version": "1.4"}, "data": items, "included": [],
                "links": {"self": f"{self._api(origin)}/datasets/{DATASET_ID}/resources"},
                "meta": {"count": len(items), "language": "pl", "params": {}, "aggregations": {}}}

    def history(self, page: int = 1) -> dict:
        created = _iso(self.c["udostepniono"])
        entries = [{"id": f"h-{rid}", "type": "history",
                    "attributes": {"action": "INSERT", "table_name": "resource", "row_id": rid,
                                   "change_timestamp": created, "message": None,
                                   "new_value": {"title": title, "slug": slug, "dataset_id": f"{DATASET_ID},{SLUG}"}}}
                   for rid, title, slug in (("aed-mapa", "Mapa AED", "mapa-aed"),
                                            ("aed-rejestr", "Rejestr AED", "rejestr-aed"))]
        entries.append({"id": "h-ds", "type": "history",
                        "attributes": {"action": "INSERT", "table_name": "dataset", "row_id": DATASET_ID,
                                       "change_timestamp": created, "message": None,
                                       "new_value": {"title": self.c["tytul"], "slug": SLUG}}})
        return {"jsonapi": {"version": "1.4"}, "data": entries if page == 1 else [],
                "meta": {"count": len(entries)}, "links": {}}

    @staticmethod
    def empty_list() -> dict:
        return {"jsonapi": {"version": "1.4"}, "data": [], "included": [], "links": {},
                "meta": {"count": 0, "aggregations": {}, "params": {}}}

    def structured_data(self, origin: str) -> dict:
        c = self.c
        return {"@context": "https://schema.org", "@type": "Dataset", "name": c["tytul"],
                "description": re.sub(r"<[^>]+>", " ", c["opis"]).strip(), "keywords": c["slowa_kluczowe"],
                "license": "https://creativecommons.org/publicdomain/zero/1.0/", "inLanguage": "pl",
                "url": f"{origin}/pl/dataset/{DATASET_ID},{SLUG}", "dateModified": self._data_date()}

    def metadata_csv(self, origin: str) -> bytes:
        """Metadane zbioru w CSV jak w portalu (mcod: DatasetResourcesCSVSerializer): wiersz na zasób,
        kolumny zbioru, dostawcy i zasobu, separator „;”."""
        c, inst = self.c, (self.c["dostawca"] or {})
        ds_url = f"{origin}/pl/dataset/{DATASET_ID},{SLUG}"
        dataset = {
            "URL zbioru": ds_url, "Tytuł": c["tytul"], "Opis": _strip(c["opis"]),
            "Słowo kluczowe": ", ".join(c["slowa_kluczowe"]), "Kategoria": c["kategoria"],
            "Częstotliwość aktualizacji": c["czestotliwosc"], "Data udostępnienia zbioru": _iso(c["udostepniono"]),
            "Data aktualizacji zbioru": self._data_date(), "Liczba wyświetleń zbioru": c["wyswietlenia"],
            "Liczba pobrań zbioru": c["pobrania"], "Liczba danych": 3, "Liczba oznaczeń zbioru jako ulubiony": 0,
            "Warunki wykorzystywania": "", "Licencja": c["licencja"], "źródło": "",
            "Zbiór zawiera dane o wysokiej wartości": "NIE",
            "Zbiór zawiera dane o wysokiej wartości z wykazu KE": "NIE",
            "Zbiór zawiera dane dynamiczne": "NIE", "Zbiór zawiera dane badawcze": "NIE",
            "Lokalizacje zbiorów danych": "Polska",
            "Dokumenty uzupełniające zbioru (nazwa, język, url, rozmiar pliku)": "",
        }
        org_url = f"{origin}/pl/institution/{inst.get('id')},{inst.get('slug')}" if inst.get("id") else ""
        organization = dict.fromkeys(ORG_COLUMNS, "")
        organization.update({"URL dostawcy": org_url, "Nazwa": inst.get("nazwa") or "", "Id Instytucji": inst.get("id") or ""})
        rows = []
        for r in self.resources(origin)["data"]:
            a, vt = r["attributes"], r["attributes"]["visualization_types"]
            size = a["file_size"]
            rows.append({**dataset, **organization,
                         "URL danych": f"{ds_url}/resource/{r['id']},{a['slug']}",
                         "Tytuł danych": a["title"], "Opis danych": _strip(a["description"]),
                         "Data udostępnienia danych": a["created"], "Dane na dzień": a["data_date"],
                         "Poziom otwartości danych": a["openness_score"],
                         "Typ": {"file": "plik", "website": "strona internetowa", "api": "API"}[a["media_type"]],
                         "Format pliku": a["format"] or "", "Rozmiar pliku": _human_size(size) if size else "",
                         "Liczba wyświetleń danych": a["views_count"], "Liczba pobrań danych": a["downloads_count"],
                         "Tabela": "TAK" if "table" in vt else "NIE", "Mapa": "TAK" if "map" in vt else "NIE",
                         "Wykres": "TAK" if "chart" in vt else "NIE",
                         "Zasób zawiera dane o wysokiej wartości": "NIE",
                         "Zasób zawiera dane o wysokiej wartości z wykazu KE": "NIE",
                         "Zasób zawiera dane dynamiczne": "NIE", "Zasób zawiera dane badawcze": "NIE",
                         "Zawiera wykaz chronionych danych": "NIE", "Lokalizacje danych": "Polska",
                         "URL pliku (do pobrania)": a["download_url"] or "", "znaki umowne": "",
                         "Dokumenty uzupełniające zasobu (nazwa, język, url, rozmiar pliku)": ""})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(dataset) + ORG_COLUMNS + RES_COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)
        return ("\ufeff" + buf.getvalue()).encode("utf-8")

    def metadata_rdf(self, origin: str) -> bytes:
        """Metadane zbioru w RDF/XML (DCAT-AP), jak /catalog/dataset/<id>.rdf w portalu."""
        c, x = self.c, _xml
        ds_url = f"{origin}/pl/dataset/{DATASET_ID},{SLUG}"
        out = ['<?xml version="1.0" encoding="utf-8"?>',
               '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dcat="http://www.w3.org/ns/dcat#"'
               ' xmlns:dct="http://purl.org/dc/terms/" xmlns:foaf="http://xmlns.com/foaf/0.1/">',
               f'  <dcat:Dataset rdf:about="{x(ds_url)}">',
               f'    <dct:identifier>{x(ds_url)}</dct:identifier>',
               f'    <dct:title xml:lang="pl">{x(c["tytul"])}</dct:title>',
               f'    <dct:description xml:lang="pl">{x(_strip(c["opis"]))}</dct:description>',
               f'    <dct:issued rdf:datatype="http://www.w3.org/2001/XMLSchema#dateTime">{_iso(c["udostepniono"])}</dct:issued>',
               f'    <dct:modified rdf:datatype="http://www.w3.org/2001/XMLSchema#dateTime">{self._data_date()}</dct:modified>',
               '    <dct:language rdf:resource="http://publications.europa.eu/resource/authority/language/POL"/>',
               '    <dcat:theme rdf:resource="http://publications.europa.eu/resource/authority/data-theme/HEAL"/>',
               '    <dct:accrualPeriodicity rdf:resource="http://publications.europa.eu/resource/authority/frequency/DAILY"/>',
               f'    <dcat:landingPage rdf:resource="{x(ds_url)}"/>']
        out += [f'    <dcat:keyword xml:lang="pl">{x(k)}</dcat:keyword>' for k in c["slowa_kluczowe"]]
        if (c["dostawca"] or {}).get("nazwa"):
            out.append(f'    <dct:publisher><foaf:Agent><foaf:name>{x(c["dostawca"]["nazwa"])}</foaf:name></foaf:Agent></dct:publisher>')
        for r in self.resources(origin)["data"]:
            a = r["attributes"]
            out += ['    <dcat:distribution>',
                    f'      <dcat:Distribution rdf:about="{x(ds_url)}/resource/{r["id"]},{a["slug"]}">',
                    f'        <dct:title xml:lang="pl">{x(a["title"])}</dct:title>',
                    f'        <dct:description xml:lang="pl">{x(_strip(a["description"]))}</dct:description>',
                    f'        <dcat:accessURL rdf:resource="{x(a["link"])}"/>']
            out += [f'        <dcat:downloadURL rdf:resource="{x(f["download_url"])}"/>' for f in a["files"]]
            if a["format"]:
                out.append(f'        <dct:format>{x(a["format"].upper())}</dct:format>')
            out += ['        <dct:license rdf:resource="https://creativecommons.org/publicdomain/zero/1.0/"/>',
                    '      </dcat:Distribution>', '    </dcat:distribution>']
        out += ['  </dcat:Dataset>', '</rdf:RDF>', '']
        return "\n".join(out).encode("utf-8")

    # ================================================================ widok tabelaryczny rejestru
    def table(self, query: dict, origin: str) -> dict:
        rows = [self._row(r) for r in self._records()]
        q = (query.get("q") or "").strip()
        for part in [p.strip() for p in q.split(" AND ") if p.strip()]:
            m = re.match(r"(col\d+)(?:\.\w+)?\s*:\s*(.+)", part)
            if m and m.group(1) in COLS:
                field, needle = COLS[m.group(1)][0], m.group(2).strip("*\"' ").lower()
                rows = [r for r in rows if needle in str(r.get(field, "")).lower()]
            else:
                needle = part.strip("*\"' ").lower()
                rows = [r for r in rows if any(needle in str(r.get(f, "")).lower() for f, _, _ in TABLE)]
        sort = (query.get("sort") or "").strip()
        if sort.lstrip("-") in COLS:
            field, _, typ = COLS[sort.lstrip("-")]
            if typ == "number":
                rows.sort(key=lambda r: float(r.get(field) or 0), reverse=sort.startswith("-"))
            else:
                rows.sort(key=lambda r: str(r.get(field) or "").lower(), reverse=sort.startswith("-"))
        count = len(rows)
        page = max(1, int(query.get("page") or 1))
        per_page = min(100, max(1, int(query.get("per_page") or 20)))
        data = []
        for i, r in enumerate(rows[(page - 1) * per_page: page * per_page]):
            attrs = {}
            for col, (field, _, _) in COLS.items():
                v = r.get(field)
                attrs[col] = {"val": v, "repr": "" if v in (None, "") else str(v)}
            data.append({"id": f"row-{(page - 1) * per_page + i + 1}", "type": "row", "attributes": attrs})
        return {"jsonapi": {"version": "1.4"}, "data": data,
                "links": {"self": f"{self._api(origin)}/resources/aed-rejestr/data?page={page}&per_page={per_page}"},
                "meta": {"count": count, "language": "pl", "params": {"page": page, "per_page": per_page},
                         "headers_map": {col: t[1] for col, t in COLS.items()},
                         "data_schema": {"fields": [{"name": col, "type": t[2], "format": "default"}
                                                    for col, t in COLS.items()], "missingValues": [""]}}}

    def register_csv(self) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f for f, _, _ in TABLE])
        for r in self._records():
            d = self._row(r)
            w.writerow([d.get(f, "") for f, _, _ in TABLE])
        return ("\ufeff" + buf.getvalue()).encode("utf-8")

    def register_geojson(self) -> bytes:
        feats = []
        for r in self._records():
            d = self._row(r)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["dlugosc"], r["szerokosc"]]},
                          "properties": {f: d.get(f) for f, _, _ in TABLE if f not in ("szerokosc", "dlugosc")}})
        return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode()

    # ================================================================ interaktywna mapa (plik HTML)
    def map_html(self, origin: str) -> bytes:
        """Plik „Mapa AED” do pobrania: generuje go serwis AED."""
        return self.serwis.map_html() if self.serwis is not None else b""

    # ================================================================ wyszukiwarka portalu
    def search_item(self, origin: str) -> dict:
        ds = self.dataset(origin)["data"]
        a = ds["attributes"]
        attrs = {k: a[k] for k in ("title", "slug", "notes", "keywords", "categories", "category", "created",
                                   "modified", "verified", "has_dynamic_data", "has_high_value_data",
                                   "has_high_value_data_from_ec_list", "has_research_data", "likes_count",
                                   "is_liked_by_current_user", "source")}
        attrs.update({"model": "dataset", "is_promoted": False, "contains_protected_data": False, "regions": []})
        item = {"id": f"dataset-{DATASET_ID}", "type": "common", "attributes": attrs,
                "links": {"self": ds["links"]["self"]}}
        inst = self._institution()
        if inst:  # portal czyta relationships.institution.data i .links.related („…/institutions/<id>,<slug>”)
            item["relationships"] = {"institution": {
                "data": {"id": inst["id"], "type": "institution"},
                "links": {"related": f"https://api.dane.gov.pl/1.4/institutions/{inst['id']},{inst['attributes']['slug']}"}}}
        return item

    @staticmethod
    def search_matches(query: dict) -> bool:
        """Czy dopisać zbiór AED do wyników wyszukiwania portalu."""
        q = (query.get("q") or "").lower()
        if not q or not any(w in q for w in SEARCH_WORDS):
            return False
        if "dataset" not in query.get("model[terms]", "dataset").split(","):
            return False
        # inne filtry (instytucja, format, region...) – nie umiemy ich sprawdzić, więc wtedy nie dopisujemy
        allowed = {"q", "page", "per_page", "sort", "model[terms]", "lang", "include"}
        return not [k for k in query if k not in allowed and not k.startswith(("facet", "filtered_facet"))]

    def patch_search(self, status: int, body: bytes, query: dict, origin: str) -> bytes | None:
        """Dopisuje zbiór AED na początek wyników /search. None = odpowiedź bez zmian."""
        if not self.search_matches(query):
            return None
        try:
            resp = json.loads(body) if status == 200 else None
        except ValueError:
            resp = None
        if not isinstance(resp, dict) or not isinstance(resp.get("data"), list):  # brak sieci: sam zbiór AED
            resp = {"jsonapi": {"version": "1.4"}, "data": [], "links": {},
                    "meta": {"count": 0, "params": {}, "aggregations": {"counters": {"datasets": 0, "resources": 0}}}}
        meta = resp.setdefault("meta", {})
        meta["count"] = int(meta.get("count") or 0) + 1
        counters = meta.setdefault("aggregations", {}).setdefault("counters", {})
        counters["datasets"] = int(counters.get("datasets") or 0) + 1
        if int(query.get("page") or 1) == 1:
            resp["data"] = [self.search_item(origin)] + [x for x in resp["data"] if x.get("id") != f"dataset-{DATASET_ID}"]
        return json.dumps(resp, ensure_ascii=False).encode()

    # ================================================================ routing
    def handle(self, path: str, query: dict, origin: str):
        """(status, content_type, body) albo None, gdy zapytanie nie dotyczy zbioru AED.

        `path` jest ścieżką API bez prefiksu (/datasets/..., /resources/..., /histories, /catalog/...).
        """
        m = re.fullmatch(r"/datasets/([^/]+)(/.*)?", path)
        if m and _ident(m.group(1)) == DATASET_ID:
            sub = m.group(2) or ""
            if sub == "":
                return 200, "application/vnd.api+json", self.dataset(origin)
            if sub == "/resources":
                return 200, "application/vnd.api+json", self.resources(origin)
            if sub in ("/showcases", "/comments"):
                return 200, "application/vnd.api+json", self.empty_list()
            if sub == "/likes":
                return 200, "application/vnd.api+json", {"data": {"attributes": {"likes_count": 0}}}
            if sub == "/resources/metadata.csv":
                return 200, "text/csv; charset=utf-8", self.metadata_csv(origin), f"{DATASET_ID}.csv"
            return ERR404
        m = re.fullmatch(r"/resources/(aed-[a-z]+)(?:,[^/]*)?(/.*)?", path)
        if m:
            d = self._find(m.group(1), origin)
            if d is None:
                return ERR404
            sub = m.group(2) or ""
            if sub == "":
                return 200, "application/vnd.api+json", {
                    "jsonapi": {"version": "1.4"}, "data": self._resource(d, origin),
                    "links": {"self": f"{self._api(origin)}/resources/{d['id']}"}, "meta": {"language": "pl"}}
            if sub == "/data" and d["tabular"]:
                return 200, "application/vnd.api+json", self.table(query, origin)
            if sub == "/rejestr_aed.csv" and d["id"] == "aed-rejestr":
                return 200, "text/csv; charset=utf-8", self.register_csv()
            if sub == "/rejestr_aed.geojson" and d["id"] == "aed-rejestr":
                return 200, "application/geo+json", self.register_geojson()
            if sub == "/mapa_aed.html" and d["id"] == "aed-mapa":
                return 200, "text/html; charset=utf-8", self.map_html(origin)
            return 200, "application/vnd.api+json", self.empty_list()  # /charts, /comments itp.
        if path == "/histories" and query.get("row_id") and _ident(query["row_id"]) == DATASET_ID:
            return 200, "application/vnd.api+json", self.history(int(query.get("page", 1) or 1))
        m = re.fullmatch(r"/catalog/dataset/([^/]+?)(\.rdf|\.xml)?(/resource/[^/]+)?", path)
        if m and _ident(m.group(1)) == DATASET_ID:
            if m.group(2):  # „Pobierz metadane: RDF”
                return 200, "application/rdf+xml; charset=utf-8", self.metadata_rdf(origin)
            return 200, "application/ld+json", self.structured_data(origin)
        return None
