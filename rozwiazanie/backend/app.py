"""Widoki rejestru AED dla Django w środowisku mcod."""
from __future__ import annotations

import json
import os
import logging
import mimetypes
import threading
import time
import urllib.parse
from datetime import date
from http import HTTPStatus
from pathlib import Path

from django.contrib.auth import logout
from django.http import HttpResponse, JsonResponse
from rozwiazanie.backend.auth import Auth, ROLE_SLUZBY
from rozwiazanie.backend.columns import PROTECTED_FIELDS, ROLE_ADMIN, ProtectedData, apply_role, columns_for
from rozwiazanie.backend.filtry import aktywne as active_filters
from rozwiazanie.backend.map_export import build_map_html
from rozwiazanie.backend.store import Store

log = logging.getLogger("aed.serwis")
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PAGES = {"/": "index.html", "/index.html": "index.html", "/rejestr.html": "index.html",
         "/tabela": "tabela.html", "/tabela.html": "tabela.html"}


class Rejestr:
    def __init__(self, request):
        self.request = request
        self.path = request.get_full_path()
        self.headers = request.headers

    def _origin(self):
        return self.request.build_absolute_uri("/").rstrip("/")

    @staticmethod
    def _send(body, ctype, status=200, extra=None):
        response = HttpResponse(body, content_type=ctype, status=status)
        for name, value in (extra or {}).items():
            response[name] = value
        return response

    @staticmethod
    def _json(obj, status=200):
        return JsonResponse(obj, safe=False, status=status, json_dumps_params={"ensure_ascii": False})

    store: Store = None
    auth: Auth = None
    protected: ProtectedData = None
    title = "Rejestr AED"
    server_version = "aed-rozwiazanie/0.3"
    _map_cache: dict = {}
    _map_lock = threading.Lock()

    def _route(self, method: str):
        if os.environ.get("AED_KATALOG") == "1":
            self.store.reload_published()
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
        return self._send("<h1>Nie znaleziono</h1><p><a href='/'>Rejestr AED</a></p>".encode(),
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
        return self._send(target.read_bytes(), ctype, extra={"Cache-Control": "public, max-age=86400"})

    def _map(self, site_url: str) -> bytes:
        """Mapa jako strona serwisu (site_url="") albo plik do pobrania (pełny adres serwisu w linkach)."""
        recs = list(self.store.records)
        with self._map_lock:
            version = (len(recs), getattr(self.store, "_published_stamp", None))
            c = self._map_cache.get(site_url)
            if c and c[1] == version and time.time() - c[0] < 300:
                return c[2]
            date = (self.store.sources_info().get("danegov", {}).get("pobrano") or time.strftime("%Y-%m-%d"))[:10]
            html = build_map_html(recs, self.title, date, site_url)
            self._map_cache[site_url] = (time.time(), version, html)
            return html

    def _api(self, method: str, p: str, q: dict):
        s = self.store
        # Rola z tokenu (ciasteczko serwisu albo JWT portalu). Kolumny chronione tylko dla administratora.
        user = self.request.user
        if user.is_authenticated:
            role = ROLE_ADMIN if user.is_superuser else "publiczny"
            if not user.is_superuser and user.groups.filter(name="Służby AED").exists():
                role = ROLE_SLUZBY
            account = {"rola": role, "uzytkownik": user.fullname or user.email}
        else:
            account = self.auth.account(self.headers)
        role = account["rola"]

        def visible(item: dict) -> dict:
            out = apply_role(item, role, self.protected)
            if isinstance(out.get("standard"), dict):  # wiersz złotego standardu: chronione tylko dla administratora
                std = out["standard"]
                if role == ROLE_ADMIN:
                    std.update({k: v for k, v in self.protected.get(str(item.get("id_aed", ""))).items() if v})
                else:
                    out["standard"] = {k: v for k, v in std.items() if k not in PROTECTED_FIELDS}
            return out

        if method == "GET":
            if p == "/auth/rola":
                return self._json({"rola": role, "uzytkownik": account["uzytkownik"], "dane_demo": self.protected.demo})
            if p == "/auth/zaloguj":  # formularz „Zaloguj się” portalu dane.gov.pl, po zalogowaniu powrót tutaj
                return self._send(b"", "text/plain", HTTPStatus.FOUND,
                                  {"Location": self.auth.login_url or "/", "Cache-Control": "no-store"})
            if p == "/kolumny":
                return self._json({"rola": role, "kolumny": columns_for(role)})
            if p == "/search":
                # wszystko=1: pełny zestaw wyników dla widoków Tabela i Mapa na stronie rejestru
                limit = min(max(int(q.get("limit", 25)), 1), 5000 if q.get("wszystko") == "1" else 100)
                offset = max(int(q.get("offset", 0)), 0)
                # „Nazwa obiektu lub numer AED” i filtry po kolumnach chronionych: tylko administrator (wymuszone tu)
                res = s.search(q.get("q", "") if role in (ROLE_ADMIN, ROLE_SLUZBY) else "", q.get("miejsce", ""), q.get("dostep", ""),
                               q.get("zrodlo", ""), q.get("publiczny", "0") == "1", limit, offset,
                               filtry=active_filters(q, role),
                               protected=self.protected if role == ROLE_ADMIN else None,
                               lat=_liczba(q.get("lat")), lon=_liczba(q.get("lon")))
                res["wyniki"] = [visible(r) for r in res["wyniki"]]
                res["rola"] = role
                return self._json(res)
            if p == "/filtry":  # definicje filtrów dla roli (kolumny chronione tylko dla administratora)
                # opcje i liczniki dla bieżącego wyszukiwania (fraza tylko administratora, miejsce)
                return self._json(s.filter_defs(role, self.protected if role == ROLE_ADMIN else None,
                                                q.get("q", "") if role in (ROLE_ADMIN, ROLE_SLUZBY) else "", q.get("miejsce", "")))
            if p == "/podpowiedzi":  # podpowiedzi do pola adresu: miejscowości, ulice, województwa, kody
                return self._json({"podpowiedzi": s.suggest(q.get("q", ""), min(int(q.get("n", 8)), 15))})
            if p == "/points":
                return self._send(s.points_json(), "application/json", extra={"Cache-Control": "no-store"})
            if p.startswith("/aed/"):
                d = s.detail(int(p.rsplit("/", 1)[1]))
                return self._json(visible(d)) if d else self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)
            if p == "/nearest":
                # w obrębie kryteriów z wyszukiwarki: miejsce, fraza (administrator) i filtry dozwolone dla roli
                kryteria = {"query": q.get("q", "") if role in (ROLE_ADMIN, ROLE_SLUZBY) else "", "location": q.get("miejsce", ""),
                            "filtry": active_filters(q, role),
                            "protected": self.protected if role == ROLE_ADMIN else None}
                res = s.nearest(float(q["lat"]), float(q["lon"]), min(int(q.get("n", 3)), 20),
                                q.get("tylko_dostepne", "1") != "0", **kryteria)
                return self._json({"wyniki": [visible(r) for r in res], "rola": role})
            if p == "/sources":
                return self._json(s.sources_info())
            if p == "/stats":
                return self._json(s.stats())
            if p == "/rejestr.json":  # zasób na portalu dane.gov.pl: zawsze tylko kolumny publiczne
                return self._json(s.register())
            if p == "/tabela":  # widok „Tabela”: zagregowana tabela we wzorcowym zakresie, kolumny wg roli
                cols, rows = s.aggregated_table(role, self.protected)
                # bez wewnętrznego identyfikatora rekordu (_id): nie pokazujemy go w interfejsie ani eksportach
                rows = [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items() if k != "_id"} for r in rows]
                return self._json({"rola": role, "kolumny": cols, "rekordy": rows, "liczba": len(rows),
                                   "pobrano": s.sources_info().get("danegov", {}).get("pobrano")})
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
            if p == "/auth/logout":
                self.auth.logout(self.headers)
                logout(self.request)
                response = self._json({"rola": "publiczny"})
                from django.conf import settings
                response.delete_cookie(settings.API_TOKEN_COOKIE_NAME, domain=settings.SESSION_COOKIE_DOMAIN)
                return response
            if p == "/refresh":
                if os.environ.get("AED_KATALOG") == "1":
                    s.reload_published()
                else:
                    threading.Thread(target=s.refresh_danegov, daemon=True).start()
                return self._json({"ok": True}, HTTPStatus.ACCEPTED)
        return self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)


def _liczba(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def setup(base: Path, cfg: dict, offline: bool):
    """Przygotowuje magazyn danych i zwraca klasę obsługi żądań serwisu."""
    if offline:
        cfg.setdefault("danegov", {})["enabled"] = False
    store = Store(base, cfg)
    if os.environ.get("AED_KATALOG") == "1":
        store._load_cache("danegov")
    else:
        store.start()
    Rejestr.store = store
    Rejestr.auth = Auth(cfg.get("auth"))
    Rejestr.protected = store.protected
    Rejestr.title = (cfg.get("serwis") or {}).get("tytul", "Rejestr AED")
    return Rejestr
