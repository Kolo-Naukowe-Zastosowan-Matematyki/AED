"""Testy agregacji do wzorcowej tabeli (logika eksportu XLSX z natka_branch + poprawki zgodności z dane.gov.pl).

Uruchomienie:  python -m unittest discover -s tests -v
"""
import csv
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozwiazanie.backend import columns  # noqa: E402
from rozwiazanie.backend.schema import AED  # noqa: E402
from rozwiazanie.scraping import agregacja as ag  # noqa: E402


class FakeProtected:
    def __init__(self, data):
        self.data = data

    def get(self, id_aed):
        return dict(self.data.get(id_aed, {}))


RECS = [
    AED("a1", 52.229700, 21.012200, "danegov", "https://dane.gov.pl/pl/dataset/1/resource/1", "CC0 1.0",
        nazwa_obiektu="Urząd", adres="ul. Długa 1, 00-950 Warszawa", wewnatrz=True, pietro="1",
        opis_lokalizacji="hol", dostep="publiczny", godziny_dostepnosci="Mo-Fr 08:00-16:00", dysponent="Gmina X",
        data_weryfikacji="2026-10-01"),
    AED("a2", 52.229750, 21.012250, "danegov", "u2", "CC0 1.0", dostep="w_godzinach"),  # ok. 6 m od a1
    AED("a3", 50.0, 19.9, "danegov", "u3", "CC0 1.0", dostep="nieznany", wewnatrz=False),
]


class AgregacjaTest(unittest.TestCase):
    def test_public_table(self):
        cols, rows = ag.agreguj(RECS, "publiczny", FakeProtected({"a1": {"numer_seryjny_aed": "SN-1"}}), "2026-11-21T10:00")
        names = [c["pole"] for c in cols]
        self.assertEqual(names, columns.PUBLIC_FIELDS)
        self.assertNotIn("numer_seryjny_aed", rows[0])
        r = rows[0]
        self.assertEqual((r["kod_pocztowy"], r["miejscowosc"]), ("00-950", "Warszawa"))
        self.assertEqual(r["typ_dostepnosci"], "PUBLICZNY")          # dostęp to nie godziny
        self.assertEqual(r["godziny_dostepnosci"], "Mo-Fr 08:00-16:00")
        self.assertEqual(r["dokladna_lokalizacja"], "hol, piętro 1")
        self.assertEqual(rows[1]["typ_dostepnosci"], "GODZINY_OTWARCIA")
        self.assertEqual([x["mozliwy_duplikat"] for x in rows], [True, True, False])  # a1 i a2 < 15 m
        self.assertEqual(str(rows[2]["data_aktualizacji_rekordu"]), "2026-11-21")  # data pobrania, gdy brak weryfikacji

    def test_admin_table_and_serial_duplicates(self):
        prot = FakeProtected({"a1": {"numer_seryjny_aed": "SN-9"}, "a3": {"numer_seryjny_aed": "SN-9",
                                                                        "data_waznosci_elektrod": "2027-01-31"}})
        cols, rows = ag.agreguj(RECS, "admin", prot)
        self.assertEqual([c["pole"] for c in cols], [c["pole"] for c in columns.COLUMNS])
        self.assertEqual(rows[2]["numer_seryjny_aed"], "SN-9")
        self.assertTrue(rows[2]["mozliwy_duplikat"])  # ten sam numer seryjny co a1
        self.assertEqual(str(rows[2]["data_waznosci_elektrod"]), "2027-01-31")

    def test_csv_follows_portal_rules(self):
        body = ag.do_csv(*ag.agreguj(RECS, "publiczny")).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(body)))
        self.assertEqual(rows[0]["wewnatrz_budynku"], "True")       # reguła bool: True/False
        self.assertEqual(rows[2]["wewnatrz_budynku"], "False")
        self.assertEqual(rows[1]["wewnatrz_budynku"], "")
        self.assertEqual(rows[0]["szerokosc_geograficzna"], "52.2297")  # kropka dziesiętna
        self.assertEqual(rows[0]["data_aktualizacji_rekordu"], "2026-10-01")

    def test_xlsx_single_sheet_both_writers(self):
        cols, rows = ag.agreguj(RECS, "publiczny")
        for body in (ag._xlsx_stdlib(cols, rows), ag.do_xlsx(cols, rows)):
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
                self.assertNotIn("xl/worksheets/sheet2.xml", z.namelist())
        try:
            import openpyxl
        except ImportError:
            return
        for body in (ag._xlsx_stdlib(cols, rows), ag.do_xlsx(cols, rows)):
            ws = openpyxl.load_workbook(io.BytesIO(body)).active
            self.assertEqual(ws.title, "AED")
            self.assertEqual([c.value for c in ws[1]], [c["pole"] for c in cols])
            self.assertEqual(ws.max_row, 4)


if __name__ == "__main__":
    unittest.main()
