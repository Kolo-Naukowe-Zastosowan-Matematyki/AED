"""Testy bez sieci: parser godzin oraz źródło dane.gov.pl na zasymulowanych odpowiedziach API 1.4.

Uruchomienie:  python -m unittest discover -s tests -v
"""
import sys
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozwiazanie.scraping import danegov as dg  # noqa: E402
from rozwiazanie.backend.hours import is_open  # noqa: E402

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


class AedDatasetTest(unittest.TestCase):
    """Zbiór „System Ewidencji Zasobów AED” w formacie API portalu (bez magazynu danych)."""

    def setUp(self):
        from portal.backend.aed_dataset import AedDataset
        self.ds = AedDataset({})
        self.origin = "http://localhost:8000"

    def test_search(self):
        self.assertTrue(self.ds.search_matches({"q": "AED", "model[terms]": "dataset,resource"}))
        self.assertFalse(self.ds.search_matches({"q": "drogi"}))
        self.assertFalse(self.ds.search_matches({"q": "aed", "institution[id][terms]": "5"}))
        body = self.ds.patch_search(502, b"", {"q": "defibrylator"}, self.origin)
        import json
        resp = json.loads(body)
        self.assertEqual(resp["meta"]["count"], 1)
        self.assertEqual(resp["data"][0]["id"], "dataset-aed")

    def test_resources(self):
        status, _, res = self.ds.handle("/datasets/aed,system-ewidencji-zasobow-aed/resources", {}, self.origin)
        self.assertEqual(status, 200)
        self.assertEqual([r["attributes"]["title"] for r in res["data"]], ["Rejestr AED"])
        status, _, tab = self.ds.handle("/resources/aed-rejestr/data", {"page": "1"}, self.origin)
        self.assertEqual(status, 200)
        self.assertIn("col1", tab["meta"]["headers_map"])
        self.assertIsNone(self.ds.handle("/datasets/1354", {}, self.origin))


class ProxyTest(unittest.TestCase):
    def test_no_writes_to_production(self):
        from portal.backend import portal_proxy
        status, _, body = portal_proxy.forward("POST", "https://api.dane.gov.pl/1.4/datasets/1354/comments", {}, b"{}")
        self.assertEqual(status, 403)

    def test_comment_queue(self):
        import tempfile
        from pathlib import Path
        from portal.backend.uwagi import Comments
        with tempfile.TemporaryDirectory() as d:
            subs = Comments(Path(d))
            rec = subs.add("zbior:aed", {"data": {"type": "comment", "attributes": {
                "comment": "Zgłoszenie nowego AED", "applicant_email": "x@example.com"}}})
            self.assertEqual(rec["status"], "do_weryfikacji_przez_dostawce")
            self.assertNotIn("x@example.com", json.dumps(subs.list()))
            with self.assertRaises(ValueError):
                subs.add("zbior:aed", {"data": {"attributes": {"comment": ""}}})


class StoreSearchTest(unittest.TestCase):
    """Wyszukiwarka rejestru (serwis AED, strona główna)."""

    def setUp(self):
        import tempfile
        from rozwiazanie.backend.schema import AED
        from rozwiazanie.backend.store import Store
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = Store(Path(self.tempdir.name), {})
        self.store.by_source["danegov"] = [
            AED("aed-1", 52.2, 21.0, "danegov", "", "", nazwa_obiektu="Szkoła Łódzka",
                adres="ul. Główna 1, Warszawa", dostep="publiczny", extra={"zbior": "Rejestr AED"}),
            AED("aed-2", 52.3, 21.1, "danegov", "", "", nazwa_obiektu="Przychodnia",
                adres="ul. Krótka 2, Warszawa", dostep="w_godzinach"),
        ]
        self.store.by_source["danegov"].append(
            AED("aed-3", 50.0, 19.9, "danegov", "", "", nazwa_obiektu="Szkoła Kraków",
                adres="Rynek, Kraków", dostep="publiczny"))
        self.store._rebuild()

    def test_search_ignores_accents_and_filters_location(self):
        result = self.store.search(query="szkola", location="lodzka")
        self.assertEqual(result["razem"], 1)
        self.assertEqual(result["wyniki"][0]["id_aed"], "aed-1")

    def test_search_filters_access_source_and_paginates(self):
        result = self.store.search(access="publiczny", source="danegov", limit=1)
        self.assertEqual(result["razem"], 2)
        self.assertEqual([item["id_aed"] for item in result["wyniki"]], ["aed-1"])
        self.assertEqual(self.store.search(public_only=True, offset=1)["wyniki"][0]["id_aed"], "aed-3")

    def test_register_and_nearest(self):
        self.assertEqual(self.store.register()["liczba"], 3)
        near = self.store.nearest(50.01, 19.91, n=1, only_available=False)
        self.assertEqual(near[0]["id_aed"], "aed-3")
        self.assertLess(near[0]["odleglosc_m"], 2000)


    def test_whole_country_and_distance_order(self):
        self.assertEqual(self.store.search(location="Polska")["razem"], 3)  # domyślna wartość pola miejsca
        res = self.store.search(lat=50.01, lon=19.91)
        self.assertEqual(res["wyniki"][0]["id_aed"], "aed-3")
        self.assertIn("odleglosc_m", res["wyniki"][0])

    def test_nearest_within_criteria(self):
        near = self.store.nearest(50.01, 19.91, n=1, only_available=False, location="Warszawa")
        self.assertEqual(near[0]["id_aed"], "aed-1")  # najbliższe w wybranym miejscu, nie w ogóle

    def test_filter_options_follow_location(self):
        def dostepnosc(defs):
            f = next(f for c in defs["kategorie"] for f in c["filtry"] if f["pole"] == "availability_type")
            return {o["wartosc"]: o["liczba"] for o in f["opcje"] if o["liczba"]}
        self.assertEqual(sum(dostepnosc(self.store.filter_defs("publiczny")).values()), 3)
        self.assertEqual(dostepnosc(self.store.filter_defs("publiczny", location="Kraków")), {"24/7": 1})


class TercTest(unittest.TestCase):
    def setUp(self):
        from rozwiazanie.backend.teryt import Terc, _czytaj
        self.terc = Terc(_czytaj((Path(__file__).parent / "dane" / "terc.csv").read_bytes()))

    def test_area_from_city(self):
        self.assertEqual(self.terc.obszar("Legionowo", "mazowieckie"),
                         {"powiat": "powiat legionowski", "gmina": "gmina Legionowo"})
        self.assertEqual(self.terc.obszar("Radzymin", "mazowieckie")["powiat"], "powiat wołomiński")
        # miasto na prawach powiatu wygrywa z gminą wiejską o tej samej nazwie
        self.assertEqual(self.terc.obszar("Przemyśl", "podkarpackie")["powiat"], "Przemyśl (miasto na prawach powiatu)")
        self.assertEqual(self.terc.obszar("Nieznane", "mazowieckie"), {})

    def test_search_and_suggest_by_district(self):
        import tempfile
        from rozwiazanie.backend.schema import AED
        from rozwiazanie.backend.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp), {})
            store.terc = self.terc
            store.by_source["danegov"] = [
                AED("a", 52.395, 20.931, "danegov", "", "", adres="ul. Piłsudskiego 41, 05-120 Legionowo"),
                AED("b", 52.327, 21.108, "danegov", "", "", adres="al. Piłsudskiego 95, 05-270 Marki")]
            store._rebuild()
            self.assertEqual([r["id_aed"] for r in store.search(location="powiat legionowski")["wyniki"]], ["a"])
            self.assertEqual(store.search(location="gmina Marki")["razem"], 1)
            sug = {s["tekst"]: s["typ"] for s in store.suggest("legion")}
            self.assertEqual(sug.get("powiat legionowski"), "powiat")
            self.assertEqual(sug.get("gmina Legionowo"), "gmina")
            self.assertEqual(store.suggest("pols")[0]["tekst"], "Polska")
            defs = store.filter_defs("publiczny", location="Legionowo")  # filtr „Miejscowość” tylko z wyników
            miasta = next(f for c in defs["kategorie"] for f in c["filtry"] if f["pole"] == "city")["opcje"]
            self.assertEqual([o["wartosc"] for o in miasta], ["Legionowo"])


if __name__ == "__main__":
    unittest.main()
