"""Wspólne elementy serwerów HTTP obu instancji (portal i serwis AED). Tylko biblioteka standardowa."""
from __future__ import annotations

import gzip
import json
import logging
import mimetypes
import socket
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("aed.http")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")


class BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method: str):  # pragma: no cover - nadpisywane
        raise NotImplementedError

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
            for one in (v if isinstance(v, list) else [v]):  # lista: nagłówek powtórzony (np. kilka Set-Cookie)
                self.send_header(k, one)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status=HTTPStatus.OK, extra: dict | None = None):
        self._send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", status,
                   {"Cache-Control": "no-store", **(extra or {})})

    def _body(self, limit: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("Za duże żądanie")
        return self.rfile.read(n) if n else b""

    def _origin(self) -> str:
        return "http://" + (self.headers.get("Host") or "localhost")


class Server(ThreadingHTTPServer):
    """Na Windows SO_REUSEADDR pozwala dwóm serwerom słuchać na tym samym porcie, a wtedy przeglądarka trafia
    do starej instancji. Dlatego na Windows port jest zajmowany na wyłączność."""
    daemon_threads = True
    allow_reuse_address = not sys.platform.startswith("win")

    def server_bind(self):
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def bind(handler, host: str, ports: list[int], name: str) -> Server:
    """Na Windows część portów (np. 8000) bywa zarezerwowana (WinError 10013) albo zajęta (10048)."""
    for p in ports:
        try:
            return Server((host, p), handler)
        except OSError as exc:
            log.warning("%s: port %d niedostępny (%s), próbuję kolejnego…", name, p, exc.strerror or exc)
    raise SystemExit(f"{name}: nie znaleziono wolnego portu. Wskaż inny w opcjach server.py.")
