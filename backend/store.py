"""Magazyn rekordów AED w pamięci: ładowanie źródeł, cache na dysku, szybkie zapytania."""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from scraping import danegov as source_danegov, osm as source_osm
from .hours import is_open
from .schema import AED, DOSTEP, FIELDS

log = logging.getLogger("aed.store")

ACCESS_CODES = list(DOSTEP.keys())  # indeks w kompaktowym formacie punktów


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Store:
    def __init__(self, base: Path, cfg: dict):
        self.base = base
        self.cfg = cfg
        self.cache_dir = base / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.by_source: dict[str, list[AED]] = {}
        self.status: dict[str, dict] = {}
        self.records: list[AED] = []
        self._points_cache: tuple[float, bytes] | None = None

    # ------------------------------------------------------------ ładowanie
    def _rebuild(self):
        order = [s for s in ("danegov", "osm") if s in self.by_source]
        self.records = [r for s in order for r in self.by_source[s]]
        self._points_cache = None

    def _save_cache(self, name: str, records: list[AED], report: list | None = None):
        path = self.cache_dir / f"{name}.json"
        payload = {"fetched_at": datetime.now().isoformat(timespec="seconds"),
                   "records": [r.to_dict() | {"extra": r.extra} for r in records], "report": report or []}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return payload["fetched_at"]

    def _load_cache(self, name: str) -> bool:
        path = self.cache_dir / f"{name}.json"
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        recs = [AED(**r) for r in payload["records"]]
        with self.lock:
            self.by_source[name] = recs
            self.status[name] = {"stan": "gotowe (z pamięci podręcznej)", "rekordy": len(recs),
                                 "pobrano": payload["fetched_at"], "raport": payload.get("report", [])}
            self._rebuild()
        return True

    def load_osm(self):
        src = self.cfg.get("osm", {})
        if not src.get("enabled", True):
            return
        path = (self.base / src.get("path", "../material/PL.geojson")).resolve()
        t = time.time()
        try:
            recs = source_osm.load(path)
        except FileNotFoundError:
            self.status["osm"] = {"stan": f"brak pliku {path}", "rekordy": 0}
            return
        with self.lock:
            self.by_source["osm"] = recs
            self.status["osm"] = {"stan": "gotowe", "rekordy": len(recs), "pobrano": datetime.fromtimestamp(
                path.stat().st_mtime).isoformat(timespec="seconds"), "plik": str(path)}
            self._rebuild()
        log.info("OSM: %d rekordów w %.2fs", len(recs), time.time() - t)

    def refresh_danegov(self):
        src = self.cfg.get("danegov", {})
        if not src.get("enabled", True):
            return
        with self.lock:
            prev = self.status.get("danegov", {})
            if prev.get("stan") == "pobieranie…":
                return
            self.status["danegov"] = {**prev, "stan": "pobieranie…", "postep": "łączenie z API"}

        def progress(msg):
            with self.lock:
                self.status["danegov"]["postep"] = msg

        try:
            recs, report = source_danegov.load(src, progress=progress)
            fetched = self._save_cache("danegov", recs, report)
            with self.lock:
                self.by_source["danegov"] = recs
                self.status["danegov"] = {"stan": "gotowe", "rekordy": len(recs), "pobrano": fetched,
                                          "raport": report}
                self._rebuild()
        except Exception as exc:  # noqa: BLE001
            log.warning("dane.gov.pl: błąd pobierania: %s", exc)
            with self.lock:
                self.status["danegov"] = {**self.status.get("danegov", {}), "stan": f"błąd: {exc}",
                                          "postep": ""}
                if "danegov" not in self.by_source:
                    self.status["danegov"]["rekordy"] = 0

    def start(self):
        self.load_osm()
        if not self._load_cache("danegov"):
            self.status["danegov"] = {"stan": "oczekuje", "rekordy": 0}
        threading.Thread(target=self.refresh_danegov, daemon=True).start()

    # ------------------------------------------------------------ zapytania
    def _open_code(self, r: AED, now: datetime) -> int:
        st = is_open(r.godziny_dostepnosci, now)
        return -1 if st is None else int(st)

    def points_json(self) -> bytes:
        """Kompaktowa lista punktów dla mapy. Cache 60 s (status 'otwarte teraz' zależy od czasu)."""
        with self.lock:
            if self._points_cache and time.time() - self._points_cache[0] < 60:
                return self._points_cache[1]
            now = datetime.now()
            sources = [s for s in ("danegov", "osm") if s in self.by_source]
            pts = [[r.szerokosc, r.dlugosc, sources.index(r.zrodlo), ACCESS_CODES.index(r.dostep),
                    self._open_code(r, now)] for r in self.records]
            body = json.dumps({"generated": now.isoformat(timespec="seconds"), "sources": sources,
                               "access": ACCESS_CODES, "points": pts}, separators=(",", ":")).encode()
            self._points_cache = (time.time(), body)
            return body

    def detail(self, idx: int) -> dict | None:
        with self.lock:
            if not 0 <= idx < len(self.records):
                return None
            r = self.records[idx]
            d = r.to_dict()
            d["dostep_opis"] = DOSTEP.get(r.dostep, r.dostep)
            d["otwarte_teraz"] = is_open(r.godziny_dostepnosci)
            d["zbior"] = r.extra.get("zbior", "")
            d["idx"] = idx
            return d

    @staticmethod
    def _search_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold().replace("ł", "l"))
        return "".join(char for char in normalized if not unicodedata.combining(char))

    def search(self, query: str = "", location: str = "", access: str = "", source: str = "",
               public_only: bool = False, limit: int = 25, offset: int = 0) -> dict:
        query = self._search_text(query.strip())
        location = self._search_text(location.strip())
        with self.lock:
            matches = []
            for idx, record in enumerate(self.records):
                if access and record.dostep != access:
                    continue
                if source and record.zrodlo != source:
                    continue
                if public_only and record.dostep != "publiczny":
                    continue

                fields = record.to_dict()
                fields["zbior"] = record.extra.get("zbior", "")
                searchable = self._search_text(" ".join(str(value) for value in fields.values()))
                if query and query not in searchable:
                    continue
                place_text = self._search_text(" ".join((
                    record.adres, record.opis_lokalizacji, record.nazwa_obiektu,
                    str(record.extra.get("zbior", "")),
                )))
                if location and location not in place_text:
                    continue
                matches.append(idx)

            total = len(matches)
            results = [self.detail(idx) for idx in matches[offset:offset + limit]]
            return {"wyniki": results, "razem": total, "limit": limit, "offset": offset}

    def nearest(self, lat: float, lon: float, n: int = 3, only_available: bool = True) -> list[dict]:
        now = datetime.now()
        with self.lock:
            cand = []
            dlat = 0.05  # ~5,5 km – najpierw zawężenie prostokątem, potem rozszerzanie
            while not cand and dlat < 3:
                dlon = dlat / max(0.2, math.cos(math.radians(lat)))
                for i, r in enumerate(self.records):
                    if abs(r.szerokosc - lat) <= dlat and abs(r.dlugosc - lon) <= dlon:
                        if only_available and (r.dostep == "prywatny" or self._open_code(r, now) == 0):
                            continue
                        cand.append((haversine_m(lat, lon, r.szerokosc, r.dlugosc), i))
                dlat *= 3
            cand.sort()
            out = []
            for dist, i in cand[:n]:
                d = self.detail(i)
                d["odleglosc_m"] = round(dist)
                out.append(d)
            return out

    def stats(self) -> dict:
        """Liczniki do strony startowej modułu i akcji promocyjnej."""
        with self.lock:
            now = datetime.now()
            open_now = sum(1 for r in self.records if self._open_code(r, now) == 1)
            return {
                "aed_razem": len(self.records),
                "aed_dane_gov_pl": len(self.by_source.get("danegov", [])),
                "aed_demo_osm": len(self.by_source.get("osm", [])),
                "dostepne_teraz": open_now,
                "zbiory_dane_gov_pl": len({r.extra.get("zbior") for r in self.by_source.get("danegov", [])}),
            }

    def sources_info(self) -> dict:
        with self.lock:
            return {
                "danegov": {"nazwa": source_danegov.LABEL, "licencja": "zgodnie z metadanymi każdego zbioru",
                            "w_eksporcie": True, **self.status.get("danegov", {})},
                "osm": {"nazwa": source_osm.LABEL, "licencja": source_osm.LICENSE,
                        "atrybucja": source_osm.ATTRIBUTION_URL, "w_eksporcie": False,
                        **self.status.get("osm", {})},
            }

    # ------------------------------------------------------------ eksport (wzorcowy zakres)
    def export_records(self) -> list[AED]:
        """Pobiera do eksportu wyłącznie aktualne rekordy z publicznego API dane.gov.pl."""
        src = self.cfg.get("danegov", {})
        records, _ = source_danegov.load(src)
        return records

    def export_csv(self) -> bytes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in self.export_records():
            d = r.to_dict()
            d["wewnatrz"] = "" if r.wewnatrz is None else ("tak" if r.wewnatrz else "nie")
            w.writerow(d)
        return ("﻿" + buf.getvalue()).encode("utf-8")

    def export_geojson(self) -> bytes:
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.dlugosc, r.szerokosc]},
                  "properties": {k: v for k, v in r.to_dict().items() if k not in ("szerokosc", "dlugosc")}}
                 for r in self.export_records()]
        return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode()

    def export_xlsx(self) -> bytes:
        """Eksportuje jeden arkusz zgodny ze wzorcowym schematem dane.gov.pl."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            from openpyxl.worksheet.table import Table, TableStyleInfo
        except ImportError as exc:
            raise RuntimeError("Brakuje biblioteki openpyxl. Zainstaluj zależności poleceniem: pip install openpyxl") from exc

        headers = [
            "numer_seryjny_aed", "szerokosc_geograficzna", "dlugosc_geograficzna",
            "wojewodztwo", "miejscowosc", "kod_pocztowy", "adres_uliczny",
            "wewnatrz_budynku", "nazwa_budynku", "dokladna_lokalizacja",
            "typ_dostepnosci", "godziny_dostepnosci", "czy_zamkniety",
            "status_operacyjny", "nazwa_operatora", "data_waznosci_elektrod",
            "data_waznosci_baterii", "data_aktualizacji_rekordu", "zrodlo_danych",
            "mozliwy_duplikat",
        ]

        records = self.export_records()
        serial_numbers = [r.id_aed if r.id_aed.startswith("SN-") else "" for r in records]
        duplicate_counts = {}
        for serial in serial_numbers:
            if serial:
                duplicate_counts[serial] = duplicate_counts.get(serial, 0) + 1

        wb = Workbook()
        ws = wb.active
        ws.title = "AED"
        ws.append(headers)

        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")

        for r, serial in zip(records, serial_numbers):
            if r.dostep == "publiczny":
                availability = "24/7"
            elif r.dostep == "w_godzinach":
                availability = "GODZINY_OTWARCIA"
            elif r.dostep in ("ograniczony", "prywatny"):
                availability = "TYLKO_PERSONEL"
            else:
                availability = None

            updated = None
            if r.data_weryfikacji:
                try:
                    updated = datetime.strptime(r.data_weryfikacji[:10], "%Y-%m-%d").date()
                except ValueError:
                    updated = None

            row = [
                serial or None,
                r.szerokosc,
                r.dlugosc,
                None,
                None,
                None,
                r.adres or None,
                None if r.wewnatrz is None else ("TRUE" if r.wewnatrz else "FALSE"),
                r.nazwa_obiektu or None,
                r.opis_lokalizacji or None,
                availability,
                r.godziny_dostepnosci or None,
                None,
                "NIEZNANY",
                r.dysponent or None,
                None,
                None,
                updated,
                r.zrodlo_url or r.zrodlo or None,
                "TRUE" if serial and duplicate_counts[serial] > 1 else "FALSE",
            ]
            ws.append(row)

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_view.showGridLines = False
        ws.row_dimensions[1].height = 30
        for column in ws.columns:
            max_length = max(len(str(cell.value)) for cell in column if cell.value is not None)
            ws.column_dimensions[column[0].column_letter].width = min(max(max_length + 2, 12), 45)

        if ws.max_row >= 2:
            table = Table(displayName="AEDData", ref=ws.dimensions)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showFirstColumn=False,
                showLastColumn=False, showRowStripes=True, showColumnStripes=False,
            )
            ws.add_table(table)

        for row_number in range(2, ws.max_row + 1):
            ws.cell(row=row_number, column=2).number_format = "0.000000"
            ws.cell(row=row_number, column=3).number_format = "0.000000"
            for col_number in (16, 17, 18):
                ws.cell(row=row_number, column=col_number).number_format = "yyyy-mm-dd"

        from io import BytesIO
        out = BytesIO()
        wb.save(out)
        return out.getvalue()
