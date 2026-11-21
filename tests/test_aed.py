"""Testy bez sieci: parser godzin oraz źródło dane.gov.pl na zasymulowanych odpowiedziach API 1.4.

Uruchomienie:  python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraping import danegov as dg  # noqa: E402
from backend.hours import is_open  # noqa: E402
from backend.schema import AED  # noqa: E402
from backend.store import Store  # noqa: E402

SAT_10 = datetime(2026, 11, 21, 10, 0)   # sobota
MON_10 = datetime(2026, 11, 23, 10, 0)   # poniedziałek
MON_20 = datetime(2026, 11, 23, 20, 0)


class HoursTest(unittest.TestCase):
    def test_24_7(self):
        self.assertTrue(is_open("24/7", SAT_10))

    def test_weekdays(self):
        spec = "Mo-Fr 07:30-15:30; Sa-Su,PH off"
        self.assertTrue(is_open(spec, MON_10))
        self.assertFalse(is_open(spec, MON_20))
        self.assertFalse(is_open(spec, SAT_10))

    def test_unknown(self):
        self.assertIsNone(is_open("", MON_10))
        self.assertIsNone(is_open("sunrise-sunset", MON_10))


DATASETS = {"data": [
    {"id": "101", "attributes": {"title": "Defibrylatory AED w gminie Przykładowo", "license_name": "CC0 1.0"}},
    {"id": "102", "attributes": {"title": "Rozkład jazdy autobusów"}},  # nieistotny – ma zostać pominięty
], "links": {}}
RESOURCES = {"data": [
    {"id": "9001", "attributes": {"title": "AED – tabela", "format": "csv"},
     "relationships": {"tabular_data": {}}},
    {"id": "9002", "attributes": {"title": "AED – plik", "format": "csv",
                                  "download_url": "https://example.invalid/aed.csv"}, "relationships": {}},
], "links": {}}
TABLE = {
    "meta": {"headers_map": {"col1": "Nazwa", "col2": "Szerokość", "col3": "Długość", "col4": "Godziny dostępności"},
             "data_schema": {"fields": [{"name": "col1", "geo": "label"}, {"name": "col2", "geo": "b"},
                                        {"name": "col3", "geo": "l"}, {"name": "col4"}]}},
    "data": [
        {"attributes": {"col1": {"val": "Urząd Gminy", "repr": "Urząd Gminy"}, "col2": {"val": 52.1}, "col3": {"val": 21.0},
                        "col4": {"val": "24/7"}}},
        {"attributes": {"col1": {"val": "Poza Polską"}, "col2": {"val": 40.0}, "col3": {"val": 2.0}, "col4": {"val": ""}}},
    ],
    "links": {},
}
CSV_FILE = "Lokalizacja;X;Y;Opis\nSzkoła nr 1;18,6466;54,3520;hol przy portierni\n".encode("cp1250")


def fake_get_json(url, timeout=25):
    if "/datasets?q=" in url:
        return DATASETS
    if url.split("?")[0].endswith("/datasets/101/resources"):
        return RESOURCES
    if "/resources/9001/data" in url:
        return TABLE
    raise AssertionError(f"nieoczekiwany URL: {url}")


class DaneGovTest(unittest.TestCase):
    def test_load(self):
        with mock.patch.object(dg, "_get_json", side_effect=fake_get_json), \
                mock.patch.object(dg, "_get_bytes", return_value=CSV_FILE):
            recs, report = dg.load({"queries": ["defibrylator"]})
        names = sorted(r.nazwa_obiektu for r in recs)
        self.assertEqual(names, ["Szkoła nr 1", "Urząd Gminy"])
        urzad = next(r for r in recs if r.nazwa_obiektu == "Urząd Gminy")
        self.assertEqual((urzad.szerokosc, urzad.dlugosc), (52.1, 21.0))
        self.assertEqual(urzad.dostep, "publiczny")          # 24/7 => publiczny
        self.assertEqual(urzad.licencja, "CC0 1.0")
        self.assertIn("/resource/9001", urzad.zrodlo_url)
        szkola = next(r for r in recs if r.nazwa_obiektu == "Szkoła nr 1")
        self.assertEqual((szkola.szerokosc, szkola.dlugosc), (54.352, 18.6466))  # X/Y rozpoznane i zamienione
        self.assertEqual(szkola.opis_lokalizacji, "hol przy portierni")
        self.assertEqual(len(report), 2)


class StoreSearchTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = Store(Path(self.tempdir.name), {})
        self.store.by_source["danegov"] = [
            AED("aed-1", 52.2, 21.0, "danegov", "", "", nazwa_obiektu="Szkoła Łódzka",
                adres="ul. Główna 1, Warszawa", dostep="publiczny", extra={"zbior": "Rejestr AED"}),
            AED("aed-2", 52.3, 21.1, "danegov", "", "", nazwa_obiektu="Przychodnia",
                adres="ul. Krótka 2, Warszawa", dostep="w_godzinach"),
        ]
        self.store.by_source["osm"] = [
            AED("osm-1", 50.0, 19.9, "osm", "", "", nazwa_obiektu="Szkoła Kraków",
                adres="Rynek, Kraków", dostep="publiczny"),
        ]
        self.store._rebuild()

    def test_search_ignores_accents_and_filters_location(self):
        result = self.store.search(query="szkola", location="lodzka")
        self.assertEqual(result["razem"], 1)
        self.assertEqual(result["wyniki"][0]["id_aed"], "aed-1")

    def test_search_filters_access_source_and_paginates(self):
        result = self.store.search(access="publiczny", source="danegov", limit=1)
        self.assertEqual(result["razem"], 1)
        self.assertEqual([item["id_aed"] for item in result["wyniki"]], ["aed-1"])
        self.assertEqual(self.store.search(public_only=True)["razem"], 2)

    def test_export_records_fetches_dane_gov_instead_of_local_records(self):
        remote_record = AED("online-1", 52.4, 21.2, "danegov", "", "", nazwa_obiektu="Online")
        with mock.patch.object(dg, "load", return_value=([remote_record], [])) as load:
            records = self.store.export_records()

        self.assertEqual(records, [remote_record])
        load.assert_called_once_with({})

    def test_export_xlsx_uses_polish_headers_and_single_sheet(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl nie jest zainstalowany")

        from io import BytesIO
        with mock.patch.object(dg, "load", return_value=(self.store.by_source["danegov"], [])):
            wb = openpyxl.load_workbook(BytesIO(self.store.export_xlsx()), read_only=True)
        self.assertEqual(wb.sheetnames, ["AED"])
        ws = wb["AED"]
        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        self.assertEqual(headers, [
            "numer_seryjny_aed", "szerokosc_geograficzna", "dlugosc_geograficzna",
            "wojewodztwo", "miejscowosc", "kod_pocztowy", "adres_uliczny",
            "wewnatrz_budynku", "nazwa_budynku", "dokladna_lokalizacja",
            "typ_dostepnosci", "godziny_dostepnosci", "czy_zamkniety",
            "status_operacyjny", "nazwa_operatora", "data_waznosci_elektrod",
            "data_waznosci_baterii", "data_aktualizacji_rekordu", "zrodlo_danych",
            "mozliwy_duplikat",
        ])
        self.assertEqual(ws.max_row, 3)


if __name__ == "__main__":
    unittest.main()
