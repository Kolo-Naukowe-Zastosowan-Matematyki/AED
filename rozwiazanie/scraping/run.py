"""Scraping serwisu AED: ręczne pobranie danych bez uruchamiania serwera.

    python -m rozwiazanie.scraping.run            -> pobiera z dane.gov.pl i zapisuje data/cache/danegov.json
    python -m rozwiazanie.scraping.run --raport   -> dodatkowo wypisuje raport zasobów
    python -m rozwiazanie.scraping.run --xlsx     -> zapisuje zagregowaną tabelę (złoty standard) do data/rejestr_aed.xlsx
    python -m rozwiazanie.scraping.run --csv      -> to samo jako CSV z separatorem „;” (data/rejestr_aed.csv)
    python -m rozwiazanie.scraping.run --offline --xlsx  -> to samo z pamięci podręcznej, bez internetu
    python -m rozwiazanie.scraping.run --geokoduj -> pobiera jak wyżej i dopytuje GUGiK o brakujące adresy (osobny,
                                                     opcjonalny krok; wyniki w data/cache/geokod.json do commita)
    python -m rozwiazanie.scraping.run --szukaj   -> tylko wypisuje zbiory i zasoby AED z wyszukiwarki dane.gov.pl
    python -m rozwiazanie.scraping.run --diagnoza -> pobiera i zapisuje do data/diagnoza.json nagłówki i pierwsze
                                                     wiersze każdego zasobu, z którego nie udało się wczytać AED

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
    ap.add_argument("--geokoduj", nargs="?", const=300, type=int, metavar="LIMIT",
                    help="uzupełnij braki z geokodera GUGiK (najwyżej LIMIT zapytań, domyślnie 300)")
    ap.add_argument("--szukaj", action="store_true", help="wypisz zbiory znalezione przez wyszukiwarkę i zakończ")
    ap.add_argument("--diagnoza", nargs="?", const="data/diagnoza.json", metavar="SCIEZKA",
                    help="zapisz próbki pominiętych zasobów (nagłówki, 3 wiersze, początek pliku)")
    ap.add_argument("--xlsx", nargs="?", const="data/rejestr_aed.xlsx", metavar="SCIEZKA",
                    help="zapisz zagregowaną tabelę (kolumny publiczne) jako jeden arkusz XLSX")
    ap.add_argument("--csv", nargs="?", const="data/rejestr_aed.csv", metavar="SCIEZKA",
                    help="zapisz zagregowaną tabelę (kolumny publiczne) jako CSV")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    if args.szukaj:
        from rozwiazanie.scraping import danegov
        traf: list = []
        zbiory = danegov.find_datasets(cfg.get("danegov", {}), traf)
        zasoby = danegov.find_resources(cfg.get("danegov", {}), {t[1] for t in traf if t[3]}, traf)
        for q in dict.fromkeys(t[0] for t in traf):
            print(f"„{q}”: {sum(1 for t in traf if t[0] == q)} wyników")
        for did, tytul, ok in sorted({(t[1], t[2], t[3]) for t in traf}, key=lambda t: (not t[2], t[1])):
            if ok:  # pozostałe trafienia (setki) tylko w liczbach powyżej
                print(f"  AED  {did:>9}  {tytul}")
        print(f"Zbiory AED: {len(zbiory)}; osobne zasoby AED (z:id) spoza tych zbiorów: {len(zasoby)}")
        raise SystemExit
    if args.geokoduj:
        cfg.setdefault("danegov", {}).update(geokodowanie=True, geokodowanie_limit=args.geokoduj)
    store = Store(BASE, cfg)
    if args.offline:
        store._load_cache("danegov")
    else:
        store.refresh_danegov()
    if "danegov" not in store.by_source:
        store._load_cache("danegov")
    st = store.status.get("danegov", {})
    print(f"dane.gov.pl: {st.get('stan')} – {st.get('rekordy', 0)} rekordów")
    if st.get("geokodowanie"):
        print(st["geokodowanie"])
    if args.raport:
        print(json.dumps(st.get("raport", []), ensure_ascii=False, indent=1))
    if args.diagnoza:
        bad = [e for e in st.get("raport", []) if not e.get("rekordy")]
        out = Path(args.diagnoza) if Path(args.diagnoza).is_absolute() else BASE / args.diagnoza
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(bad, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"Diagnoza: {len(bad)} zasobów bez rekordów -> {out}")
    for path, build in ((args.xlsx, store.export_xlsx), (args.csv, store.export_csv)):
        if path:
            out = Path(path) if Path(path).is_absolute() else BASE / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(build())
            print(f"Zapisano: {out}")
