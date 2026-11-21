"""Magazyn rekordów AED w pamięci: ładowanie źródeł, cache na dysku, szybkie zapytania."""
from __future__ import annotations

import io
import json
import logging
import math
import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from rozwiazanie.scraping import danegov as source_danegov
from .hours import is_open
from .schema import AED, DOSTEP

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
        self.std: list[dict] = []

    # ------------------------------------------------------------ ładowanie
    def _rebuild(self):
        """Rekordy + ich wiersze w złotym standardzie (do filtrów i podpowiedzi), z wyliczonym possible_duplicate."""
        from rozwiazanie.scraping.agregacja import _duplikaty, standard_rekordu
        self.records = list(self.by_source.get("danegov", []))
        std = []
        for r in self.records:
            row = standard_rekordu(r)
            r.extra["std"] = row
            std.append(row)
        dup = _duplikaty([x for x in std if x]) if all(std) else set()
        for i, row in enumerate(std):
            row["possible_duplicate"] = i in dup
        self.std = std
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
        for r in recs:  # starsze pliki cache: tytuły zbiorów z wyróżnieniem <mark> z wyszukiwarki API
            if "<" in str(r.extra.get("zbior", "")):
                r.extra["zbior"] = re.sub(r"<[^>]+>", "", r.extra["zbior"])
        with self.lock:
            self.by_source[name] = recs
            self.status[name] = {"stan": "gotowe (z pamięci podręcznej)", "rekordy": len(recs),
                                 "pobrano": payload["fetched_at"], "raport": payload.get("report", [])}
            self._rebuild()
        return True

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
            from rozwiazanie.scraping.geokod import Geokoder
            geo = Geokoder(self.cache_dir / "geokod.json", online=src.get("geokodowanie", True))
            recs, report = source_danegov.load(src, progress=progress, geokoder=geo)
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
            sources = ["danegov"]
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
            d["standard"] = dict(self.std[idx]) if idx < len(self.std) else {}  # kolumny chronione usuwa app.visible
            return d

    def filter_defs(self, role: str, protected=None) -> dict:
        from .filtry import definicje
        with self.lock:
            rows = list(self.std)
            ids = [r.id_aed for r in self.records]
        if protected is not None:
            rows = [{**row, **{k: v for k, v in protected.get(i).items() if v not in ("", None)}} for row, i in zip(rows, ids)]
        return definicje(rows, role)

    def suggest(self, phrase: str, limit: int = 8) -> list[dict]:
        from .filtry import podpowiedzi
        with self.lock:
            rows = list(self.std)
        return podpowiedzi(rows, phrase, limit)

    @staticmethod
    def _search_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold().replace("ł", "l"))
        return "".join(char for char in normalized if not unicodedata.combining(char))

    def search(self, query: str = "", location: str = "", access: str = "", source: str = "",
               public_only: bool = False, limit: int = 25, offset: int = 0, filtry: dict | None = None,
               protected=None) -> dict:
        """Wyszukiwanie. `filtry`: {pole: wartość} już przefiltrowane wg roli (backend/filtry.py: aktywne).
        `protected`: dane chronione (tylko dla administratora) dołączane do wiersza przed filtrowaniem."""
        from .filtry import pasuje
        query = self._search_text(query.strip())
        location = self._search_text(location.strip())
        filtry = filtry or {}
        now = datetime.now()
        with self.lock:
            matches = []
            for idx, record in enumerate(self.records):
                if filtry:
                    row = self.std[idx]
                    if protected is not None:
                        row = {**row, **{k: v for k, v in protected.get(record.id_aed).items() if v not in ("", None)}}
                    otwarte = is_open(record.godziny_dostepnosci, now) if "otwarte_teraz" in filtry else None
                    if record.dostep == "publiczny" and not record.godziny_dostepnosci:
                        otwarte = True if otwarte is None else otwarte
                    if not pasuje(row, filtry, otwarte):
                        continue
                if access and record.dostep != access:
                    continue
                if source and record.zrodlo != source:
                    continue
                if public_only and record.dostep != "publiczny":
                    continue

                fields = record.to_dict()
                fields["zbior"] = record.extra.get("zbior", "")
                if protected is not None:  # numer seryjny szuka tylko administrator
                    fields["aed_sn"] = protected.get(record.id_aed).get("aed_sn", "") or self.std[idx].get("aed_sn", "")
                searchable = self._search_text(" ".join(str(value) for value in fields.values()))
                if query and query not in searchable:
                    continue
                st = self.std[idx]
                place_text = self._search_text(" ".join((
                    record.adres, record.opis_lokalizacji, record.nazwa_obiektu,
                    str(record.extra.get("zbior", "")), st.get("city", ""), st.get("region", ""),
                    st.get("postal_code", ""), st.get("street_address", ""),
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
                "dostepne_teraz": open_now,
                "zbiory_dane_gov_pl": len({r.extra.get("zbior") for r in self.by_source.get("danegov", [])}),
            }

    def sources_info(self) -> dict:
        with self.lock:
            return {
                "danegov": {"nazwa": source_danegov.LABEL, "licencja": "zgodnie z metadanymi każdego zbioru",
                            "w_eksporcie": True, **self.status.get("danegov", {})},
            }

    # ------------------------------------------------------------ eksport (wzorcowy zakres)
    def export_records(self) -> list[AED]:
        """Rekordy z dane.gov.pl (jedyne źródło danych)."""
        with self.lock:
            return list(self.by_source.get("danegov", []))

    def register(self) -> dict:
        """Rejestr we wzorcowym zakresie dla portalu dane.gov.pl (zasób „Rejestr AED” zbioru)."""
        with self.lock:
            recs = list(self.by_source.get("danegov", []))
            info = self.status.get("danegov", {})
        return {"pobrano": info.get("pobrano"), "liczba": len(recs), "rekordy": [r.to_dict() for r in recs]}

    def aggregated_table(self, role: str = "publiczny", protected=None) -> tuple[list[dict], list[dict]]:
        """Jedna tabela we wzorcowym zakresie ze wszystkich zbiorów (rozwiazanie/scraping/agregacja.py).
        Dane z pamięci podręcznej, bez pobierania API przy każdym eksporcie."""
        from rozwiazanie.scraping.agregacja import agreguj
        with self.lock:
            fetched = self.status.get("danegov", {}).get("pobrano") or ""
        return agreguj(self.export_records(), role, protected, fetched)

    def export_csv(self, role: str = "publiczny", protected=None) -> bytes:
        from rozwiazanie.scraping.agregacja import do_csv
        return do_csv(*self.aggregated_table(role, protected))

    def export_xlsx(self, role: str = "publiczny", protected=None) -> bytes:
        """Wzorcowy zakres jako jeden arkusz XLSX (logika z natka_branch, poprawki w agregacja.py)."""
        from rozwiazanie.scraping.agregacja import do_xlsx
        return do_xlsx(*self.aggregated_table(role, protected))

    def export_geojson(self) -> bytes:
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.dlugosc, r.szerokosc]},
                  "properties": {k: v for k, v in r.to_dict().items() if k not in ("szerokosc", "dlugosc")}}
                 for r in self.export_records()]
        return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False).encode()
