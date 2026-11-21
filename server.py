"""Uruchomienie prototypu: portal dane.gov.pl z wbudowanym modułem AED.

    python server.py                 -> http://localhost:8000 (strona główna portalu)
                                        http://localhost:8000/pl/aed (moduł AED)
    python server.py --port 8080
    python server.py --offline       -> bez pobierania z API dane.gov.pl (dane z pamięci podręcznej)
    python server.py --open          -> dodatkowo otwiera przeglądarkę
    Windows: dwuklik w start.bat (uruchomienie / restart), stop.bat (zatrzymanie)

Strefy kodu:  backend/  scraping/  frontend/  vision/   (opis w README.md)
"""
import argparse
import json
import logging
from pathlib import Path

from backend.app import run

BASE = Path(__file__).resolve().parent

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Portal dane.gov.pl z modułem AED (prototyp)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--open", action="store_true", help="otwórz przeglądarkę po starcie")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg_path = BASE / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    run(BASE, cfg, args.host, args.port, args.offline, args.open)
