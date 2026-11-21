"""Ustalanie roli użytkownika serwisu rejestru AED.

Dwa tryby (config.json -> "auth" -> "tryb"):

  "demo"    (domyślny) atrapa logowania administratora w samym serwisie: POST /aed-api/auth/login z hasłem
            (zmienna środowiskowa AED_ADMIN_HASLO albo config "haslo_demo"). Serwis wydaje losowy token
            w ciasteczku HttpOnly. Do pokazu bez uruchomionego backendu dane.gov.pl.
  "portal"  rola z konta portalu dane.gov.pl (mcod): frontend przekazuje token JWT portalu w nagłówku
            Authorization: Bearer <token>, a serwis sprawdza go zapytaniem GET {api_url}/auth/user.
            mcod zwraca rolę w polu "system_role" (admin / editor / representative / official / user) po
            dodaniu jednego pola w users/serializers.py (patrz mcod_wsad/README.md).

Brak tokenu, zły token albo błąd połączenia = rola publiczna. Filtrowanie kolumn robi serwer (columns.py).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie

from .columns import ROLE_ADMIN, ROLE_PUBLIC

log = logging.getLogger("aed.auth")
COOKIE = "aed_token"
SESSION_TTL = 8 * 3600
PORTAL_CACHE_TTL = 300


class Auth:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.mode = cfg.get("tryb", "demo")
        self.api_url = (cfg.get("api_url") or "").rstrip("/")
        self.password = os.environ.get("AED_ADMIN_HASLO") or cfg.get("haslo_demo") or "admin-aed"
        self.lock = threading.Lock()
        self.sessions: dict[str, float] = {}             # token demo -> czas wygaśnięcia
        self.portal_cache: dict[str, tuple[float, str]] = {}  # token portalu -> (czas, rola)

    # ------------------------------------------------------------ token z żądania
    @staticmethod
    def token_from(headers) -> str:
        auth = headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001 - zepsute ciasteczko = brak tokenu
            return ""
        return cookie[COOKIE].value if COOKIE in cookie else ""

    def role(self, headers) -> str:
        token = self.token_from(headers)
        if not token:
            return ROLE_PUBLIC
        with self.lock:
            exp = self.sessions.get(token)
            if exp and exp > time.time():
                return ROLE_ADMIN
        if self.mode == "portal" and self.api_url:
            return self._portal_role(token)
        return ROLE_PUBLIC

    # ------------------------------------------------------------ tryb demo
    def login(self, password: str) -> str | None:
        if not hmac.compare_digest(str(password).encode(), self.password.encode()):
            return None
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            self.sessions = {t: e for t, e in self.sessions.items() if e > now}
            self.sessions[token] = now + SESSION_TTL
        return token

    def logout(self, headers):
        token = self.token_from(headers)
        with self.lock:
            self.sessions.pop(token, None)
            self.portal_cache.pop(token, None)

    @staticmethod
    def cookie_header(token: str, max_age: int = SESSION_TTL) -> str:
        return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"

    # ------------------------------------------------------------ tryb portal (mcod)
    def _portal_role(self, token: str) -> str:
        now = time.time()
        with self.lock:
            hit = self.portal_cache.get(token)
            if hit and now - hit[0] < PORTAL_CACHE_TTL:
                return hit[1]
        role = ROLE_PUBLIC
        req = urllib.request.Request(f"{self.api_url}/auth/user",
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                role = self.role_from_account(json.loads(resp.read().decode("utf-8")))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            log.info("Portal nie potwierdził tokenu (%s), rola publiczna", exc)
        with self.lock:
            self.portal_cache[token] = (now, role)
        return role

    @staticmethod
    def role_from_account(payload: dict) -> str:
        """Odpowiedź JSON:API z GET /auth/user mcod: data.attributes.system_role."""
        attrs = ((payload or {}).get("data") or {}).get("attributes") or {}
        return ROLE_ADMIN if attrs.get("system_role") == "admin" else ROLE_PUBLIC
