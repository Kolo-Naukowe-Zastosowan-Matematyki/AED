"""Przekazywanie zapytań frontendu portalu do publicznych usług dane.gov.pl.

Frontend portalu w trybie nieprodukcyjnym wysyła zapytania na ten sam adres (/api, /cms, /media, /flags),
tak jak w plikach proxy.*.conf.json z repozytorium frontendu. Ten moduł odtwarza tę konfigurację,
dzięki czemu `python server.py` pokazuje stronę główną portalu z prawdziwymi danymi.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request

log = logging.getLogger("aed.proxy")

# prefiks lokalny -> adres docelowy (odpowiednik proxy.dev.conf.json, ale dla produkcji)
ROUTES = {
    "/api/": "https://api.dane.gov.pl/1.4/",
    "/cms/": "https://cms.dane.gov.pl/",
    "/media/": "https://dane.gov.pl/media/",
    "/flags/": "https://dane.gov.pl/flags/",
}
FORWARD_REQ = ("Accept", "Accept-Language", "Content-Type", "Authorization", "X-Api-Version")
FORWARD_RESP = ("Content-Type", "Cache-Control", "Last-Modified", "ETag", "Content-Disposition")


def match(path: str) -> str | None:
    for prefix, target in ROUTES.items():
        if path.startswith(prefix):
            return target + path[len(prefix):]
    return None


def forward(method: str, target: str, headers, body: bytes | None, timeout: int = 30):
    """Zwraca (status, nagłówki, treść). Ciasteczka i dane logowania użytkownika nie są przekazywane."""
    req_headers = {h: headers[h] for h in FORWARD_REQ if headers.get(h)}
    req_headers["User-Agent"] = "aed-prototyp/0.2 (proxy portalu)"
    req = urllib.request.Request(target, data=body if method in ("POST", "PUT", "PATCH") else None,
                                 headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = {h: resp.headers[h] for h in FORWARD_RESP if resp.headers.get(h)}
            return resp.status, out, resp.read()
    except urllib.error.HTTPError as exc:
        out = {h: exc.headers[h] for h in FORWARD_RESP if exc.headers and exc.headers.get(h)}
        return exc.code, out, exc.read()
    except Exception as exc:  # noqa: BLE001 – brak sieci, DNS, timeout
        log.warning("Proxy %s %s: %s", method, target, exc)
        msg = ('{"errors":[{"title":"Brak połączenia z dane.gov.pl","detail":"%s"}]}' % str(exc).replace('"', "'"))
        return 502, {"Content-Type": "application/json; charset=utf-8"}, msg.encode()
