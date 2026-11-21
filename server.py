"""Uruchomienie prototypu: dwie niezależne instancje w jednym procesie.

  A. portal/   makieta dane.gov.pl: oryginalny frontend i API portalu, a w nich nasz zbiór
               „System Ewidencji Zasobów AED”                     -> http://localhost:8000
  B. rozwiazanie/   serwis AED: rejestr (strona główna), mapa, API i scraping
                                                                   -> http://localhost:8001

    python server.py                 uruchamia obie instancje
    python server.py --open          dodatkowo otwiera przeglądarkę (portal)
    python server.py --offline       bez pobierania z API dane.gov.pl (dane z pamięci podręcznej)
    python server.py --port 8080 --serwis-port 8081
    Windows: dwuklik w start.bat (uruchomienie / restart), stop.bat (zatrzymanie)
"""
import argparse
import json
import logging
import os
import threading
import webbrowser
from pathlib import Path

from common.http import bind
from portal.backend.app import setup as setup_portal
from rozwiazanie.backend.app import setup as setup_serwis

BASE = Path(__file__).resolve().parent
log = logging.getLogger("aed")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Prototyp: portal dane.gov.pl ze zbiorem AED + serwis AED")
    ap.add_argument("--port", type=int, default=8000, help="port portalu dane.gov.pl")
    ap.add_argument("--serwis-port", type=int, default=8001, help="port serwisu AED")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--open", action="store_true", help="otwórz przeglądarkę po starcie")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg_path = BASE / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

    # B. serwis AED
    serwis = bind(setup_serwis(BASE, cfg, args.offline), args.host,
                  [args.serwis_port] + list(range(8785, 8800)), "Serwis AED")
    serwis_url = f"http://localhost:{serwis.server_address[1]}"
    threading.Thread(target=serwis.serve_forever, daemon=True).start()

    # A. makieta portalu dane.gov.pl (dane zbioru AED pobiera z API serwisu)
    portal = bind(setup_portal(BASE, cfg, serwis_url + "/aed-api", (cfg.get("serwis") or {}).get("url") or serwis_url),
                  args.host, [args.port] + list(range(8765, 8785)), "Portal dane.gov.pl")
    portal_url = f"http://localhost:{portal.server_address[1]}"

    log.info("Portal dane.gov.pl:  %s  (zbiór AED: %s/pl/dataset/aed,system-ewidencji-zasobow-aed)",
             portal_url, portal_url)
    log.info("Serwis AED:          %s  (rejestr, %s/mapa)", serwis_url, serwis_url)
    pid_file = BASE / "data" / "server.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()} {portal.server_address[1]}", encoding="utf-8")
    if args.open:
        threading.Timer(1.0, webbrowser.open, [portal_url + "/pl"]).start()
    try:
        portal.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pid_file.unlink(missing_ok=True)
