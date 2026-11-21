"""Geokodowanie adresów bez współrzędnych: Usługa Geokodowania GUGiK (UUG, dane PRG, bezpłatna, bez klucza).

  adres("ul. Piłsudskiego 95, 05-270 Marki") -> {"lat", "lon", "region", "city"}
  odwrotne(52.32, 21.10)                      -> {"region", "city", "street_address", "postal_code"}
                                                 (najbliższy punkt adresowy; województwo z kodu TERYT)

Wyniki są zapisywane w data/cache/geokod.json (plik jest w repozytorium), więc każdy adres pytamy tylko raz.
Zwykły start serwisu korzysta wyłącznie z tego pliku i nie łączy się z GUGiK; nowe zapytania wysyła tylko
osobny krok: python -m rozwiazanie.scraping.run --geokoduj (limit zapytań na przebieg, odstęp między nimi).
Po błędzie sieci albo odmowie geokoder wyłącza się do końca przebiegu, a odmowę („blocked for abuse”, HTTP 429/403)
zapamiętuje w pliku na BLOKADA_H godzin, żeby kolejne uruchomienia nie przedłużały blokady.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from rozwiazanie.scraping.standard import TERYT_WOJ, do_puwg1992, liczba, w_polsce

log = logging.getLogger("aed.geokod")
UUG = "https://services.gugik.gov.pl/uug/"
PAUZA_S = 1.0  # odstęp między zapytaniami; zbyt częste kończą się blokadą „blocked for abuse”
LIMIT = 300  # najwięcej zapytań w jednym przebiegu
BLOKADA_H = 24  # po odmowie GUGiK nie pytamy przez tyle godzin
USER_AGENT = "aed-prototyp/0.2 (agregator rejestrow AED z dane.gov.pl; Python-urllib)"


def _pierwszy_wynik(body: dict) -> dict | None:
    res = body.get("results") if isinstance(body, dict) else None
    if isinstance(res, dict) and res:
        return next(iter(res.values()))
    if isinstance(res, list) and res:
        return res[0]
    return None


def _z_wyniku(r: dict) -> dict:
    out: dict = {}
    lon, lat = liczba(r.get("x")), liczba(r.get("y"))
    m = re.search(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)", str(r.get("geometry_wkt", "")))
    if (lat is None or lon is None or not w_polsce(lat, lon)) and m:
        lon, lat = float(m.group(1)), float(m.group(2))
    if lat is not None and lon is not None and w_polsce(lat, lon):
        out["lat"], out["lon"] = round(lat, 6), round(lon, 6)
    teryt = str(r.get("teryt") or r.get("terc") or "")
    if len(teryt) >= 2:
        out["region"] = TERYT_WOJ.get(teryt[:2], "")
    if r.get("city"):
        out["city"] = str(r["city"])
    street = str(r.get("street") or "").strip()
    number = str(r.get("number") or "").strip()
    if number:
        out["street_address"] = f"{street} {number}".strip() if street else f"{r.get('city') or ''} {number}".strip()
    code = str(r.get("code") or r.get("postcode") or "").strip()
    if code:
        out["postal_code"] = code
    return out


class Geokoder:
    def __init__(self, cache_path: Path, online: bool = True, limit: int = LIMIT, user_agent: str = ""):
        self.path = cache_path
        self.online = online
        self.limit = limit
        self.user_agent = user_agent or USER_AGENT
        self.lock = threading.Lock()
        self.pytania = 0
        self.wariant = 0  # wariant zapytania odwrotnego, który ostatnio zadziałał
        self.blokada = ""  # komunikat GUGiK, gdy odmówił obsługi (np. blokada za zbyt wiele zapytań)
        self.limit_osiagniety = False
        try:
            self.cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        except (OSError, ValueError):
            self.cache = {}
        b = self.cache.get("_blokada")
        if online and isinstance(b, dict) and str(b.get("do", "")) > datetime.now().isoformat(timespec="seconds"):
            self.online = False
            self.blokada = f"{b.get('powod', '')}; wstrzymane do {str(b['do']).replace('T', ' ')[:16]}"
            log.warning("Geokoder GUGiK: %s", self.blokada)

    def _odmowa(self, powod: str):
        self.blokada = powod[:200]
        self.online = False
        do = (datetime.now() + timedelta(hours=BLOKADA_H)).isoformat(timespec="seconds")
        with self.lock:
            self.cache["_blokada"] = {"powod": self.blokada, "do": do}
        log.warning("Geokoder GUGiK odmówił (%s), nie pytam do %s", self.blokada, do.replace("T", " ")[:16])

    def _get(self, params: dict) -> dict | None:
        if self.pytania >= self.limit:
            if not self.limit_osiagniety:
                log.warning("Geokoder GUGiK: limit %d zapytań w przebiegu, resztę dokończy kolejny", self.limit)
            self.limit_osiagniety = True
            self.online = False
            return None
        url = UUG + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429, 503):
                self._odmowa(f"HTTP {exc.code}")
            else:
                log.warning("Geokoder GUGiK niedostępny (%s), wyłączam do końca przebiegu", exc)
                self.online = False
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("Geokoder GUGiK niedostępny (%s), wyłączam do końca przebiegu", exc)
            self.online = False
            return None
        finally:
            time.sleep(PAUZA_S)
        self.pytania += 1
        if not isinstance(body, dict) or ("results" not in body and body.get("notice")):
            # np. {"notice": "blocked for abuse"}: to nie jest odpowiedź „brak adresu”, więc nic nie zapamiętujemy
            self._odmowa(str(body.get("notice") if isinstance(body, dict) else body))
            return None
        return body

    def _zapytaj(self, key: str, params: dict) -> dict | None:
        with self.lock:
            if key in self.cache:
                return self.cache[key] or None
        if not self.online:
            return None
        body = self._get(params)
        if body is None:
            return None
        r = _pierwszy_wynik(body)
        out = _z_wyniku(r) if r else {}
        with self.lock:
            self.cache[key] = out
        return out or None

    def adres(self, query: str) -> dict | None:
        q = re.sub(r"\b(ul|al|pl|os)\.\s*", "", query, flags=re.I).strip(" ,")
        if not q:
            return None
        out = self._zapytaj("a:" + q.lower(), {"request": "GetAddress", "address": q, "srid": "4326"})
        return out if out and "lat" in out else None

    def odwrotne(self, lat: float, lon: float) -> dict | None:
        """Najbliższy punkt adresowy. Kolejność osi w POINT bywa różnie rozumiana (EPSG:4326 lat/lon albo lon/lat,
        EPSG:2180 x/y), więc pytamy w kolejnych wariantach; zły wariant wypada poza Polskę i nie daje wyniku.
        Wariant, który zadziałał, zapamiętujemy (także w pliku), żeby kolejne punkty pytać jednym zapytaniem."""
        key = f"r3:{lat:.5f},{lon:.5f}"  # r3: odpowiedzi z blokady GUGiK z wersji r2 były zapisane jako puste
        with self.lock:
            if key in self.cache:
                return self.cache[key] or None
        east, north = do_puwg1992(lat, lon)
        warianty = [{"location": f"POINT({lon} {lat})", "srid": "4326"},
                    {"location": f"POINT({lat} {lon})", "srid": "4326"},
                    {"location": f"POINT({east:.1f} {north:.1f})", "srid": "2180"},
                    {"location": f"POINT({north:.1f} {east:.1f})", "srid": "2180"}]
        znany = self.cache.get("_wariant")
        if isinstance(znany, int) and 0 <= znany < len(warianty):
            kolejnosc = [znany]
        else:
            kolejnosc = [self.wariant] + [i for i in range(len(warianty)) if i != self.wariant]
        for i in kolejnosc:
            if not self.online:
                return None
            body = self._get({"request": "GetAddressReverse", **warianty[i]})
            r = _pierwszy_wynik(body) if body is not None else None
            out = _z_wyniku(r) if r else {}
            if out.get("region") or out.get("street_address"):
                self.wariant = i
                with self.lock:
                    self.cache[key] = out
                    self.cache["_wariant"] = i
                return out
        if self.online:  # pusty wynik zapamiętujemy tylko, gdy odpowiedziały wszystkie warianty
            with self.lock:
                self.cache[key] = {}
        return None

    def zapisz(self):
        with self.lock:  # posortowane, po jednym wpisie w wierszu: czytelne różnice w git
            data = json.dumps(self.cache, ensure_ascii=False, sort_keys=True, indent=0) + "\n"
        try:
            if self.path.read_text(encoding="utf-8") == data:
                return  # bez zmian: nie ruszamy pliku śledzonego w git
        except OSError:
            pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self.path)
