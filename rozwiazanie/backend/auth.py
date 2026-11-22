"""Weryfikacja konta i tokenu przez lokalne API mcod."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from http.cookies import SimpleCookie

from .columns import ROLE_ADMIN, ROLE_PUBLIC

log = logging.getLogger("aed.auth")
TOKEN_COOKIES = ("local_apiauthtoken", "apiauthtoken")  # ciasteczka frontendu portalu (prefiks zależny od domeny)
ROLE_SLUZBY = "sluzby_aed"


class Auth:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.api_url = (cfg.get("api_url") or "").rstrip("/")  # server.py ustawia API makiety portalu
        self.login_url = cfg.get("logowanie_url") or ""

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
        return next((cookie[c].value for c in TOKEN_COOKIES if c in cookie and cookie[c].value), "")

    def account(self, headers) -> dict:
        """{"rola": "admin" | "publiczny", "uzytkownik": nazwa konta albo ""}."""
        token = self.token_from(headers)
        if not token or not self.api_url:
            return {"rola": ROLE_PUBLIC, "uzytkownik": ""}
        return self._portal_account(token)

    def role(self, headers) -> str:
        return self.account(headers)["rola"]

    def logout(self, headers):
        """Koniec sesji w portalu (POST /auth/logout z tokenem) i w pamięci serwisu."""
        token = self.token_from(headers)
        if token and self.api_url:
            req = urllib.request.Request(f"{self.api_url}/auth/logout", data=b"{}", method="POST",
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=5).close()
            except (urllib.error.URLError, OSError) as exc:
                log.info("Portal nie potwierdził wylogowania (%s)", exc)

    @staticmethod
    def logout_cookies(host: str) -> list[str]:
        """Usunięcie ciasteczek tokenu portalu (frontend portalu ustawia je z Domain=<host>)."""
        host = (host or "").split(":")[0]
        out = []
        for name in TOKEN_COOKIES + ("local_sessionid", "sessionid"):
            out.append(f"{name}=; Path=/; Max-Age=0")
            if host:
                out.append(f"{name}=; Path=/; Domain={host}; Max-Age=0")
        return out

    # ------------------------------------------------------------ konto z portalu
    def _portal_account(self, token: str) -> dict:
        acc = {"rola": ROLE_PUBLIC, "uzytkownik": ""}
        req = urllib.request.Request(f"{self.api_url}/auth/user",
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                acc = self.account_from(json.loads(resp.read().decode("utf-8")))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            log.info("Portal nie potwierdził tokenu (%s), rola publiczna", exc)
        return acc

    @staticmethod
    def account_from(payload: dict) -> dict:
        """Odpowiedź JSON:API z GET /auth/user: data.attributes.aed_rola / system_role / fullname."""
        attrs = ((payload or {}).get("data") or {}).get("attributes") or {}
        role = ROLE_SLUZBY if attrs.get("aed_rola") == ROLE_SLUZBY else ROLE_PUBLIC
        return {"rola": ROLE_ADMIN if attrs.get("system_role") == "admin" else role,
                "uzytkownik": str(attrs.get("fullname") or attrs.get("email") or "")}

    @staticmethod
    def role_from_account(payload: dict) -> str:
        return Auth.account_from(payload)["rola"]
