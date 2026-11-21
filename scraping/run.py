"""Strefa 2: ręczne pobranie danych bez uruchamiania serwera.

    python -m scraping.run            -> pobiera z dane.gov.pl i zapisuje data/cache/danegov.json
    python -m scraping.run --raport   -> dodatkowo wypisuje raport zasobów

Używa wyłącznie publicznego API dane.gov.pl i plików na otwartych licencjach.
Nie pobieramy danych z serwisów, których regulamin na to nie pozwala.
"""
import argparse
import json
import logging
from pathlib import Path

from backend.store import Store

BASE = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raport", action="store_true")
    ap.add_argument("--xlsx", nargs="?", const="data/aed_dane_gov_pl.xlsx",
                    metavar="SCIEZKA", help="zapisz zbior jako jeden arkusz XLSX")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    store = Store(BASE, cfg)
    store.refresh_danegov()
    if "danegov" not in store.by_source:
        store._load_cache("danegov")
    st = store.status.get("danegov", {})
    print(f"dane.gov.pl: {st.get('stan')} – {st.get('rekordy', 0)} rekordów")
    if args.raport:
        print(json.dumps(st.get("raport", []), ensure_ascii=False, indent=1))
    if args.xlsx:
        output = (BASE / args.xlsx).resolve() if not Path(args.xlsx).is_absolute() else Path(args.xlsx)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(store.export_xlsx())
        print(f"XLSX: {output}")
