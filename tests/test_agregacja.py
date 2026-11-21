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
        cols, rows = ag.agreguj(RECS, "publiczny", FakeProtected({"a1": {"aed_sn": "SN-1"}}), "2026-11-21T10:00")
        names = [c["pole"] for c in cols]
        self.assertEqual(names, columns.PUBLIC_FIELDS)
        self.assertNotIn("aed_sn", rows[0])
        self.assertNotIn("possible_duplicate", rows[0])                 # kolumna chroniona
        r = rows[0]
        self.assertEqual((r["postal_code"], r["city"], r["street_address"]), ("00-950", "Warszawa", "ul. Długa 1"))
        self.assertEqual(r["region"], "mazowieckie")                     # z kodu pocztowego
        self.assertEqual(r["availability_type"], "24/7")                 # słownik złotego standardu
        self.assertEqual(r["opening_hours"], "Mo-Fr 08:00-16:00")
        self.assertEqual(r["operational_status"], "NIEZNANY")
        self.assertEqual(rows[1]["availability_type"], "GODZINY_OTWARCIA")
        self.assertEqual(str(rows[2]["record_updated_at"]), "2026-11-21")  # data pobrania, gdy brak weryfikacji

    def test_admin_table_and_duplicates(self):
        prot = FakeProtected({"a1": {"aed_sn": "SN-9"}, "a3": {"aed_sn": "SN-9", "pad_expiration_date": "2027-01-31"}})
        cols, rows = ag.agreguj(RECS, "admin", prot)
        self.assertEqual([c["pole"] for c in cols], [c["pole"] for c in columns.COLUMNS])
        self.assertEqual(rows[2]["aed_sn"], "SN-9")
        self.assertEqual([x["possible_duplicate"] for x in rows], [True, True, True])  # a1~a2 < 15 m, a1=a3 ten sam SN
        self.assertEqual(str(rows[2]["pad_expiration_date"]), "2027-01-31")

    def test_csv_golden_standard(self):
        body = ag.do_csv(*ag.agreguj(RECS, "admin", FakeProtected({}))).decode("utf-8-sig")
        header = body.splitlines()[0]
        self.assertTrue(header.startswith("aed_sn;latitude;longitude;region;city;postal_code;street_address;is_indoor"))
        rows = list(csv.DictReader(io.StringIO(body), delimiter=";"))
        self.assertEqual(rows[0]["is_indoor"], "TRUE")
        self.assertEqual(rows[2]["is_indoor"], "FALSE")
        self.assertEqual(rows[1]["is_indoor"], "")
        self.assertEqual(rows[0]["latitude"], "52.2297")                 # kropka dziesiętna
        self.assertEqual(rows[0]["record_updated_at"], "2026-10-01")
        self.assertEqual(rows[2]["possible_duplicate"], "FALSE")

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
