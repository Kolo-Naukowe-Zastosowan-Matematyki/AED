"""Filtry rejestru AED wynikające z tabeli kolumn chronionych (common/aed_columns.json).

Zasada: filtr jest przypisany do kolumny złotego standardu. Użytkownik publiczny widzi i może użyć tylko filtrów
na kolumnach jawnych; administrator wszystkich. Serwer to wymusza (parametry filtrów na kolumnach chronionych
od roli publicznej są ignorowane), więc ukrycie filtra w interfejsie nie jest jedynym zabezpieczeniem.

Kolejność: najpierw „najważniejsze” (to, co decyduje, czy AED da się użyć w nagłej sytuacji), potem kategorie.
Parametry zapytania: f.<pole>=<wartość>, np. f.availability_type=24/7, f.is_locked=FALSE, f.region=mazowieckie.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import date, timedelta

from .columns import COLUMNS, ROLE_ADMIN

_KOL = {c["pole"]: c for c in COLUMNS}
SLOWNIK_DOSTEPNOSCI = {"24/7": "Całodobowo (24/7)", "GODZINY_OTWARCIA": "W godzinach otwarcia",
                       "TYLKO_PERSONEL": "Tylko personel"}
SLOWNIK_STATUSU = {"SPRAWNY": "Sprawny", "W_SERWISIE": "W serwisie", "NIESPRAWNY": "Niesprawny", "NIEZNANY": "Nieznany"}
TERMINY = {"przeterminowane": "Przeterminowane", "90dni": "Kończy się w ciągu 90 dni", "wazne": "Ważne",
           "brak": "Brak danych"}

# Najważniejsze: szybkie przełączniki na górze (każdy to jedna para kolumna = wartość, „otwarte teraz” z godzin)
NAJWAZNIEJSZE = [
    {"id": "f.availability_type", "pole": "availability_type", "wartosc": "24/7", "etykieta": "Dostępny 24/7"},
    {"id": "f.otwarte_teraz", "pole": "opening_hours", "wartosc": "1", "etykieta": "Dostępny teraz"},
    {"id": "f.is_locked", "pole": "is_locked", "wartosc": "FALSE", "etykieta": "Bez klucza i kodu"},
    {"id": "f.operational_status", "pole": "operational_status", "wartosc": "SPRAWNY", "etykieta": "Sprawny"},
    {"id": "f.is_indoor", "pole": "is_indoor", "wartosc": "FALSE", "etykieta": "Na zewnątrz budynku"},
]

KATEGORIE = [
    ("Lokalizacja", [("region", "wybor"), ("city", "wybor")]),
    ("Dostępność", [("availability_type", "slownik"), ("is_locked", "tak_nie"), ("is_indoor", "tak_nie")]),
    ("Stan urządzenia", [("operational_status", "slownik"), ("pad_expiration_date", "termin"),
                         ("battery_expiration_date", "termin")]),
    ("Dysponent i jakość danych", [("operator_name", "wybor"), ("possible_duplicate", "tak_nie"),
                                   ("aed_sn", "jest")]),
]
# kategorie widoczne w całości tylko w panelu administratora (także ich filtry po kolumnach jawnych, np. dysponent)
KATEGORIE_ADMIN = {"Dysponent i jakość danych"}
FILTRY_ADMIN = {pole for nazwa, pola in KATEGORIE if nazwa in KATEGORIE_ADMIN for pole, _ in pola}
ETYKIETY_TAK_NIE = {"is_locked": ("Wymaga klucza lub kodu", "Bez klucza i kodu"),
                    "is_indoor": ("Wewnątrz budynku", "Na zewnątrz"),
                    "possible_duplicate": ("Możliwy duplikat", "Bez duplikatu")}


def dozwolone(pole: str, rola: str) -> bool:
    kol = _KOL.get(pole)
    return kol is not None and (rola == ROLE_ADMIN or not kol["chroniona"])


def _bool_txt(v) -> str:
    return "TRUE" if v is True else "FALSE" if v is False else ""


def _termin(v, dzis: date) -> str:
    try:
        d = date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        d = None
    if d is None:
        return "brak"
    if d < dzis:
        return "przeterminowane"
    return "90dni" if d <= dzis + timedelta(days=90) else "wazne"


def wartosc(row: dict, pole: str, rodzaj: str, dzis: date | None = None) -> str:
    """Wartość wiersza w postaci porównywanej z parametrem filtra."""
    v = row.get(pole)
    if rodzaj == "tak_nie" or isinstance(v, bool):
        return _bool_txt(v)
    if rodzaj == "termin":
        return _termin(v, dzis or date.today())
    if rodzaj == "jest":
        return "TRUE" if v not in (None, "") else "FALSE"
    return "" if v is None else str(v)


def _rodzaje() -> dict[str, str]:
    out = {p: r for _, pola in KATEGORIE for p, r in pola}
    return out


RODZAJE = _rodzaje()


def aktywne(params: dict, rola: str) -> dict[str, str]:
    """Parametry f.<pole> dozwolone dla roli (reszta jest ignorowana: serwer wymusza ochronę kolumn)."""
    out = {}
    for k, v in params.items():
        if not k.startswith("f.") or v in ("", None):
            continue
        pole = k[2:]
        if pole == "otwarte_teraz":
            if dozwolone("opening_hours", rola):
                out[pole] = v
        elif dozwolone(pole, rola) and (rola == ROLE_ADMIN or pole not in FILTRY_ADMIN):
            out[pole] = v
    return out


def pasuje(row: dict, filtry: dict[str, str], otwarte_teraz=None, dzis: date | None = None) -> bool:
    for pole, oczekiwana in filtry.items():
        if pole == "otwarte_teraz":
            if oczekiwana == "1" and otwarte_teraz is False:  # nieznane godziny nie wykluczają (lepiej pokazać)
                return False
            continue
        if wartosc(row, pole, RODZAJE.get(pole, "wybor"), dzis) != oczekiwana:
            return False
    return True


def _sortkey(s: str) -> str:
    return unicodedata.normalize("NFKD", s.casefold().replace("ł", "l"))


def definicje(rows: list[dict], rola: str) -> dict:
    """Opis filtrów dla interfejsu: najważniejsze + kategorie z opcjami i licznikami (tylko kolumny dozwolone dla roli)."""
    dzis = date.today()
    naj = [dict(f) for f in NAJWAZNIEJSZE if dozwolone(f["pole"], rola)]
    for f in naj:
        if f["id"] != "f.otwarte_teraz":
            f["liczba"] = sum(1 for r in rows if wartosc(r, f["pole"], RODZAJE.get(f["pole"], "wybor"), dzis) == f["wartosc"])
    kategorie = []
    for nazwa, pola in KATEGORIE:
        if nazwa in KATEGORIE_ADMIN and rola != ROLE_ADMIN:
            continue
        filtry = []
        for pole, rodzaj in pola:
            if not dozwolone(pole, rola):
                continue
            licz = Counter(wartosc(r, pole, rodzaj, dzis) for r in rows)
            if rodzaj == "slownik":
                slownik = SLOWNIK_DOSTEPNOSCI if pole == "availability_type" else SLOWNIK_STATUSU
                opcje = [{"wartosc": k, "etykieta": e, "liczba": licz.get(k, 0)} for k, e in slownik.items()]
            elif rodzaj == "tak_nie":
                tak, nie = ETYKIETY_TAK_NIE.get(pole, ("Tak", "Nie"))
                opcje = [{"wartosc": "TRUE", "etykieta": tak, "liczba": licz.get("TRUE", 0)},
                         {"wartosc": "FALSE", "etykieta": nie, "liczba": licz.get("FALSE", 0)}]
            elif rodzaj == "termin":
                opcje = [{"wartosc": k, "etykieta": e, "liczba": licz.get(k, 0)} for k, e in TERMINY.items()]
            elif rodzaj == "jest":
                opcje = [{"wartosc": "TRUE", "etykieta": "Podany", "liczba": licz.get("TRUE", 0)},
                         {"wartosc": "FALSE", "etykieta": "Brak", "liczba": licz.get("FALSE", 0)}]
            else:
                opcje = [{"wartosc": k, "etykieta": k, "liczba": n}
                         for k, n in sorted(licz.items(), key=lambda kv: _sortkey(kv[0])) if k]
            filtry.append({"id": f"f.{pole}", "pole": pole, "etykieta": _KOL[pole]["nazwa"].rstrip("?"),
                           "chroniona": _KOL[pole]["chroniona"], "opcje": opcje})
        if filtry:
            kategorie.append({"nazwa": nazwa, "filtry": filtry})
    return {"rola": rola, "najwazniejsze": naj, "kategorie": kategorie}


def podpowiedzi(rows: list[dict], fraza: str, limit: int = 8) -> list[dict]:
    """Podpowiedzi do pola „Adres, miejscowość lub lokalizacja” z danych rejestru (tylko kolumny jawne):
    cały kraj („Polska”), miejscowości, gminy i powiaty (gdy jest słownik TERC), województwa, ulice z miejscowością,
    kody pocztowe. Najpierw dopasowanie od początku słowa."""
    q = _sortkey(fraza.strip())
    if len(q) < 2:
        return []
    licz: Counter = Counter()
    typ: dict[str, str] = {}
    for r in rows:
        for tekst, rodzaj in ((r.get("city"), "miejscowość"), (r.get("region"), "województwo"),
                              (r.get("powiat"), "powiat"), (r.get("gmina"), "gmina"),
                              ("Polska", "cały kraj"), (r.get("postal_code"), "kod pocztowy"),
                              (", ".join(x for x in (r.get("street_address"), r.get("city")) if x)
                               if r.get("street_address") else "", "adres")):
            if tekst:
                licz[tekst] += 1
                typ.setdefault(tekst, rodzaj)
    trafienia = []
    for tekst, n in licz.items():
        t = _sortkey(tekst)
        if t.startswith(q):
            ranga = 0
        elif any(w.startswith(q) for w in t.replace(",", " ").replace(".", " ").split()):
            ranga = 1
        elif q in t:
            ranga = 2
        else:
            continue
        kolej = {"cały kraj": 0, "miejscowość": 1, "gmina": 2, "powiat": 3, "województwo": 4, "adres": 5,
                 "kod pocztowy": 6}[typ[tekst]]
        trafienia.append((ranga, kolej, -n, _sortkey(tekst), tekst))
    trafienia.sort()
    return [{"tekst": t[4], "typ": typ[t[4]], "liczba": licz[t[4]]} for t in trafienia[:limit]]
