"""Filtry rejestru wynikające z tabeli kolumn chronionych."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozwiazanie.backend import filtry  # noqa: E402

ROWS = [
    {"city": "Kraków", "region": "małopolskie", "street_address": "ul. Długa 1", "availability_type": "24/7",
     "is_locked": False, "operational_status": "SPRAWNY", "possible_duplicate": True, "aed_sn": "SN-1",
     "pad_expiration_date": "2020-01-01"},
    {"city": "Kraśnik", "region": "lubelskie", "street_address": "Rynek 2", "availability_type": "TYLKO_PERSONEL",
     "is_locked": True, "operational_status": "NIEZNANY", "possible_duplicate": False, "aed_sn": ""},
    {"city": "Krosno", "region": "podkarpackie", "postal_code": "38-400", "availability_type": "GODZINY_OTWARCIA"},
]


class FiltryTest(unittest.TestCase):
    def test_public_cannot_filter_protected(self):
        params = {"f.possible_duplicate": "TRUE", "f.aed_sn": "TRUE", "f.region": "małopolskie", "inne": "x"}
        self.assertEqual(filtry.aktywne(params, "publiczny"), {"region": "małopolskie"})
        self.assertEqual(set(filtry.aktywne(params, "admin")), {"possible_duplicate", "aed_sn", "region"})

    def test_definitions_by_role(self):
        pub = filtry.definicje(ROWS, "publiczny")
        ids = {f["pole"] for c in pub["kategorie"] for f in c["filtry"]}
        self.assertFalse(ids & {"aed_sn", "possible_duplicate", "pad_expiration_date", "battery_expiration_date"})
        self.assertEqual(pub["najwazniejsze"][0]["etykieta"], "Dostępny 24/7")
        adm = filtry.definicje(ROWS, "admin")
        ids = {f["pole"] for c in adm["kategorie"] for f in c["filtry"]}
        self.assertTrue({"aed_sn", "possible_duplicate", "pad_expiration_date"} <= ids)

    def test_matching(self):
        self.assertTrue(filtry.pasuje(ROWS[0], {"availability_type": "24/7", "is_locked": "FALSE"}))
        self.assertFalse(filtry.pasuje(ROWS[1], {"is_locked": "FALSE"}))
        self.assertTrue(filtry.pasuje(ROWS[0], {"pad_expiration_date": "przeterminowane"}))
        self.assertTrue(filtry.pasuje(ROWS[2], {"pad_expiration_date": "brak"}))



if __name__ == "__main__":
    unittest.main()
