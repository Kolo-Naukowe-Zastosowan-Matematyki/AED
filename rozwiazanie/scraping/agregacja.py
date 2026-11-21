"""Agregacja: wszystkie rekordy AED z wielu zbiorów dane.gov.pl -> jedna tabela we wzorcowym zakresie.

Logika przeniesiona z gałęzi natka_branch (Store.export_xlsx, autorka: Natalia Pośpiech) do scrapingu
naszego rozwiązania, z poprawkami zgodności z dane.gov.pl (mcod):
  * wartości logiczne True/False      (mcod settings VERIFICATION_RULES „bool”: „Wymagane wartości: True, False”),
  * kod pocztowy xx-xxx               (reguła „pna”), liczby z kropką dziesiętną, daty yyyy-mm-dd,
  * typ dostępności ze słownika       (dostęp to nie godziny: godziny są w osobnej kolumnie),
  * duplikaty: ten sam numer seryjny albo inny AED w odległości do 15 m,
  * dane z pamięci podręcznej rozwiązania (bez pobierania API przy każdym eksporcie),
  * kolumny z tabeli wzorca common/aed_columns.json; kolumny chronione tylko dla administratora.

Kolejność kroków jak w agregacji DGA w mcod (resources/dga_utils.py: create_main_dga_df):
  1. rekordy ze wszystkich zasobów (scraping/danegov.py: load) -> 2. wiersz wzorcowy dla każdego rekordu
  -> 3. kolumna dysponenta (nazwa_operatora) -> 4. jeden arkusz / jeden plik CSV.
"""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from rozwiazanie.backend.columns import COLUMNS, ROLE_ADMIN

DUPLIKAT_M = 15.0
TYP_DOSTEPNOSCI = {
    "publiczny": "PUBLICZNY",
    "w_godzinach": "GODZINY_OTWARCIA",
    "ograniczony": "TYLKO_PERSONEL",
    "prywatny": "PRYWATNY",
    "nieznany": "NIEZNANY",
}
_PNA = re.compile(r"\b(\d{2}-\d{3})\s+([^\d,;]+)")


def kolumny(rola: str) -> list[dict]:
    """Kolumny tabeli wzorca widoczne dla roli (publiczna: bez chronionych)."""
    return [c for c in COLUMNS if rola == ROLE_ADMIN or not c["chroniona"]]


def _metry(a, b) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.szerokosc), math.radians(b.szerokosc)
    dp, dl = p2 - p1, math.radians(b.dlugosc - a.dlugosc)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _duplikaty(records: list, serials: list[str]) -> set[int]:
    """Indeksy rekordów, które wyglądają na duplikat innego rekordu (siatka ~15 m, bez porównań n^2)."""
    out: set[int] = set()
    by_serial: dict[str, list[int]] = {}
    for i, s in enumerate(serials):
        if s:
            by_serial.setdefault(s, []).append(i)
    for idxs in by_serial.values():
        if len(idxs) > 1:
            out.update(idxs)
    cell = 0.0002  # ok. 22 m szerokości
    grid: dict[tuple[int, int], list[int]] = {}
    for i, r in enumerate(records):
        grid.setdefault((int(r.szerokosc / cell), int(r.dlugosc / cell)), []).append(i)
    for (gy, gx), idxs in grid.items():
        for i in idxs:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for j in grid.get((gy + dy, gx + dx), ()):
                        if j > i and _metry(records[i], records[j]) <= DUPLIKAT_M:
                            out.update((i, j))
    return out


def _data(value: str) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def wiersz(r, chronione: dict | None, duplikat: bool, data_pobrania: str = "") -> dict:
    """Jeden rekord AED -> wiersz we wzorcowym zakresie (nazwy kolumn z common/aed_columns.json)."""
    ch = chronione or {}
    m = _PNA.search(r.adres or "")
    lokalizacja = ", ".join(x for x in (r.opis_lokalizacji, f"piętro {r.pietro}" if r.pietro else "") if x)
    return {
        "numer_seryjny_aed": ch.get("numer_seryjny_aed") or None,
        "szerokosc_geograficzna": round(r.szerokosc, 6),
        "dlugosc_geograficzna": round(r.dlugosc, 6),
        "wojewodztwo": None,
        "miejscowosc": m.group(2).strip() if m else None,
        "kod_pocztowy": m.group(1) if m else None,
        "adres_uliczny": r.adres or None,
        "wewnatrz_budynku": r.wewnatrz,
        "nazwa_budynku": r.nazwa_obiektu or None,
        "dokladna_lokalizacja": lokalizacja or None,
        "typ_dostepnosci": TYP_DOSTEPNOSCI.get(r.dostep, "NIEZNANY"),
        "godziny_dostepnosci": r.godziny_dostepnosci or None,
        "czy_zamkniety": None,
        "status_operacyjny": "NIEZNANY",
        "nazwa_operatora": r.dysponent or None,
        "data_waznosci_elektrod": _data(ch.get("data_waznosci_elektrod")),
        "data_waznosci_baterii": _data(ch.get("data_waznosci_baterii")),
        "data_aktualizacji_rekordu": _data(r.data_weryfikacji) or _data(data_pobrania),
        "zrodlo_danych": r.zrodlo_url or r.zrodlo or None,
        "mozliwy_duplikat": duplikat,
        "osoba_kontaktowa": ch.get("osoba_kontaktowa") or None,
        "telefon_kontaktowy": ch.get("telefon_kontaktowy") or None,
    }


def agreguj(records: list, rola: str, chronione=None, data_pobrania: str = "") -> tuple[list[dict], list[dict]]:
    """Zwraca (kolumny, wiersze) jednej tabeli. `chronione`: obiekt z .get(id_aed) (backend/columns.py)."""
    cols = kolumny(rola)
    ch = [chronione.get(r.id_aed) if chronione is not None else {} for r in records]
    dup = _duplikaty(records, [c.get("numer_seryjny_aed", "") for c in ch])
    names = [c["pole"] for c in cols]
    rows = [{k: v for k, v in wiersz(r, c, i in dup, data_pobrania).items() if k in names}
            for i, (r, c) in enumerate(zip(records, ch))]
    return cols, rows


def _txt(v) -> str:
    """Zapis wartości wg reguł portalu: True/False, yyyy-mm-dd, kropka dziesiętna, puste = pusta komórka."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def do_csv(cols: list[dict], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([c["pole"] for c in cols])
    for row in rows:
        w.writerow([_txt(row.get(c["pole"])) for c in cols])
    return ("﻿" + buf.getvalue()).encode("utf-8")


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
    ws.append([c["pole"] for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for row in rows:
        # bool jako tekst True/False (reguła portalu), daty jako daty, liczby jako liczby
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
    for ri, values in enumerate([[c["pole"] for c in cols]] +
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
