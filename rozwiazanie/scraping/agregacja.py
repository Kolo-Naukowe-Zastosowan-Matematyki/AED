"""Agregacja: rekordy AED ze wszystkich zbiorów dane.gov.pl -> jedna tabela w złotym standardzie (schemat Oliwii).

Logika eksportu przeniesiona z gałęzi natka_branch (Store.export_xlsx, autorka: Natalia Pośpiech) do scrapingu
naszego rozwiązania. Wiersze są już ustandaryzowane przy imporcie (standard.py: mapowanie kolumn, słowniki,
daty, województwo), tutaj tylko:
  1. kolumny z tabeli wzorca common/aed_columns.json, chronione tylko dla administratora,
  2. wartości chronione od dostawców (data/chronione) nadpisują puste pola chronione,
  3. possible_duplicate: ten sam SN więcej niż raz albo inny AED w odległości do 15 m,
  4. zapis: CSV z separatorem „;” (nagłówek = polskie nazwy pól), XLSX jeden arkusz, TRUE/FALSE, RRRR-MM-DD.
Kolejność kroków jak w agregacji DGA w mcod (resources/dga_utils.py: create_main_dga_df).
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from rozwiazanie.backend.columns import COLUMNS, ROLE_ADMIN
from rozwiazanie.scraping.standard import SCHEMA, standaryzuj

DUPLIKAT_M = 15.0
CSV_SEP = SCHEMA.get("csv", {}).get("separator", ";")
PRAWDA, FALSZ = SCHEMA.get("csv", {}).get("prawda", "TRUE"), SCHEMA.get("csv", {}).get("falsz", "FALSE")
_TYPY = {c["pole"]: c["typ"] for c in COLUMNS}

# starsze rekordy z pamięci podręcznej (sprzed standaryzacji) przepuszczamy przez ten sam normalizator
_AED_KOLUMNY = ["nazwa_obiektu", "opis_lokalizacji", "adres", "szerokosc", "dlugosc", "wewnatrz", "dostep",
                "godziny_dostepnosci", "dysponent", "data_weryfikacji"]
_AED_MAPA = {"pola": {"building_name": "nazwa_obiektu", "exact_location": "opis_lokalizacji",
                      "street_address": "adres", "latitude": "szerokosc", "longitude": "dlugosc",
                      "is_indoor": "wewnatrz", "availability_type": "dostep", "opening_hours": "godziny_dostepnosci",
                      "operator_name": "dysponent", "record_updated_at": "data_weryfikacji"},
             "para": None, "teryt": None}


def kolumny(rola: str) -> list[dict]:
    """Kolumny tabeli wzorca widoczne dla roli (publiczna: bez chronionych)."""
    return [c for c in COLUMNS if rola == ROLE_ADMIN or not c["chroniona"]]


def _metry(a: dict, b: dict) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dp, dl = p2 - p1, math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _duplikaty(rows: list[dict]) -> set[int]:
    """Indeksy wierszy, które wyglądają na duplikat innego (ten sam SN albo siatka ~15 m, bez porównań n^2)."""
    out: set[int] = set()
    by_serial: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        if r.get("aed_sn"):
            by_serial.setdefault(str(r["aed_sn"]).strip().upper(), []).append(i)
    for idxs in by_serial.values():
        if len(idxs) > 1:
            out.update(idxs)
    cell = 0.0002  # ok. 22 m szerokości
    grid: dict[tuple[int, int], list[int]] = {}
    for i, r in enumerate(rows):
        grid.setdefault((int(r["latitude"] / cell), int(r["longitude"] / cell)), []).append(i)
    for (gy, gx), idxs in grid.items():
        for i in idxs:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for j in grid.get((gy + dy, gx + dx), ()):
                        if j > i and _metry(rows[i], rows[j]) <= DUPLIKAT_M:
                            out.update((i, j))
    return out


def _data(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def status_sprawnosci(row, dzis=None):
    dzis = dzis or date.today()
    for field in ("pad_expiration_date", "battery_expiration_date"):
        deadline = _data(row.get(field))
        if deadline and deadline < dzis:
            return "PO_TERMINIE"
    return row.get("operational_status")


def standard_rekordu(r, data_pobrania: str = "") -> dict:
    """Rekord AED -> wiersz złotego standardu (z importu, a dla starszych rekordów przez ten sam normalizator)."""
    std = (r.extra or {}).get("std")
    if std:
        return dict(std)
    row = {k: getattr(r, k) for k in _AED_KOLUMNY}
    rec, _, _ = standaryzuj(row, _AED_MAPA, {"zasob_url": r.zrodlo_url, "pobrano": data_pobrania})
    return rec or {}


def wiersz(r, chronione: dict | None, data_pobrania: str = "") -> dict:
    """Jeden rekord AED -> wiersz w złotym standardzie (nazwy kolumn z common/aed_columns.json)."""
    out = standard_rekordu(r, data_pobrania)
    for k, v in (chronione or {}).items():
        if v not in (None, "") and k in _TYPY:
            out[k] = v
    for k, typ in _TYPY.items():
        v = out.get(k)
        if typ == "date":
            out[k] = _data(v)
        elif v == "":
            out[k] = None
    out["operational_status"] = status_sprawnosci(out)
    return out


def agreguj(records: list, rola: str, chronione=None, data_pobrania: str = "") -> tuple[list[dict], list[dict]]:
    """Zwraca (kolumny, wiersze) jednej tabeli. `chronione`: obiekt z .get(id_aed) (backend/columns.py)."""
    cols = kolumny(rola)
    full = [wiersz(r, chronione.get(r.id_aed) if chronione is not None else {}, data_pobrania) for r in records]
    dup = _duplikaty(full)
    names = [c["pole"] for c in cols]
    rows = []
    for i, (r, row) in enumerate(zip(records, full)):
        row["possible_duplicate"] = i in dup
        out = {k: row.get(k) for k in names}
        out["_id"] = r.id_aed  # identyfikator rekordu w rozwiązaniu (nie trafia do CSV/XLSX: nie ma go w tabeli wzorca)
        rows.append(out)
    return cols, rows


def _txt(v) -> str:
    """Zapis wartości wg złotego standardu: TRUE/FALSE, RRRR-MM-DD, kropka dziesiętna, puste = pusta komórka."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return PRAWDA if v else FALSZ
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def do_csv(cols: list[dict], rows: list[dict]) -> bytes:
    """CSV do bezpośredniego importu: separator „;”, nagłówek = polskie nazwy pól, UTF-8 z BOM (Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=CSV_SEP, lineterminator="\r\n")
    w.writerow([c["nazwa"] for c in cols])
    for row in rows:
        w.writerow([_txt(row.get(c["pole"])) for c in cols])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def do_xlsx(cols: list[dict], rows: list[dict]) -> bytes:
    """Jeden arkusz „AED”, nagłówek w 1. wierszu (tak portal importuje XLSX do widoku tabelarycznego).
    Z openpyxl: wygląd z eksportu Natalii (pogrubiony nagłówek, filtr, zamrożony wiersz, tabela).
    Bez openpyxl: ten sam arkusz z biblioteki standardowej, żeby prototyp działał bez instalowania pakietów."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return _xlsx_stdlib(cols, rows)
    return _xlsx_openpyxl(cols, rows)


def _xlsx_openpyxl(cols, rows) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = "AED"
    ws.append([c["nazwa"] for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for row in rows:
        # bool jako tekst TRUE/FALSE (złoty standard), daty jako daty, liczby jako liczby
        ws.append([_txt(v) if isinstance(v, bool) else v for v in (row.get(c["pole"]) for c in cols)])
    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 30
    for i, c in enumerate(cols, start=1):
        letter = ws.cell(row=1, column=i).column_letter
        values = [len(str(ws.cell(row=r, column=i).value or "")) for r in range(1, ws.max_row + 1)]
        ws.column_dimensions[letter].width = min(max(max(values) + 2, 12), 45)
        for r in range(2, ws.max_row + 1):
            if c["typ"] == "number":
                ws.cell(row=r, column=i).number_format = "0.000000"
            elif c["typ"] == "date":
                ws.cell(row=r, column=i).number_format = "yyyy-mm-dd"
    if ws.max_row >= 2:
        table = Table(displayName="AED", ref=ws.dimensions)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(table)
    else:
        ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_stdlib(cols, rows) -> bytes:
    def cell(ref, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(_txt(v))}</t></is></c>'

    lines = []
    for ri, values in enumerate([[c["nazwa"] for c in cols]] +
                                [[row.get(c["pole"]) for c in cols] for row in rows], start=1):
        cells = "".join(cell(f"{_col(ci)}{ri}", v) for ci, v in enumerate(values, start=1) if v not in (None, ""))
        lines.append(f'<row r="{ri}">{cells}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/>'
             f'</sheetView></sheetViews><sheetData>{"".join(lines)}</sheetData></worksheet>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="AED" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            z.writestr(name, body)
    return out.getvalue()
