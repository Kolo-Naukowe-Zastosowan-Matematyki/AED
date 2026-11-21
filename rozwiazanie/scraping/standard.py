"""Standaryzacja: wiersze z dowolnego źródła -> rekordy w złotym standardzie (common/aed_columns.json).

Generyczna heurystyka zamiast reguł pod konkretne miasta, żeby nowe zbiory działały bez zmian w kodzie:
  1. mapowanie kolumn: role mapowe z dane.gov.pl (b/l/label) -> dokładny synonim -> synonim jako fragment nazwy,
  2. sprawdzenie mapowania po wartościach (np. kolumna „x” musi zawierać liczby w zasięgu Polski),
  3. wykrywanie kolumn po wartościach, gdy nazwa nic nie mówi: pary liczb w zasięgu Polski, „52.1, 21.0”,
     WKT POINT, stopnie-minuty-sekundy, współrzędne PUWG 1992 / PUWG 2000, kody pocztowe, kody TERYT,
  4. normalizacja wartości: przecinek dziesiętny, zamienione lat/lon, słowniki (dostępność, status),
     wartości logiczne, daty (różne zapisy -> RRRR-MM-DD), kod pocztowy XX-XXX, województwo,
  5. braki uzupełniane z kontekstu (instytucja publikująca, URL zasobu, data modyfikacji) albo z geokodera,
  6. nierozpoznane kolumny i odrzucone wiersze trafiają do raportu (nie przerywają importu).
Tylko biblioteka standardowa.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "common" / "aed_columns.json").read_text(encoding="utf-8"))
KOLUMNY = SCHEMA["kolumny"]
POLA = [c["pole"] for c in KOLUMNY]
SLOWNIKI = SCHEMA["slowniki"]
PL_BBOX = (48.9, 14.0, 55.1, 24.3)

TERYT_WOJ = {"02": "dolnośląskie", "04": "kujawsko-pomorskie", "06": "lubelskie", "08": "lubuskie",
             "10": "łódzkie", "12": "małopolskie", "14": "mazowieckie", "16": "opolskie", "18": "podkarpackie",
             "20": "podlaskie", "22": "pomorskie", "24": "śląskie", "26": "świętokrzyskie",
             "28": "warmińsko-mazurskie", "30": "wielkopolskie", "32": "zachodniopomorskie"}
# Przybliżenie: pierwsze dwie cyfry kodu pocztowego -> województwo (strefy PNA nie pokrywają się idealnie
# z granicami województw, dlatego to ostatnia deska ratunku, po danych źródłowych, TERYT i geokoderze).
_PNA_WOJ = {}
for _a, _b, _w in [(0, 9, "mazowieckie"), (10, 14, "warmińsko-mazurskie"), (15, 19, "podlaskie"),
                   (20, 24, "lubelskie"), (25, 25, "świętokrzyskie"), (26, 26, "mazowieckie"),
                   (27, 29, "świętokrzyskie"), (30, 34, "małopolskie"), (35, 39, "podkarpackie"),
                   (40, 44, "śląskie"), (45, 49, "opolskie"), (50, 59, "dolnośląskie"), (60, 64, "wielkopolskie"),
                   (65, 69, "lubuskie"), (70, 78, "zachodniopomorskie"), (80, 84, "pomorskie"),
                   (85, 89, "kujawsko-pomorskie"), (90, 99, "łódzkie")]:
    for _i in range(_a, _b + 1):
        _PNA_WOJ[f"{_i:02d}"] = _w


# ---------------------------------------------------------------- pomocnicze

def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s).replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9/]+", "_", s.lower()).strip("_")


def tekst(v) -> str:
    if isinstance(v, dict):
        v = v.get("repr", v.get("val", v.get("pl")))
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def w_polsce(lat: float, lon: float) -> bool:
    a, b, c, d = PL_BBOX
    return a <= lat <= c and b <= lon <= d


# ---------------------------------------------------------------- współrzędne

_DMS = re.compile(r"(\d{1,3})\s*[°º˚d]\s*(\d{1,2})?\s*['’′m]?\s*(\d{1,2}(?:[.,]\d+)?)?\s*(?:\"|”|″|''|s)?\s*([NSEWnsew])?")


def liczba(v) -> float | None:
    """'52,2297' / '52.2297' / ' 52.2297 N' / 52.2297 / '52°13′47″' -> float."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = tekst(v)
    if not s:
        return None
    if re.search(r"[°º˚′″]|\d\s*['\"]", s):
        m = _DMS.search(s)
        if m:
            d, mi, se = float(m.group(1)), float(m.group(2) or 0), float((m.group(3) or "0").replace(",", "."))
            val = d + mi / 60 + se / 3600
            return -val if (m.group(4) or "").upper() in ("S", "W") else val
    s = re.sub(r"(?i)\s*[NSEW]$|^[NSEW]\s*", "", s).replace(" ", "").replace(" ", "")
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    elif s.count(",") >= 1 and s.count(".") == 1 and s.rfind(",") < s.find("."):
        s = s.replace(",", "")  # separator tysięcy
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def para(v) -> tuple[float, float] | None:
    """Jedna komórka z dwiema współrzędnymi: '52.1, 21.0', '52,1 21,0', 'POINT(21.0 52.1)', '52.1;21.0'."""
    s = tekst(v)
    if not s:
        return None
    m = re.search(r"POINT\s*\(\s*([-\d.,]+)\s+([-\d.,]+)\s*\)", s, re.I)
    if m:
        x, y = liczba(m.group(1)), liczba(m.group(2))
        return (y, x) if x is not None and y is not None else None
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", s)
    if len(nums) == 4 and "," in s and s.count(",") == 3:  # '52,1, 21,0' – przecinki dziesiętne i rozdzielający
        nums = [f"{nums[0]}.{nums[1]}", f"{nums[2]}.{nums[3]}"]
    if len(nums) != 2:
        nums = re.findall(r"-?\d+\.\d+", s)
    if len(nums) == 2:
        a, b = liczba(nums[0]), liczba(nums[1])
        if a is not None and b is not None:
            return a, b
    return None


def _tm_odwrotne(x: float, y: float, lon0: float, k0: float, fe: float, fn: float) -> tuple[float, float]:
    """Odwrotne odwzorowanie Gaussa-Krügera na elipsoidzie GRS80 -> (lat, lon) w stopniach.
    x = współrzędna wschodnia (easting), y = północna (northing)."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = (y - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
         + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(p) ** 2
    t1 = math.tan(p) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(p) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p) ** 2) ** 1.5
    d = (x - fe) / (n1 * k0)
    lat = p - (n1 * math.tan(p) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                          + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(p)
    return math.degrees(lat), lon0 + math.degrees(lon)


def _tm_wprost(lat: float, lon: float, lon0: float, k0: float, fe: float, fn: float) -> tuple[float, float]:
    """Odwzorowanie Gaussa-Krügera na elipsoidzie GRS80: (lat, lon) w stopniach -> (easting, northing) w metrach."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    phi, dl = math.radians(lat), math.radians(lon - lon0)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t, c = math.tan(phi) ** 2, ep2 * math.cos(phi) ** 2
    aa = dl * math.cos(phi)
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi) - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = fe + k0 * n * (aa + (1 - t + c) * aa ** 3 / 6 + (5 - 18 * t + t ** 2 + 72 * c - 58 * ep2) * aa ** 5 / 120)
    y = fn + k0 * (m + n * math.tan(phi) * (aa ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * aa ** 4 / 24
                                            + (61 - 58 * t + t ** 2 + 600 * c - 330 * ep2) * aa ** 6 / 720))
    return x, y


def do_puwg1992(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 -> PUWG 1992 (EPSG:2180): (easting, northing)."""
    return _tm_wprost(lat, lon, 19.0, 0.9993, 500000.0, -5300000.0)


def z_ukladu_pl(a: float, b: float) -> tuple[float, float, str] | None:
    """Para liczb w metrach -> (lat, lon, układ). Rozpoznaje PUWG 1992 (EPSG:2180) i PUWG 2000 (EPSG:2176-2179),
    w obu kolejnościach osi (geodezyjne X to północ, w GIS-ie x to wschód)."""
    for east, north in ((a, b), (b, a)):
        if 140000 <= east <= 900000 and 120000 <= north <= 800000:
            lat, lon = _tm_odwrotne(east, north, 19.0, 0.9993, 500000.0, -5300000.0)
            if w_polsce(lat, lon):
                return lat, lon, "PUWG 1992"
        zone = int(east // 1000000)
        if zone in (5, 6, 7, 8) and 5400000 <= north <= 6200000:
            lat, lon = _tm_odwrotne(east, north, zone * 3.0, 0.999923, zone * 1000000 + 500000.0, 0.0)
            if w_polsce(lat, lon):
                return lat, lon, f"PUWG 2000 strefa {zone}"
    return None


def wspolrzedne(lat_raw, lon_raw) -> tuple[float, float, str] | None:
    """Dwie wartości (dowolny zapis) -> (lat, lon, uwaga) w WGS84 albo None."""
    a, b = liczba(lat_raw), liczba(lon_raw)
    if a is None or b is None:
        return None
    if w_polsce(a, b):
        return a, b, ""
    if w_polsce(b, a):
        return b, a, "zamienione lat/lon"
    if abs(a) > 1000 and abs(b) > 1000:
        r = z_ukladu_pl(b, a)  # kolumna „szerokości” = północ, „długości” = wschód
        if r:
            return r[0], r[1], r[2]
    # współrzędne zapisane bez kropki (np. 52229676 -> 52.229676)
    for scale in (1e6, 1e5, 1e7):
        if w_polsce(a / scale, b / scale):
            return a / scale, b / scale, "brak kropki dziesiętnej"
        if w_polsce(b / scale, a / scale):
            return b / scale, a / scale, "brak kropki dziesiętnej, zamienione lat/lon"
    return None


# ---------------------------------------------------------------- inne wartości

_PNA = re.compile(r"(?<!\d)(\d{2})[-\s]?(\d{3})(?!\d)")
_PNA_MIASTO = re.compile(r"(?<!\d)(\d{2}-\d{3})\s+([A-ZĄĆĘŁŃÓŚŹŻ][^\d,;()]+)")


def kod_pocztowy(v) -> str:
    s = tekst(v)
    m = re.fullmatch(r"\s*(\d{2})[-\s]?(\d{3})\s*", s) or _PNA.search(s) if s else None
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def logiczna(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = norm(tekst(v))
    if not s:
        return None
    if s in ("true", "tak", "t", "yes", "y", "1", "wewnatrz", "w_budynku", "wewnetrzny", "zamkniety", "zamknieta",
             "x", "prawda", "inside", "indoor"):
        return True
    if s in ("false", "nie", "n", "no", "0", "zewnatrz", "na_zewnatrz", "zewnetrzny", "otwarty", "otwarta",
             "falsz", "outside", "outdoor", "brak"):
        return False
    if s.startswith(("wewn", "w_budynku")) or "wewnatrz" in s:
        return True
    if s.startswith(("zewn", "na_zewn", "elewacja", "na_scianie_zewn")):
        return False
    return None


def data_iso(v) -> str:
    """Różne zapisy dat -> RRRR-MM-DD (pusty tekst, gdy się nie da)."""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = tekst(v)
    if not s:
        return ""
    m = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{4})", s)
        if m:
            d, mo, y = map(int, m.groups())
        else:
            m = re.fullmatch(r"(\d{1,2})[-./](\d{4})", s)  # MM.RRRR (np. data ważności elektrod)
            if not m:
                from rozwiazanie.scraping.czytniki import excel_data
                ed = excel_data(s) if re.fullmatch(r"\d{5}(\.\d+)?", s) else None
                return ed.isoformat() if ed else ""
            mo, y, d = int(m.group(1)), int(m.group(2)), 1
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def ze_slownika(nazwa: str, v) -> str:
    """Wartość -> klucz słownika (common/aed_columns.json „slowniki”) albo '' gdy nie pasuje."""
    s = norm(tekst(v))
    if not s:
        return ""
    slownik = SLOWNIKI[nazwa]
    for key, variants in slownik.items():
        if s == norm(key) or s in variants:
            return key
    for key, variants in slownik.items():  # fragmenty: „dostępny całodobowo dla wszystkich” -> 24/7
        if any(len(x) > 3 and x in s for x in variants):
            return key
    return ""


def dostepnosc(v, godziny: str = "") -> str:
    k = ze_slownika("availability_type", v)
    if k:
        return k
    g = norm(godziny)
    if g in ("24/7", "24h", "calodobowo", "0_24", "00_00_24_00", "mo_su_00_00_24_00", "pn_nd_0_24") or "24/7" in g:
        return "24/7"
    return "GODZINY_OTWARCIA" if g else ""


def wojewodztwo(v) -> str:
    s = norm(tekst(v)).replace("wojewodztwo_", "").replace("woj_", "")
    if not s:
        return ""
    for w in SLOWNIKI["wojewodztwa"]:
        if s == norm(w) or s.startswith(norm(w)[:6]) and norm(w).split("_")[0] in s:
            return w
    if re.fullmatch(r"\d{2,7}", s):
        return TERYT_WOJ.get(s.zfill(2)[:2] if len(s) <= 2 else s[:2], "")
    return ""


def woj_z_pna(pna: str) -> str:
    return _PNA_WOJ.get(pna[:2], "") if pna else ""


# ---------------------------------------------------------------- mapowanie kolumn

def _synonimy() -> dict[str, list[str]]:
    return {c["pole"]: [norm(s) for s in c.get("synonimy", [])] for c in KOLUMNY}


# pola opisujące miejsce konkretnego AED: długie elaboraty i teksty wspólne dla całego zbioru są odrzucane
OPISOWE = ("building_name", "exact_location", "street_address", "opening_hours")
MAX_OPIS = 300
OGOLNE_NAZWY = {"defibrylator", "aed", "defibrylator_aed", "aed_defibrylator", "automatyczny_defibrylator_zewnetrzny"}


def _probka(rows: list[dict], col: str, n: int = 200) -> list:
    out = []
    for r in rows[:n * 3]:
        v = r.get(col)
        if tekst(v):
            out.append(v)
            if len(out) >= n:
                break
    return out


def _udzial(values: list, test) -> float:
    return sum(1 for v in values if test(v)) / len(values) if values else 0.0


def mapuj_kolumny(columns: list[str], rows: list[dict], geo_roles: dict[str, str] | None = None) -> dict:
    """Zwraca {"pola": {pole_standardu: kolumna_źródła}, "para": kolumna z parą współrzędnych | None,
    "nierozpoznane": [...], "uwagi": [...]}."""
    geo_roles = geo_roles or {}
    syn = _synonimy()
    normed = {c: norm(c) for c in columns}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    uwagi: list[str] = []

    def take(pole, col, why):
        if pole not in mapping and col in normed and col not in used:
            mapping[pole] = col
            used.add(col)
            if why:
                uwagi.append(f"{pole} <- „{col}” ({why})")

    # 1) role mapowe nadane przez dostawcę w panelu dane.gov.pl
    for role, pole in (("b", "latitude"), ("l", "longitude"), ("label", "building_name")):
        if role in geo_roles:
            take(pole, geo_roles[role], f"rola mapowa {role}")
    # współrzędne z geometrii GeoJSON/KML
    if "_geom_x" in normed:
        take("longitude", "_geom_x", "geometria")
        take("latitude", "_geom_y", "geometria")
    # 2) dokładne synonimy (kolejność pól w schemacie = priorytet)
    by_norm: dict[str, list[str]] = {}
    for col, n in normed.items():
        by_norm.setdefault(n, []).append(col)
    for pole, names in syn.items():  # kolejność synonimów = priorytet (np. „nazwa” przed „lokalizacja”)
        for s_ in names:
            col = next((c for c in by_norm.get(s_, []) if c not in used), None)
            if col:
                take(pole, col, "")
                break
    # 3) synonim jako fragment nazwy (najdłuższy synonim wygrywa), tylko synonimy dłuższe niż 3 znaki
    cands = []
    for pole, names in syn.items():
        if pole in mapping:
            continue
        for col, n in normed.items():
            if col in used:
                continue
            for s in names:
                if len(s) > 3 and (s in n.split("_") or s in n):
                    cands.append((len(s), -POLA.index(pole), pole, col, s))
                elif len(n) >= 5 and len(s) > len(n) and s.startswith(n):
                    # nazwa obcięta (shapefile/DBF: 10 znaków), np. „lokalizacj”: im mniej ucięte, tym pewniejsze
                    cands.append((len(n) - 0.1 * (len(s) - len(n)), -POLA.index(pole), pole, col, s))
    for _, _, pole, col, s in sorted(cands, reverse=True):
        take(pole, col, f"nazwa zawiera „{s}”")

    # 4) kontrola po wartościach: współrzędne muszą być liczbami
    for pole in ("latitude", "longitude"):
        if pole in mapping and _udzial(_probka(rows, mapping[pole]), lambda v: liczba(v) is not None) < 0.5:
            uwagi.append(f"{pole}: kolumna „{mapping[pole]}” nie zawiera liczb, szukam po wartościach")
            used.discard(mapping.pop(pole))

    # 4b) kolumny opisowe: ogólny tekst powtarzany w każdym wierszu (np. opis, czym jest AED) albo bardzo długie
    #     elaboraty nie są lokalizacją konkretnego urządzenia, więc nie trafiają do pól miejsca
    for pole in OPISOWE:
        if pole not in mapping:
            continue
        vals = [tekst(v) for v in _probka(rows, mapping[pole])]
        if not vals:
            continue
        dlugie = sorted(len(v) for v in vals)[(len(vals) - 1) // 2] > MAX_OPIS
        wspolny = len(vals) >= 3 and max(vals.count(v) for v in set(vals)) >= 0.9 * len(vals) and len(vals[0]) > 60
        if dlugie or wspolny:
            powod = "ten sam długi tekst we wszystkich wierszach" if wspolny else "bardzo długie opisy"
            uwagi.append(f"{pole}: pominięto kolumnę „{mapping[pole]}” ({powod}, to nie jest lokalizacja urządzenia)")
            used.discard(mapping.pop(pole))

    # 5) wykrywanie po wartościach
    pair_col = None
    free = [c for c in columns if c not in used]
    if not ("latitude" in mapping and "longitude" in mapping):
        # jedna kolumna z parą współrzędnych
        for c in free:
            vals = _probka(rows, c, 50)
            if vals and _udzial(vals, lambda v: (p := para(v)) is not None and wspolrzedne(*p) is not None) >= 0.6:
                pair_col = c
                used.add(c)
                uwagi.append(f"latitude/longitude <- „{c}” (para współrzędnych w jednej kolumnie)")
                break
    if pair_col is None and not ("latitude" in mapping and "longitude" in mapping):
        num = {}
        for c in [c for c in columns if c not in used]:
            vals = _probka(rows, c, 100)
            nums = [liczba(v) for v in vals]
            nums = [x for x in nums if x is not None]
            if vals and len(nums) >= 0.8 * len(vals):
                num[c] = nums
        lats = [c for c, xs in num.items() if all(49 <= x <= 55 for x in xs)]
        lons = [c for c, xs in num.items() if all(14 <= x <= 24.2 for x in xs)]
        if "latitude" in mapping and not lons:
            lons = [c for c in lats if c != mapping["latitude"]]  # np. dwie kolumny w zakresie 49-55 przy zamianie
        if "latitude" not in mapping and lats:
            c = next((c for c in lats if c not in lons or len(lats) == 1), lats[0])
            take("latitude", c, "wartości 49-55")
        if "longitude" not in mapping:
            c = next((c for c in lons if c != mapping.get("latitude")), None)
            if c:
                take("longitude", c, "wartości 14-24")
        if not ("latitude" in mapping and "longitude" in mapping):  # metry: PUWG 1992 / 2000
            big = [c for c, xs in num.items() if c not in used and xs and all(abs(x) > 1000 for x in xs)]
            for i, c1 in enumerate(big):
                for c2 in big[i + 1:]:
                    r = next((r for r in rows if liczba(r.get(c1)) and liczba(r.get(c2))), None)
                    if r and z_ukladu_pl(liczba(r[c1]), liczba(r[c2])):
                        mapping.pop("latitude", None), mapping.pop("longitude", None)
                        take("latitude", c1, "układ PUWG")
                        take("longitude", c2, "układ PUWG")
                        break
                if "latitude" in mapping and "longitude" in mapping:
                    break
    if "postal_code" not in mapping:
        for c in [c for c in columns if c not in used]:
            vals = _probka(rows, c, 50)
            if vals and _udzial(vals, lambda v: re.fullmatch(r"\d{2}-\d{3}", tekst(v))) >= 0.8:
                take("postal_code", c, "wartości XX-XXX")
                break
    teryt = next((c for c in columns if c not in used and "teryt" in normed[c]), None)
    if teryt:
        used.add(teryt)
    return {"pola": mapping, "para": pair_col, "teryt": teryt, "uwagi": uwagi,
            "nierozpoznane": [c for c in columns if c not in used and not c.startswith("_")]}


# ---------------------------------------------------------------- rekord

def standaryzuj(row: dict, mapa: dict, ctx: dict, geokoder=None) -> tuple[dict | None, str, list[str]]:
    """Wiersz źródła -> (rekord w złotym standardzie | None, powód odrzucenia, uwagi)."""
    m = mapa["pola"]
    def g(pole: str) -> str:
        v = tekst(row.get(m[pole])) if pole in m else ""
        return "" if pole in OPISOWE and len(v) > MAX_OPIS else v  # pojedynczy elaborat w komórce
    uwagi: list[str] = []
    rec = {p: "" for p in POLA}

    rec["aed_sn"] = g("aed_sn")
    rec["street_address"] = g("street_address")
    rec["city"] = g("city")
    rec["postal_code"] = kod_pocztowy(g("postal_code"))
    addr_all = " ".join(x for x in (rec["street_address"], rec["city"], g("postal_code")) if x)
    mm = _PNA_MIASTO.search(addr_all)
    if mm:
        rec["postal_code"] = rec["postal_code"] or mm.group(1)
        if not rec["city"]:
            rec["city"] = mm.group(2).strip()
        # adres w jednej kolumnie: „ul. Długa 1, 00-950 Warszawa” -> ulica bez kodu i miasta
        if rec["street_address"] and mm.group(0) in rec["street_address"]:
            rec["street_address"] = rec["street_address"].replace(mm.group(0), "").strip(" ,;")
    rec["city"] = rec["city"] or ctx.get("miasto", "")

    # współrzędne
    coords = None
    if mapa.get("para"):
        p = para(row.get(mapa["para"]))
        coords = wspolrzedne(*p) if p else None
    elif "latitude" in m and "longitude" in m:
        coords = wspolrzedne(row.get(m["latitude"]), row.get(m["longitude"]))
    if coords and coords[2]:
        uwagi.append(coords[2])
    geo = None
    if not coords and geokoder is not None:
        query = ", ".join(x for x in (rec["street_address"], rec["postal_code"], rec["city"]) if x)
        if rec["street_address"] and (rec["city"] or rec["postal_code"]):
            geo = geokoder.adres(query)
            if geo:
                coords = (geo["lat"], geo["lon"], "geokodowanie GUGiK")
                uwagi.append("geokodowanie GUGiK")
    if not coords:
        if not rec["street_address"]:
            return None, "brak współrzędnych i adresu", uwagi
        return None, "brak współrzędnych, adresu nie udało się zgeokodować", uwagi
    rec["latitude"], rec["longitude"] = round(coords[0], 6), round(coords[1], 6)

    # województwo: źródło -> TERYT -> geokoder -> kod pocztowy
    rec["region"] = wojewodztwo(g("region"))
    if not rec["region"] and mapa.get("teryt"):
        rec["region"] = TERYT_WOJ.get(tekst(row.get(mapa["teryt"])).zfill(7)[:2], "")
    if not rec["region"] and geo and geo.get("region"):
        rec["region"] = geo["region"]
    # odwrotne geokodowanie (najbliższy punkt adresowy PRG): województwo, a gdy źródło podaje same współrzędne,
    # także ulica i kod pocztowy, żeby punkty z jednej miejscowości dało się od siebie odróżnić
    if geokoder is not None and (not rec["region"] or not rec["street_address"]):
        rev = geokoder.odwrotne(rec["latitude"], rec["longitude"])
        if rev:
            rec["region"] = rec["region"] or rev.get("region", "")
            rec["city"] = rec["city"] or rev.get("city", "")
            if not rec["street_address"] and rev.get("street_address"):
                rec["street_address"] = rev["street_address"]
                rec["postal_code"] = rec["postal_code"] or kod_pocztowy(rev.get("postal_code", ""))
                uwagi.append("adres z odwrotnego geokodowania GUGiK")
    rec["region"] = rec["region"] or woj_z_pna(rec["postal_code"]) or ctx.get("wojewodztwo", "")

    rec["building_name"] = g("building_name")
    if norm(rec["building_name"]) in OGOLNE_NAZWY:
        rec["building_name"] = ""  # „Defibrylator” w kolumnie nazwy nic nie mówi o miejscu
    rec["exact_location"] = g("exact_location")
    rec["is_indoor"] = logiczna(g("is_indoor"))
    if rec["is_indoor"] is None:
        blob = norm(f"{rec['exact_location']} {g('is_indoor')}")
        if re.search(r"(^|_)(hol|korytarz|recepcj|portier|parter|pietr|wewnatrz|sekretariat|klatk|szatni)", blob):
            rec["is_indoor"] = True
        elif re.search(r"(^|_)(elewacj|zewnatrz|na_zewn|przy_wejsciu_do_budynku|wiat|slup)", blob):
            rec["is_indoor"] = False
    rec["opening_hours"] = g("opening_hours")
    rec["availability_type"] = dostepnosc(g("availability_type"), rec["opening_hours"])
    if rec["availability_type"] == "24/7" and norm(rec["opening_hours"]) in ("24/7", "24h"):
        rec["opening_hours"] = ""  # 24/7 to kategoria, nie godziny
    rec["is_locked"] = logiczna(g("is_locked"))
    if rec["is_locked"] is None and g("is_locked"):
        s = norm(g("is_locked"))
        rec["is_locked"] = True if any(x in s for x in ("klucz", "kod", "portier", "zamk")) else None
    rec["operational_status"] = ze_slownika("operational_status", g("operational_status")) or "NIEZNANY"
    rec["operator_name"] = g("operator_name") or ctx.get("instytucja", "")
    rec["pad_expiration_date"] = data_iso(g("pad_expiration_date"))
    rec["battery_expiration_date"] = data_iso(g("battery_expiration_date"))
    rec["record_updated_at"] = data_iso(g("record_updated_at")) or data_iso(ctx.get("zmodyfikowano")) \
        or data_iso(ctx.get("pobrano")) or date.today().isoformat()
    rec["data_source"] = ctx.get("zasob_url", "") or g("data_source")
    rec["possible_duplicate"] = False
    return rec, "", uwagi


def braki(rec: dict) -> list[str]:
    """Wymagane pola standardu, których rekord nie ma (do raportu jakości, rekord i tak trafia do tabeli)."""
    return [c["pole"] for c in KOLUMNY
            if c.get("wymagalnosc") == "wymagane" and not c["chroniona"] and rec.get(c["pole"]) in ("", None)]
