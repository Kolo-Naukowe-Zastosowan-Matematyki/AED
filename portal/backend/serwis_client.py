"""Klient serwisu AED po stronie portalu.

Portal (instancja A) nie ma własnej bazy AED: dane zasobów zbioru „System Ewidencji Zasobów AED” pobiera z API
serwisu AED (instancja B), tak jak prawdziwy portal pobiera zasób z adresu podanego przez dostawcę.
Odpowiedzi są trzymane w pamięci przez `ttl` sekund.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request

log = logging.getLogger("aed.portal.serwis")


class SerwisClient:
    def __init__(self, api_url: str, ttl: int = 60):
        self.api = api_url.rstrip("/")
        self.ttl = ttl
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()

    def _get(self, path: str, timeout: int = 20) -> bytes | None:
        with self._lock:
            hit = self._cache.get(path)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        try:
            with urllib.request.urlopen(self.api + path, timeout=timeout) as resp:
                body = resp.read()
        except Exception as exc:  # noqa: BLE001 – serwis wyłączony albo niedostępny
            log.warning("Serwis AED niedostępny (%s): %s", path, exc)
            return hit[1] if hit else None
        with self._lock:
            self._cache[path] = (time.time(), body)
        return body

    def register(self) -> dict:
        body = self._get("/rejestr.json")
        return json.loads(body) if body else {"pobrano": None, "rekordy": []}

    def map_html(self) -> bytes:
        return self._get("/mapa_aed.html", timeout=60) or b""
