"""Serwis AED (instancja B): własny frontend, backend i scraping, niezależny od dane.gov.pl.

    /                 rejestr AED (strona główna, rozwiazanie/frontend/index.html)
    /mapa             mapa wszystkich AED
    /aed-api/...      API serwisu (opis w README.md)

Portal dane.gov.pl (instancja A) tylko linkuje do tych stron i pobiera z /aed-api/rejestr.json dane
do zasobów zbioru „System Ewidencji Zasobów AED”. Tylko biblioteka standardowa Pythona.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
import urllib.parse
from http import HTTPStatus
from pathlib import Path

from common.http import BaseHandler
from rozwiazanie.backend.auth import Auth
from rozwiazanie.backend.columns import ProtectedData, apply_role, columns_for
from rozwiazanie.backend.map_export import build_map_html
from rozwiazanie.backend.store import Store

log = logging.getLogger("aed.serwis")
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PAGES = {"/": "index.html", "/index.html": "index.html", "/rejestr.html": "index.html"}


class SerwisHandler(BaseHandler):
    store: Store = None
    auth: Auth = None
    protected: ProtectedData = None
    title = "Rejestr AED"
    server_version = "aed-rozwiazanie/0.3"
    _map_cache: dict = {}
    _map_lock = threading.Lock()

    def _route(self, method: str):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/aed-api/"):
            try:
                return self._api(method, url.path[len("/aed-api"):], dict(urllib.parse.parse_qsl(url.query)))
            except (KeyError, ValueError) as exc:
                return self._json({"blad": str(exc) or "nieprawidłowe parametry"}, HTTPStatus.BAD_REQUEST)
        if method == "GET" and url.path.rstrip("/") in ("/mapa", "/mapa.html"):
            return self._send(self._map(""), "text/html; charset=utf-8", extra={"Cache-Control": "no-cache"})
        if method == "GET" and url.path.startswith("/vendor/"):
            return self._vendor(url.path)
        if method == "GET" and url.path in PAGES:
            body = (FRONTEND / PAGES[url.path]).read_bytes()
            return self._send(body, "text/html; charset=utf-8", extra={"Cache-Control": "no-cache"})
        self._send("<h1>Nie znaleziono</h1><p><a href='/'>Rejestr AED</a></p>".encode(),
                   "text/html; charset=utf-8", HTTPStatus.NOT_FOUND)

    def _vendor(self, path: str):
        """Biblioteki dołączone do serwisu (Leaflet), żeby strony działały też bez dostępu do CDN."""
        root = (FRONTEND / "vendor").resolve()
        target = (FRONTEND / urllib.parse.unquote(path).lstrip("/")).resolve()
        if root not in target.parents or not target.is_file():
            return self._send(b"nie znaleziono", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self._send(target.read_bytes(), ctype, extra={"Cache-Control": "public, max-age=86400"})

    def _map(self, site_url: str) -> bytes:
        """Mapa jako strona serwisu (site_url="") albo plik do pobrania (pełny adres serwisu w linkach)."""
        recs = list(self.store.records)
        with self._map_lock:
            c = self._map_cache.get(site_url)
            if c and c[1] == len(recs) and time.time() - c[0] < 300:
                return c[2]
            date = (self.store.sources_info().get("danegov", {}).get("pobrano") or time.strftime("%Y-%m-%d"))[:10]
            html = build_map_html(recs, self.title, date, site_url)
            self._map_cache[site_url] = (time.time(), len(recs), html)
            return html

    def _api(self, method: str, p: str, q: dict):
        s = self.store
        # Rola z tokenu (ciasteczko serwisu albo JWT portalu). Kolumny chronione tylko dla administratora.
        role = self.auth.role(self.headers)

        def visible(item: dict) -> dict:
            return apply_role(item, role, self.protected)

        if method == "GET":
            if p == "/auth/rola":
                return self._json({"rola": role, "tryb": self.auth.mode, "dane_demo": self.protected.demo})
            if p == "/kolumny":
                return self._json({"rola": role, "kolumny": columns_for(role)})
            if p == "/search":
                limit = min(max(int(q.get("limit", 25)), 1), 100)
                offset = max(int(q.get("offset", 0)), 0)
                res = s.search(q.get("q", ""), q.get("miejsce", ""), q.get("dostep", ""),
                               q.get("zrodlo", ""), q.get("publiczny", "0") == "1", limit, offset)
                res["wyniki"] = [visible(r) for r in res["wyniki"]]
                res["rola"] = role
                return self._json(res)
            if p == "/points":
                return self._send(s.points_json(), "application/json", extra={"Cache-Control": "no-store"})
            if p.startswith("/aed/"):
                d = s.detail(int(p.rsplit("/", 1)[1]))
                return self._json(visible(d)) if d else self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)
            if p == "/nearest":
                res = s.nearest(float(q["lat"]), float(q["lon"]), min(int(q.get("n", 3)), 20),
                                q.get("tylko_dostepne", "1") != "0")
                return self._json({"wyniki": [visible(r) for r in res], "rola": role})
            if p == "/sources":
                return self._json(s.sources_info())
            if p == "/stats":
                return self._json(s.stats())
            if p == "/rejestr.json":  # zasób na portalu dane.gov.pl: zawsze tylko kolumny publiczne
                return self._json(s.register())
            if p == "/export.xlsx":  # wzorcowy zakres; administrator dostaje też kolumny chronione
                return self._send(s.export_xlsx(role, self.protected),
                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition": 'attachment; filename="rejestr_aed.xlsx"',
                                         "Cache-Control": "no-store"})
            if p == "/export.csv":
                return self._send(s.export_csv(role, self.protected), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="rejestr_aed.csv"'})
            if p == "/export.geojson":
                return self._send(s.export_geojson(), "application/geo+json",
                                  extra={"Content-Disposition": 'attachment; filename="rejestr_aed.geojson"'})
            if p == "/mapa_aed.html":
                return self._send(self._map(self._origin()), "text/html; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="mapa_aed.html"'})
        if method == "POST":
            if p == "/auth/login":
                payload = json.loads(self._body(4 * 1024) or b"{}")
                token = self.auth.login(payload.get("haslo", ""))
                if not token:
                    log.warning("Nieudane logowanie administratora z %s", self.address_string())
                    return self._json({"blad": "nieprawidłowe hasło"}, HTTPStatus.UNAUTHORIZED)
                return self._json({"rola": "admin"}, extra={"Set-Cookie": self.auth.cookie_header(token)})
            if p == "/auth/logout":
                self.auth.logout(self.headers)
                return self._json({"rola": "publiczny"}, extra={"Set-Cookie": self.auth.cookie_header("", 0)})
            if p == "/refresh":
                threading.Thread(target=s.refresh_danegov, daemon=True).start()
                return self._json({"ok": True}, HTTPStatus.ACCEPTED)
        self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)


def setup(base: Path, cfg: dict, offline: bool):
    """Przygotowuje magazyn danych i zwraca klasę obsługi żądań serwisu."""
    if offline:
        cfg.setdefault("danegov", {})["enabled"] = False
    store = Store(base, cfg)
    store.start()
    if offline:
        store._load_cache("danegov")
    SerwisHandler.store = store
    SerwisHandler.auth = Auth(cfg.get("auth"))
    SerwisHandler.protected = ProtectedData(base)
    SerwisHandler.title = (cfg.get("serwis") or {}).get("tytul", "Rejestr AED")
    return SerwisHandler
