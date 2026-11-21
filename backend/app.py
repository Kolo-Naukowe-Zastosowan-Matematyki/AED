"""Strefa 1: serwer HTTP modułu AED.

Jeden proces obsługuje trzy rzeczy:
  * /aed-api/...           – API modułu AED (dane, najbliższe AED, eksport, zgłoszenia, weryfikacja zdjęć),
  * /api, /cms, /media ... – przekazywanie do publicznych usług dane.gov.pl (portal_proxy),
  * pozostałe ścieżki      – zbudowany frontend portalu z wbudowanym modułem AED (frontend/dist).
Tylko biblioteka standardowa Pythona (Pillow opcjonalnie, dla strefy 4).
"""
from __future__ import annotations

import gzip
import json
import logging
import mimetypes
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend import portal_proxy
from backend.store import Store
from backend.submissions import MAX_PHOTO, Submissions
from vision import verify as vision

log = logging.getLogger("aed")


class Handler(BaseHTTPRequestHandler):
    store: Store = None
    subs: Submissions = None
    dist: Path = None
    server_version = "aed-prototyp/0.2"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ odpowiedzi
    def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK, extra: dict | None = None, compress=True):
        gz = compress and "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1024 \
            and not ctype.startswith(("image/", "font/"))
        if gz:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", status,
                   {"Cache-Control": "no-store"})

    def _body(self, limit: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("Za duże żądanie")
        return self.rfile.read(n) if n else b""

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ------------------------------------------------------------ routing
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method: str):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/aed-api/"):
            try:
                return self._aed_api(method, url.path[len("/aed-api"):], dict(urllib.parse.parse_qsl(url.query)))
            except (KeyError, ValueError) as exc:
                return self._json({"blad": str(exc) or "nieprawidłowe parametry"}, HTTPStatus.BAD_REQUEST)
        target = portal_proxy.match(url.path)
        if target:
            if url.query:
                target += "?" + url.query
            body = self._body(2 * 1024 * 1024) if method == "POST" else None
            status, headers, data = portal_proxy.forward(method, target, self.headers, body)
            return self._send(data, headers.pop("Content-Type", "application/octet-stream"), status, headers)
        if method == "GET":
            return self._static(url.path)
        self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)

    def _aed_api(self, method: str, p: str, q: dict):
        s = self.store
        if method == "GET":
            if p == "/points":
                return self._send(s.points_json(), "application/json", extra={"Cache-Control": "no-store"})
            if p.startswith("/aed/"):
                d = s.detail(int(p.rsplit("/", 1)[1]))
                return self._json(d) if d else self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)
            if p == "/nearest":
                res = s.nearest(float(q["lat"]), float(q["lon"]), min(int(q.get("n", 3)), 20),
                                q.get("tylko_dostepne", "1") != "0")
                return self._json({"wyniki": res})
            if p == "/sources":
                return self._json(s.sources_info())
            if p == "/stats":
                return self._json(s.stats())
            if p == "/zgloszenia":
                return self._json({"zgloszenia": self.subs.list()})
            if p == "/export.csv":
                return self._send(s.export_csv(), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="aed_dane_gov_pl.csv"'})
            if p == "/export.geojson":
                return self._send(s.export_geojson(), "application/geo+json",
                                  extra={"Content-Disposition": 'attachment; filename="aed_dane_gov_pl.geojson"'})
        if method == "POST":
            if p == "/refresh":
                threading.Thread(target=s.refresh_danegov, daemon=True).start()
                return self._json({"ok": True}, HTTPStatus.ACCEPTED)
            if p == "/zdjecie":
                data = self._body(MAX_PHOTO)
                declared = (float(q["lat"]), float(q["lon"])) if "lat" in q and "lon" in q else None
                known = [x.get("weryfikacja_zdjecia", {}).get("dhash") for x in self.subs.list()]
                verdict = vision.verify(data, declared, [k for k in known if k])
                if verdict.get("ocena") != "odrzuc" and vision.HAVE_PIL:
                    verdict["zdjecie_id"] = self.subs.save_photo(data, verdict)
                return self._json(verdict)
            if p == "/zgloszenia":
                payload = json.loads(self._body(64 * 1024) or b"{}")
                return self._json(self.subs.add(payload), HTTPStatus.CREATED)
        self._json({"blad": "nie znaleziono"}, HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------ frontend portalu
    def _static(self, path: str):
        dist = self.dist
        if not (dist / "index.html").exists():
            msg = ("<h1>Brak zbudowanego frontendu</h1><p>Uruchom <code>python frontend/build.py</code> "
                   "albo skopiuj katalog <code>frontend/dist</code>. API modułu działa pod <a href='/aed-api/stats'>"
                   "/aed-api/stats</a>.</p>").encode()
            return self._send(msg, "text/html; charset=utf-8", HTTPStatus.SERVICE_UNAVAILABLE)
        rel = urllib.parse.unquote(path).lstrip("/")
        target = (dist / rel).resolve() if rel else dist / "index.html"
        if dist.resolve() not in target.parents and target != dist / "index.html" or not target.is_file():
            target = dist / "index.html"  # routing aplikacji Angular (np. /pl/aed)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        cache = "no-cache" if target.name == "index.html" else "public, max-age=31536000, immutable"
        self._send(target.read_bytes(), ctype, extra={"Cache-Control": cache})


class Server(ThreadingHTTPServer):
    """Na Windows SO_REUSEADDR pozwala dwóm serwerom słuchać na tym samym porcie, a wtedy przeglądarka trafia
    do starej instancji. Dlatego na Windows port jest zajmowany na wyłączność."""
    daemon_threads = True
    allow_reuse_address = not sys.platform.startswith("win")

    def server_bind(self):
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def run(base: Path, cfg: dict, host: str, port: int, offline: bool, open_browser: bool = False):
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    if offline:
        cfg.setdefault("danegov", {})["enabled"] = False
    store = Store(base, cfg)
    store.start()
    if offline:
        store._load_cache("danegov")
    Handler.store = store
    Handler.subs = Submissions(base)
    Handler.dist = (base / "frontend" / "dist").resolve()

    # Na Windows część portów (np. 8000) bywa zarezerwowana (WinError 10013) albo zajęta (10048).
    srv = None
    for p in [port] + list(range(8765, 8785)):
        try:
            srv = Server((host, p), Handler)
            break
        except OSError as exc:
            log.warning("Port %d niedostępny (%s), próbuję kolejnego…", p, exc.strerror or exc)
    if srv is None:
        raise SystemExit("Nie znaleziono wolnego portu. Uruchom z opcją --port, np. python server.py --port 5050")
    a = srv.server_address
    log.info("Portal z modułem AED: http://localhost:%d  (moduł: http://localhost:%d/pl/aed)", a[1], a[1])
    pid_file = base / "data" / "server.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()} {a[1]}", encoding="utf-8")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, [f"http://localhost:{a[1]}/pl"]).start()
    if not vision.HAVE_PIL:
        log.warning("Strefa 4 (zdjęcia) wyłączona: brak Pillow. pip install -r vision/requirements.txt")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pid_file.unlink(missing_ok=True)
