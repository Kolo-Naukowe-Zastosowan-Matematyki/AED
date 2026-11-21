"""Logowanie w makiecie portalu dane.gov.pl: konta demo zamiast produkcyjnych kont mcod.

Oryginalny frontend portalu loguje się tak jak na dane.gov.pl:
  POST /api/auth/login   {"data": {"type": "user", "attributes": {"email", "password"}}}
                         -> data.attributes.token (JWT; frontend zapisuje go w ciasteczku <prefiks>apiauthtoken,
                            na localhost: local_apiauthtoken, i wysyła jako Authorization: Bearer)
  GET  /api/auth/user    -> konto zalogowanego użytkownika (JSON:API), w tym rola
  POST /api/auth/logout  -> koniec sesji

Rola dla serwisu AED: pole "aed_rola" („sluzby_aed” = dostęp do kolumn chronionych rejestru) obok "system_role"
z mcod (admin też ma dostęp). Na produkcji to pole dopisuje wsad mcod (mcod_wsad/README.md, p. 3).
Nic z tego nie trafia do produkcyjnego dane.gov.pl.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

SESJA_S = 8 * 3600
# konta demo (opisane w README); hasła tylko do pokazu na localhost
KONTA = {
    "sluzby@aed.demo": {"haslo": "demo-aed", "fullname": "Dyspozytor PRM (demo)", "system_role": "user",
                        "aed_rola": "sluzby_aed"},
    "admin@aed.demo": {"haslo": "demo-aed", "fullname": "Administrator dane.gov.pl (demo)", "system_role": "admin",
                       "aed_rola": ""},
    "obywatel@aed.demo": {"haslo": "demo-aed", "fullname": "Jan Kowalski (demo)", "system_role": "user",
                          "aed_rola": ""},
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Konta:
    def __init__(self):
        self.klucz = secrets.token_bytes(32)
        self.lock = threading.Lock()
        self.sesje: dict[str, tuple[str, float]] = {}  # token -> (email, wygasa)

    def zaloguj(self, email: str, haslo: str) -> str | None:
        email = (email or "").strip().lower()
        konto = KONTA.get(email)
        if not konto or not hmac.compare_digest(str(haslo).encode(), konto["haslo"].encode()):
            return None
        exp = int(time.time()) + SESJA_S
        roles = ["admin"] if konto["system_role"] == "admin" else ["user"]
        payload = {"user": {"session_key": secrets.token_hex(16), "email": email, "roles": roles}, "exp": exp}
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = _b64(json.dumps(payload).encode())
        sig = _b64(hmac.new(self.klucz, f"{head}.{body}".encode(), hashlib.sha256).digest())
        token = f"{head}.{body}.{sig}"
        with self.lock:
            now = time.time()
            self.sesje = {t: s for t, s in self.sesje.items() if s[1] > now}
            self.sesje[token] = (email, exp)
        return token

    def konto(self, token: str) -> tuple[str, dict] | None:
        with self.lock:
            s = self.sesje.get(token or "")
        if not s or s[1] < time.time():
            return None
        return s[0], KONTA[s[0]]

    def wyloguj(self, token: str):
        with self.lock:
            self.sesje.pop(token or "", None)

    @staticmethod
    def uzytkownik(email: str, konto: dict, token: str = "") -> dict:
        """Odpowiedź JSON:API jak GET /auth/user w mcod (pola, z których korzysta frontend i serwis AED)."""
        attrs = {"email": email, "fullname": konto["fullname"], "state": "active", "is_newsletter_receiver": False,
                 "system_role": konto["system_role"], "aed_rola": konto["aed_rola"],
                 "subscriptions_report_opt_in": False, "rodo_privacy_policy_opt_in": True}
        if token:
            attrs["token"] = token
        uid = int(hashlib.sha1(email.encode()).hexdigest()[:6], 16)
        return {"jsonapi": {"version": "1.4"},
                "data": {"id": str(uid), "type": "user", "attributes": attrs, "relationships": {}}}
