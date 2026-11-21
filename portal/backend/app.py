"""Makieta portalu dane.gov.pl (instancja A): oryginalny frontend portalu i jego API, a w nich nasz zbiór.

Jedyna zmiana względem portalu to zbiór „System Ewidencji Zasobów AED”:
  * /api/datasets/aed..., /api/resources/aed-... – zbiór w formacie API portalu (aed_dataset.py), z danymi
                             pobieranymi z serwisu AED (serwis_client.py),
  * /api/search            – wyniki z dane.gov.pl z dopisanym zbiorem AED, gdy fraza dotyczy AED,
  * POST .../comments      – „Zgłoś uwagi” do zbioru AED trafia do kolejki dostawcy (uwagi.py),
  * /api/auth/...          – logowanie kontami demo (konta.py): oryginalny formularz „Zaloguj się” portalu,
                             z którego serwis AED bierze rolę (GET /api/auth/user),
  * /api, /cms, /media ... – odczyt z publicznych usług dane.gov.pl (portal_proxy.py); zapisy są blokowane,
  * pozostałe ścieżki      – zbudowany frontend portalu (portal/frontend/dist).
Tylko biblioteka standardowa Pythona.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import urllib.parse
from http import HTTPStatus
from pathlib import Path

from common.http import BaseHandler
from portal.backend import portal_proxy
from portal.backend.aed_dataset import AedDataset
from portal.backend.konta import Konta
from portal.backend.serwis_client import SerwisClient
from portal.backend.uwagi import Comments

log = logging.getLogger("aed.portal")


class PortalHandler(BaseHandler):
    dataset: AedDataset = None
    comments: Comments = None
    konta: Konta = None
    serwis_url: str = ""
    dist: Path = None
    server_version = "aed-portal/0.3"

    def _dataset_api(self, path: str, query: str) -> bool:
        """Zbiór AED udający zbiór portalu. Zwraca True, gdy zapytanie zostało obsłużone."""
        res = self.dataset.handle(path, dict(urllib.parse.parse_qsl(query)), self._origin())
        if res is None:
            return False
        status, ctype, body, *name = res
        extra = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
            ctype += "; charset=utf-8"
        elif not ctype.startswith(("application/ld+json", "application/rdf+xml")):  # pliki: CSV, GeoJSON
            extra["Content-Disposition"] = f'attachment; filename="{name[0] if name else path.rsplit("/", 1)[-1]}"'
        self._send(body, ctype, status, extra)
        return True

    def _search_with_aed(self, url) -> bool:
        """Wyszukiwarka portalu (/api/search): wyniki z dane.gov.pl + zbiór AED, gdy fraza dotyczy AED."""
        query = dict(urllib.parse.parse_qsl(url.query))
        if not self.dataset.search_matches(query):
            return False
        target = portal_proxy.match(url.path) + ("?" + url.query if url.query else "")
        status, headers, data = portal_proxy.forward("GET", target, self.headers, None)
        body = self.dataset.patch_search(status, data, query, self._origin())
        self._send(body, "application/vnd.api+json; charset=utf-8", HTTPStatus.OK, {"Cache-Control": "no-store"})
        return True

    def _route(self, method: str):
        url = urllib.parse.urlparse(self.path)
        for prefix in ("/api/1.4", "/api"):
            if method == "GET" and url.path.startswith(prefix + "/") and \
                    self._dataset_api(url.path[len(prefix):], url.query):
                return
        if method == "GET" and url.path in ("/api/search", "/api/search/") and self._search_with_aed(url):
            return
        if method == "POST" and self._aed_comment(url.path):
            return
        if self._auth(method, url.path):
            return
        target = portal_proxy.match(url.path)
        if target and method != "GET":
            return self._blocked_write(url.path)
        if target:
            if url.query:
                target += "?" + url.query
            status, headers, data = portal_proxy.forward(method, target, self.headers, None)
            return self._send(data, headers.pop("Content-Type", "application/octet-stream"), status, headers)
        if method == "GET":
            return self._static(url.path)
        self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)

    AUTH = re.compile(r"/api(?:/1\.4)?/auth/(.+?)/?")
    TOKEN_COOKIES = ("local_apiauthtoken", "apiauthtoken")

    def _token(self) -> str:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name in self.TOKEN_COOKIES and value:
                return value
        return ""

    def _api_json(self, body: dict, status=HTTPStatus.OK):
        self._send(json.dumps(body, ensure_ascii=False).encode(), "application/vnd.api+json; charset=utf-8", status,
                   {"Cache-Control": "no-store"})

    def _auth(self, method: str, path: str) -> bool:
        """Logowanie w makiecie: konta demo (konta.py) zamiast produkcyjnych kont dane.gov.pl."""
        m = self.AUTH.fullmatch(path)
        if not m:
            return False
        what = m.group(1)
        if method == "POST" and what == "login":
            try:
                attrs = ((json.loads(self._body(16 * 1024) or b"{}").get("data") or {}).get("attributes") or {})
            except ValueError:
                attrs = {}
            token = self.konta.zaloguj(attrs.get("email", ""), attrs.get("password", ""))
            if not token:
                self._api_json({"errors": [{"status": "401", "code": "401_unauthorized", "title": "Błąd logowania",
                                            "detail": "Nieprawidłowy e-mail lub hasło. Konta demo są w README."}]},
                               HTTPStatus.UNAUTHORIZED)
                return True
            email, konto = self.konta.konto(token)
            log.info("Zalogowano w makiecie portalu: %s", email)
            self._api_json(self.konta.uzytkownik(email, konto, token))
            return True
        if method == "POST" and what == "logout":
            self.konta.wyloguj(self._token())
            self._api_json({"jsonapi": {"version": "1.4"}, "data": None})
            return True
        if method == "GET":
            hit = self.konta.konto(self._token())
            if not hit:
                self._api_json({"errors": [{"status": "401", "code": "401_unauthorized",
                                            "title": "Wymagane logowanie"}]}, HTTPStatus.UNAUTHORIZED)
            elif what == "user":
                self._api_json(self.konta.uzytkownik(*hit))
            else:  # panel użytkownika i pozostałe zasoby konta: puste w makiecie
                self._api_json({"jsonapi": {"version": "1.4"}, "data": [], "meta": {"count": 0, "aggregations": {}}})
            return True
        return False  # rejestracja, zmiana hasła itp.: zablokowane jak dotąd (_blocked_write)

    AED_COMMENTS = re.compile(r"/api(?:/1\.4)?/(datasets|resources)/([^/]+)/comments/?")

    def _aed_comment(self, path: str) -> bool:
        """„Zgłoś uwagi” do zbioru AED: uwaga trafia do kolejki dostawcy."""
        m = self.AED_COMMENTS.fullmatch(path)
        if not m:
            return False
        kind, ident = m.group(1), urllib.parse.unquote(m.group(2)).split(",")[0]
        if kind == "datasets" and ident not in ("aed", "system-ewidencji-zasobow-aed"):
            return False
        if kind == "resources" and not ident.startswith("aed-"):
            return False
        try:
            payload = json.loads(self._body(64 * 1024) or b"{}")
            rec = self.comments.add(("zbior:aed" if kind == "datasets" else f"zasob:{ident}"), payload)
        except ValueError as exc:
            self._send(json.dumps({"errors": [{"status": "422", "detail": str(exc)}]}, ensure_ascii=False).encode(),
                       "application/vnd.api+json; charset=utf-8", HTTPStatus.UNPROCESSABLE_ENTITY)
            return True
        log.info("Zgłoszenie do dostawcy zbioru AED: %s (%s)", rec["id"], rec["dotyczy"])
        body = {"jsonapi": {"version": "1.4"},
                "data": {"id": rec["id"], "type": "comment", "attributes": {"comment": rec["tresc"]}},
                "meta": {"status": rec["status"]}}
        self._send(json.dumps(body, ensure_ascii=False).encode(), "application/vnd.api+json; charset=utf-8",
                   HTTPStatus.CREATED)
        return True

    def _blocked_write(self, path: str):
        """Prototyp nie wysyła niczego do produkcyjnego dane.gov.pl: zapisy (uwagi, propozycje danych, formularze,
        logowanie) dostają lokalną odpowiedź demo i nie wychodzą poza ten komputer."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, 2 * 1024 * 1024)) if length else b""
        log.info("Zablokowano zapis do dane.gov.pl: %s %s", self.command, path)
        if "/auth/" in path:
            err = {"errors": [{"status": "403", "title": "Prototyp",
                               "detail": "Logowanie i konta są wyłączone w prototypie."}]}
            return self._send(json.dumps(err, ensure_ascii=False).encode(), "application/vnd.api+json; charset=utf-8",
                              HTTPStatus.FORBIDDEN)
        try:
            data = (json.loads(raw) or {}).get("data") or {}
        except (ValueError, AttributeError):
            data = {}
        body = {"jsonapi": {"version": "1.4"},
                "data": {"id": "demo", "type": data.get("type") or "demo", "attributes": {}},
                "meta": {"demo": True,
                         "info": "Prototyp: zapis nie został wysłany do dane.gov.pl."}}
        self._send(json.dumps(body, ensure_ascii=False).encode(), "application/vnd.api+json; charset=utf-8",
                   HTTPStatus.CREATED)

    def _static(self, path: str):
        dist = self.dist
        if not (dist / "index.html").exists():
            msg = ("<h1>Brak zbudowanego frontendu portalu</h1><p>Uruchom <code>python portal/frontend/build.py</code> "
                   "albo skopiuj katalog <code>portal/frontend/dist</code>.</p>").encode()
            return self._send(msg, "text/html; charset=utf-8", HTTPStatus.SERVICE_UNAVAILABLE)
        rel = urllib.parse.unquote(path).lstrip("/")
        target = (dist / rel).resolve() if rel else dist / "index.html"
        if dist.resolve() not in target.parents and target != dist / "index.html" or not target.is_file():
            target = dist / "index.html"  # routing aplikacji Angular (np. /pl/dataset)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        cache = "no-cache" if target.name == "index.html" else "public, max-age=31536000, immutable"
        data = target.read_bytes()
        if target.name == "index.html" and self.serwis_url:
            data = data.replace(b"</head>", self._powrot_js() + b"</head>", 1)
        self._send(data, ctype, extra={"Cache-Control": cache})

    POWROT = "/pl/aed-powrot"  # ?redirect= formularza logowania portalu: po zalogowaniu wracamy do serwisu AED

    def _powrot_js(self) -> bytes:
        cel = json.dumps(self.serwis_url.rstrip("/") + "/?zalogowano=1")
        return (f"<script>(function(){{var p={json.dumps(self.POWROT)},c={cel};"
                "function s(){if(location.pathname.indexOf(p)===0)location.replace(c);}"
                "['pushState','replaceState'].forEach(function(k){var o=history[k];"
                "history[k]=function(){var r=o.apply(this,arguments);s();return r;};});"
                "addEventListener('popstate',s);s();})();</script>").encode()


def setup(base: Path, cfg: dict, serwis_api: str, serwis_url: str):
    """Przygotowuje makietę portalu i zwraca klasę obsługi żądań."""
    PortalHandler.dataset = AedDataset(cfg, SerwisClient(serwis_api), serwis_url)
    PortalHandler.comments = Comments(base)
    PortalHandler.konta = Konta()
    PortalHandler.serwis_url = serwis_url
    PortalHandler.dist = (Path(__file__).resolve().parents[1] / "frontend" / "dist")
    return PortalHandler
