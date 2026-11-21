"""Scraping serwisu AED: ręczne pobranie danych bez uruchamiania serwera.

    python -m rozwiazanie.scraping.run            -> pobiera z dane.gov.pl i zapisuje data/cache/danegov.json
    python -m rozwiazanie.scraping.run --raport   -> dodatkowo wypisuje raport zasobów
    python -m rozwiazanie.scraping.run --xlsx     -> zapisuje zagregowaną tabelę (wzorcowy zakres) do data/rejestr_aed.xlsx
    python -m rozwiazanie.scraping.run --offline --xlsx  -> to samo z pamięci podręcznej, bez internetu

Używa wyłącznie publicznego API dane.gov.pl i plików na otwartych licencjach.
Nie pobieramy danych z serwisów, których regulamin na to nie pozwala.
"""
import argparse
import json
import logging
from pathlib import Path

from rozwiazanie.backend.store import Store

BASE = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raport", action="store_true")
    ap.add_argument("--offline", action="store_true", help="bez pobierania, dane z data/cache")
    ap.add_argument("--xlsx", nargs="?", const="data/rejestr_aed.xlsx", metavar="SCIEZKA",
                    help="zapisz zagregowaną tabelę (kolumny publiczne) jako jeden arkusz XLSX")
    ap.add_argument("--csv", nargs="?", const="data/rejestr_aed.csv", metavar="SCIEZKA",
                    help="zapisz zagregowaną tabelę (kolumny publiczne) jako CSV")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    store = Store(BASE, cfg)
    if args.offline:
        store._load_cache("danegov")
    else:
        store.refresh_danegov()
    if "danegov" not in store.by_source:
        store._load_cache("danegov")
    st = store.status.get("danegov", {})
    print(f"dane.gov.pl: {st.get('stan')} – {st.get('rekordy', 0)} rekordów")
    if args.raport:
        print(json.dumps(st.get("raport", []), ensure_ascii=False, indent=1))
    for path, build in ((args.xlsx, store.export_xlsx), (args.csv, store.export_csv)):
        if path:
            out = Path(path) if Path(path).is_absolute() else BASE / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(build())
            print(f"Zapisano: {out}")
