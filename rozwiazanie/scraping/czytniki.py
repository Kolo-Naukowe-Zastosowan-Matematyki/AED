"""Odporne czytniki plików z dane.gov.pl: dowolny plik -> lista wierszy (słowników).

Nie ufamy deklarowanemu formatowi zasobu: rodzaj pliku rozpoznajemy po zawartości (sygnatura ZIP/XLSX/ODS/XLS,
XML, JSON, HTML), a deklarowany format służy tylko jako podpowiedź. Obsługiwane:
  * CSV/TXT  – kodowanie (BOM, UTF-8, UTF-16, CP1250, ISO-8859-2), separator (; , tab |) wykrywany po spójności
               liczby pól, wiersze tytułowe nad nagłówkiem są pomijane,
  * XLSX/ODS – biblioteka standardowa (zipfile + xml), pierwszy niepusty arkusz, nagłówek wykrywany jak w CSV,
  * XLS      – przez xlrd, jeśli jest zainstalowany (inaczej czytelny komunikat w raporcie),
  * JSON     – GeoJSON, lista obiektów, {"data": [...]}, JSON Lines, odpowiedź JSON:API; śmieci przed JSON-em,
  * XML/KML/GPX – powtarzające się elementy jako wiersze, Placemark/wpt ze współrzędnymi,
  * ZIP      – każdy plik w archiwum.
Każdy czytnik zwraca (wiersze, uwagi). Błąd nie przerywa importu: trafia do uwag i do raportu.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter
from datetime import date, timedelta
from xml.etree import ElementTree as ET

DELIMS = [";", ",", "\t", "|"]
MAX_ROWS = 50000


class NieobslugiwanyPlik(Exception):
    """Plik, którego nie da się odczytać jako tabeli (np. strona HTML zamiast pliku)."""


# ---------------------------------------------------------------- tekst

def dekoduj(raw: bytes) -> tuple[str, str]:
    """Zwraca (tekst, kodowanie). Najpierw BOM, potem UTF-8, potem polskie kodowania jednobajtowe."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace"), "utf-16"
    if len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", "replace"), "utf-16-le"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    # CP1250 i ISO-8859-2 różnią się m.in. ą/ś/ź (0xB9/0x9C/0x9F vs 0xB1/0xB6/0xBC): wybieramy to, które daje więcej polskich liter
    best = max(("cp1250", "iso-8859-2"), key=lambda e: sum(raw.decode(e, "replace").count(ch) for ch in "ąśźĄŚŹ"))
    return raw.decode(best, "replace"), best


def _pusty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _naglowek(rows: list[list]) -> int:
    """Indeks wiersza nagłówka: pierwszy wiersz, który ma tyle niepustych komórek co typowy wiersz danych
    i składa się głównie z tekstu (pomija tytuły, puste wiersze i notki nad tabelą)."""
    if not rows:
        return 0
    widths = [sum(not _pusty(c) for c in r) for r in rows[:60]]
    typical = Counter(w for w in widths if w > 1).most_common(1)
    target = typical[0][0] if typical else max(widths or [0])
    for i, r in enumerate(rows[:30]):
        cells = [str(c).strip() for c in r if not _pusty(c)]
        if len(cells) >= max(2, int(target * 0.6)):
            texty = sum(not re.fullmatch(r"[-+]?\d+([.,]\d+)?", c) for c in cells)
            if texty >= len(cells) * 0.6:
                return i
    return 0


def _do_slownikow(rows: list[list]) -> list[dict]:
    if not rows:
        return []
    h = _naglowek(rows)
    header, seen = [], Counter()
    for i, c in enumerate(rows[h]):
        name = str(c).strip() if not _pusty(c) else f"kolumna_{i + 1}"
        seen[name] += 1
        header.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    out = []
    for r in rows[h + 1:h + 1 + MAX_ROWS]:
        if all(_pusty(c) for c in r):
            continue
        d = {header[i] if i < len(header) else f"kolumna_{i + 1}": c for i, c in enumerate(r)}
        out.append(d)
    return out


def wykryj_separator(text: str) -> str:
    """Separator, przy którym najwięcej linii ma tę samą (>1) liczbę pól. Odporne na przecinek dziesiętny
    w plikach z separatorem ';' i na cudzysłowy (liczymy pola csv.reader, nie znaki)."""
    lines = [l for l in text.splitlines()[:200] if l.strip()][:80]
    best, best_score = ",", -1.0
    for d in DELIMS:
        try:
            counts = [len(r) for r in csv.reader(lines, delimiter=d)]
        except csv.Error:
            continue
        if not counts:
            continue
        mode, freq = Counter(counts).most_common(1)[0]
        if mode < 2:
            continue
        score = freq / len(counts) + min(mode, 30) / 1000  # spójność, przy remisie więcej kolumn
        if score > best_score:
            best, best_score = d, score
    return best


def czytaj_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    text, enc = dekoduj(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    d = wykryj_separator(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=d))
    names = {";": "średnik", ",": "przecinek", "\t": "tabulator", "|": "kreska"}
    return _do_slownikow(rows), [f"CSV: kodowanie {enc}, separator {names[d]}"]


# ---------------------------------------------------------------- arkusze

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _kol(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def excel_data(serial) -> date | None:
    """Liczba seryjna daty Excela -> data (system 1900)."""
    try:
        f = float(serial)
    except (TypeError, ValueError):
        return None
    if 20000 < f < 80000:  # 1954..2119: rozsądny zakres dat w rejestrze AED
        return date(1899, 12, 30) + timedelta(days=int(f))
    return None


def czytaj_xlsx(raw: bytes) -> tuple[list[dict], list[str]]:
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    # style dat: numFmtId 14-22 i własne formaty z „yy”/„dd”
    date_styles: set[int] = set()
    if "xl/styles.xml" in z.namelist():
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.get("numFmtId")): n.get("formatCode", "").lower() for n in st.iter(f"{{{_NS['m']}}}numFmt")}
        xfs = st.find("m:cellXfs", _NS)
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId", 0))
            if 14 <= fid <= 22 or ("yy" in custom.get(fid, "") or "dd" in custom.get(fid, "")):
                date_styles.add(i)
    sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    notes = []
    for name in sheets:
        root = ET.fromstring(z.read(name))
        rows: list[list] = []
        for row in root.iter(f"{{{_NS['m']}}}row"):
            cells: dict[int, object] = {}
            for c in row.findall("m:c", _NS):
                t, s = c.get("t"), int(c.get("s", 0) or 0)
                v = c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
                elif v is not None:
                    val = v.text
                    if s in date_styles and excel_data(val):
                        val = excel_data(val).isoformat()
                else:
                    continue
                cells[_kol(c.get("r") or "A1")] = val
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        recs = _do_slownikow(rows)
        if recs:
            if len(sheets) > 1:
                notes.append(f"XLSX: arkusz {name.rsplit('/', 1)[-1]} z {len(sheets)}")
            return recs, notes
    return [], ["XLSX: brak danych w arkuszach"]


def czytaj_ods(raw: bytes) -> tuple[list[dict], list[str]]:
    z = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(z.read("content.xml"))
    T = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    O = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    for table in root.iter(f"{{{T}}}table"):
        rows = []
        for tr in table.iter(f"{{{T}}}table-row"):
            row = []
            for tc in tr.findall(f"{{{T}}}table-cell"):
                rep = min(int(tc.get(f"{{{T}}}number-columns-repeated", 1)), 200)
                val = tc.get(f"{{{O}}}date-value") or tc.get(f"{{{O}}}value") or \
                    " ".join("".join(p.itertext()) for p in tc if p.tag.endswith("}p"))
                row += [val[:10] if tc.get(f"{{{O}}}date-value") else val] * rep
            while row and _pusty(row[-1]):
                row.pop()
            rows.append(row)
        recs = _do_slownikow(rows)
        if recs:
            return recs, ["ODS"]
    return [], ["ODS: brak danych"]


def czytaj_xls(raw: bytes) -> tuple[list[dict], list[str]]:
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise NieobslugiwanyPlik("stary format XLS: zainstaluj pakiet xlrd (pip install xlrd)") from exc
    book = xlrd.open_workbook(file_contents=raw)
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode).date().isoformat())
                else:
                    row.append(cell.value)
            rows.append(row)
        recs = _do_slownikow(rows)
        if recs:
            return recs, ["XLS (xlrd)"]
    return [], ["XLS: brak danych"]


# ---------------------------------------------------------------- JSON

def _splaszcz(obj: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and not {"val", "repr"} & set(v):
            out.update(_splaszcz(v, key + "_"))
        else:
            out[key] = v
    return out


def _geom_punkt(geom: dict) -> tuple[float, float] | None:
    if not isinstance(geom, dict):
        return None
    t, c = geom.get("type"), geom.get("coordinates")
    try:
        if t == "Point":
            return float(c[0]), float(c[1])
        if t == "MultiPoint":
            return float(c[0][0]), float(c[0][1])
        if t in ("Polygon", "MultiPolygon", "LineString"):  # środek prostokąta otaczającego
            pts = c
            while isinstance(pts[0][0], list):
                pts = [p for part in pts for p in part]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _lista_rekordow(data) -> list[dict] | None:
    """Szuka w strukturze JSON listy obiektów, która wygląda na tabelę."""
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data[:20]):
        return data
    if isinstance(data, dict):
        for key in ("features", "data", "records", "rekordy", "items", "results", "rows", "result", "dane"):
            if key in data:
                found = _lista_rekordow(data[key])
                if found is not None:
                    return found
        lists = [v for v in data.values() if isinstance(v, (list, dict))]
        for v in lists:
            found = _lista_rekordow(v)
            if found:
                return found
    return None


def czytaj_json(raw: bytes) -> tuple[list[dict], list[str]]:
    text, _ = dekoduj(raw)
    s = text.strip()
    if not s:
        raise NieobslugiwanyPlik("pusty plik")
    notes = []
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # JSON Lines albo śmieci przed/po JSON-ie (np. JSONP „callback(...)”)
        lines = [l for l in s.splitlines() if l.strip()]
        try:
            data = [json.loads(l) for l in lines]
            notes.append("JSON Lines")
        except json.JSONDecodeError:
            start = min([i for i in (s.find("{"), s.find("[")) if i >= 0] or [-1])
            end = max(s.rfind("}"), s.rfind("]"))
            if start < 0 or end <= start:
                raise NieobslugiwanyPlik("to nie jest JSON (początek: %r)" % s[:60])
            data = json.loads(s[start:end + 1])
            notes.append("JSON wycięty spomiędzy innych znaków")
    recs = _lista_rekordow(data) or []
    rows = []
    for r in recs:
        if "attributes" in r and isinstance(r["attributes"], dict):  # JSON:API
            r = {**r["attributes"], "id": r.get("id")}
        if "geometry" in r or "properties" in r:  # GeoJSON Feature
            props = _splaszcz(dict(r.get("properties") or {}))
            pt = _geom_punkt(r.get("geometry"))
            if pt:
                props["_geom_x"], props["_geom_y"] = pt
            rows.append(props)
        else:
            rows.append(_splaszcz(r))
    return rows[:MAX_ROWS], notes or ["JSON"]


# ---------------------------------------------------------------- XML / KML / GPX

def _lokalna(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def czytaj_xml(raw: bytes) -> tuple[list[dict], list[str]]:
    root = ET.fromstring(raw)
    # KML: Placemark z <coordinates>lon,lat</coordinates>
    marks = [e for e in root.iter() if _lokalna(e.tag) == "Placemark"]
    if marks:
        rows = []
        for pm in marks:
            row = {}
            for e in pm.iter():
                name = _lokalna(e.tag)
                if name == "coordinates" and e.text:
                    parts = e.text.strip().split()[0].split(",")
                    row["_geom_x"], row["_geom_y"] = parts[0], parts[1]
                elif name in ("Data", "SimpleData") and e.get("name"):
                    row[e.get("name")] = "".join(e.itertext()).strip()
                elif name in ("name", "description", "address") and e.text:
                    row[name] = e.text.strip()
            rows.append(row)
        return rows, ["KML"]
    # GPX: <wpt lat="" lon="">
    wpts = [e for e in root.iter() if _lokalna(e.tag) == "wpt"]
    if wpts:
        return [{"lat": w.get("lat"), "lon": w.get("lon"),
                 **{_lokalna(c.tag): (c.text or "").strip() for c in w}} for w in wpts], ["GPX"]
    # ogólny XML: najczęstszy element mający dzieci = rekord
    counter = Counter()
    for e in root.iter():
        if len(e):
            counter[e.tag] += 1
    for tag, n in counter.most_common():
        if n < 1 or tag == root.tag and n == 1 and len(counter) > 1:
            continue
        rows = []
        for e in root.iter(tag):
            row = dict(e.attrib)
            for c in e:
                text = "".join(c.itertext()).strip()
                if len(c):
                    for cc in c:
                        row[f"{_lokalna(c.tag)}_{_lokalna(cc.tag)}"] = "".join(cc.itertext()).strip()
                else:
                    row[_lokalna(c.tag)] = text
                row.update({f"{_lokalna(c.tag)}_{k}": v for k, v in c.attrib.items()})
            rows.append({_lokalna(k): v for k, v in row.items()})
        if len(rows) > 1 or n == 1:
            return rows[:MAX_ROWS], [f"XML: rekord = <{_lokalna(tag)}>"]
    return [], ["XML: nie znaleziono powtarzających się rekordów"]


# ---------------------------------------------------------------- wejście

def rozpoznaj(raw: bytes, deklarowany: str = "") -> str:
    head = raw[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    if raw[:4] == b"PK\x03\x04":
        try:
            names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
        except zipfile.BadZipFile:
            return "nieznany"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if "content.xml" in names:
            return "ods"
        return "zip"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"
    low = head[:400].lower()
    if low.startswith((b"<!doctype html", b"<html")) or b"<html" in low[:200]:
        return "html"
    if head.startswith(b"<"):
        return "xml"
    if head.startswith((b"{", b"[")):
        return "json"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "csv"
    if deklarowany in ("json", "geojson", "jsonld") or re.match(rb"^[\w.$]+\s*\(\s*[\[{]", head):
        return "json"  # np. JSONP „callback({...})” albo śmieci przed JSON-em
    return {"kml": "xml", "gpx": "xml"}.get(deklarowany, "csv")


CZYTNIKI = {"csv": czytaj_csv, "xlsx": czytaj_xlsx, "ods": czytaj_ods, "xls": czytaj_xls,
            "json": czytaj_json, "xml": czytaj_xml}


def czytaj(raw: bytes, deklarowany: str = "", _glebokosc: int = 0) -> tuple[list[dict], list[str]]:
    """Dowolny plik -> (wiersze, uwagi). Rzuca NieobslugiwanyPlik z opisem, gdy pliku nie da się odczytać."""
    if not raw:
        raise NieobslugiwanyPlik("pusty plik")
    if raw[:2] == b"\x1f\x8b":  # serwer oddał plik skompresowany gzipem (wtedy json.loads widzi „Expecting value”)
        import gzip
        raw = gzip.decompress(raw)
    kind = rozpoznaj(raw, (deklarowany or "").lower())
    if kind == "html":
        raise NieobslugiwanyPlik("pod adresem pliku jest strona HTML, a nie dane (link do strony zamiast do pliku)")
    if kind == "zip":
        if _glebokosc:
            raise NieobslugiwanyPlik("zagnieżdżone archiwum ZIP")
        rows, notes = [], []
        z = zipfile.ZipFile(io.BytesIO(raw))
        for name in z.namelist():
            if name.endswith("/") or name.startswith("__MACOSX"):
                continue
            try:
                r, n = czytaj(z.read(name), name.rsplit(".", 1)[-1], _glebokosc + 1)
                rows += r
                notes += [f"ZIP/{name}: {x}" for x in n]
            except Exception as exc:  # noqa: BLE001
                notes.append(f"ZIP/{name}: pominięty ({exc})")
        return rows, notes
    if kind == "nieznany":
        raise NieobslugiwanyPlik("nierozpoznany format pliku")
    if kind == "xml" and deklarowany in ("csv", "txt"):
        kind = "xml"
    return CZYTNIKI[kind](raw)
