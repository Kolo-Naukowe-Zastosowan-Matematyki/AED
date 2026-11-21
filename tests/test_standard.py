"""Standaryzacja heterogenicznych plików z dane.gov.pl do złotego standardu (schemat Oliwii).

Przypadki odtwarzają problemy z prawdziwych zasobów (Marki: same adresy, Krosno: dziwna nazwa kolumny
długości, Przemyśl: CSV, którego nie rozpoznawał csv.Sniffer, i XML, 39512: „JSON”, który nie jest JSON-em),
plus nowe, nieznane układy, na które parser ma być odporny.

Uruchomienie:  python -m unittest discover -s tests -v
"""
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rozwiazanie.scraping import czytniki, standard  # noqa: E402
from rozwiazanie.scraping.danegov import standaryzuj_wiersze  # noqa: E402

CTX = {"resource_url": "https://dane.gov.pl/pl/dataset/1/resource/2", "license": "CC0 1.0", "institution": "Urząd Miasta Marki",
       "dataset_title": "Defibrylatory", "zasob_url": "https://dane.gov.pl/pl/dataset/1/resource/2",
       "instytucja": "Urząd Miasta Marki", "miasto": "Marki", "zmodyfikowano": "2026-05-04"}


class FakeGeo:
    """Geokoder testowy (bez sieci): zwraca stały punkt dla znanych adresów."""
    def __init__(self):
        self.pytania = []

    def adres(self, q):
        self.pytania.append(q)
        if "Piłsudskiego 95" in q:
            return {"lat": 52.3205, "lon": 21.1043, "region": "mazowieckie", "city": "Marki"}
        return None

    def odwrotne(self, lat, lon):
        return {"region": "mazowieckie"}


def run(raw: bytes, fmt="csv", geo=None):
    rows, notes = czytniki.czytaj(raw, fmt)
    entry = {}
    recs = standaryzuj_wiersze(rows, {}, CTX, entry, geo, "2")
    return [r.extra["std"] for r in recs], entry, notes


class CzytnikiTest(unittest.TestCase):
    def test_whole_row_in_one_cell(self):
        # plik Marek: cały wiersz w jednej komórce, nagłówek „Długość geograficzna,Szerokość geograficzna, Nazwa, …”
        raw = ('"Długość geograficzna,Szerokość geograficzna, Nazwa, Lokalizacja, Adres, Numer Id"\n'
               '"21.107557,52.326697,Urząd Miasta Marki,hol parter,al. Józefa Piłsudskiego 95, Marki,1"\n'
               '"21.098185,52.32396,Szkoła Podstawowa nr 2,portiernia,ul. Szkolna 2,2"\n').encode("utf-8")
        recs, entry, _ = run(raw)
        r = recs[0]
        self.assertEqual((r["latitude"], r["longitude"]), (52.326697, 21.107557))
        self.assertEqual((r["building_name"], r["exact_location"]), ("Urząd Miasta Marki", "hol parter"))
        self.assertEqual(r["street_address"], "al. Józefa Piłsudskiego 95, Marki")  # przecinek w adresie
        self.assertEqual(recs[1]["street_address"], "ul. Szkolna 2")

    def test_legionowo_address_in_parts(self):
        # zbiór Legionowa: ulica rozbita na cecha_ulicy, nazwa_ulicy, nr_budynku, nr_lokalu
        raw = (Path(__file__).parent / "dane" / "legionowo.csv").read_bytes()
        recs, entry, _ = run(raw)
        self.assertEqual(len(recs), 24)
        r = recs[0]
        self.assertEqual((r["building_name"], r["city"], r["postal_code"]), ("Urząd Miasta Legionowo", "Legionowo", "05-120"))
        self.assertEqual(r["street_address"], "ul. Piłsudskiego 41")
        self.assertEqual(recs[14]["street_address"], "al. 1 Dywizji Zmechanizowanej 16")
        self.assertEqual(recs[9]["building_name"], 'Pływalnia "Wodne Piaski"')
        self.assertEqual(r["region"], "mazowieckie")
        self.assertNotIn("nazwa_ulicy", entry["nierozpoznane_kolumny"])
        row = {"c": "ulica", "u": "Długa", "n": "5", "l": "3"}
        self.assertEqual(standard.adres_z_czesci(row, {"cecha": "c", "ulica": "u", "nr": "n", "lokal": "l"}), "ul. Długa 5/3")

    def test_point_far_from_dataset_is_reported_not_changed(self):
        raw = ("Nazwa;Szerokosc;Dlugosc\nUrząd;52,3267;21,1076\nSzkoła;52,3240;21,0982\n"
               "Basen;52,3170;21,1041\nHala;49,7188;21,7203\n").encode("utf-8")
        recs, entry, _ = run(raw)
        self.assertEqual(len(recs), 4)
        self.assertEqual(len(entry["podejrzane_wspolrzedne"]), 1)
        self.assertIn("wiersz 4", entry["podejrzane_wspolrzedne"][0])
        self.assertEqual(recs[3]["building_name"], "Hala")

    def test_csv_cp1250_semicolon_decimal_comma_title_row(self):
        raw = ("Wykaz defibrylatorów AED – stan na 2026\n\n"
               "Lp.;Nazwa obiektu;Adres;Szerokość geograficzna;Długość geograficzna;Dostępność\n"
               "1;Urząd Miasta;ul. Rynek 1, 38-400 Krosno;49,6887;21,7706;całodobowo\n"
               "2;Szkoła Podstawowa nr 3;ul. Szkolna 2, 38-400 Krosno;49,6901;21,7650;w godzinach pracy\n").encode("cp1250")
        recs, entry, notes = run(raw)
        self.assertIn("separator średnik", notes[0])
        self.assertEqual(len(recs), 2)
        r = recs[0]
        self.assertEqual((r["latitude"], r["longitude"]), (49.6887, 21.7706))
        self.assertEqual((r["building_name"], r["street_address"], r["postal_code"], r["city"]),
                         ("Urząd Miasta", "ul. Rynek 1", "38-400", "Krosno"))
        self.assertEqual(r["region"], "podkarpackie")
        self.assertEqual(r["availability_type"], "24/7")
        self.assertEqual(recs[1]["availability_type"], "GODZINY_OTWARCIA")
        self.assertIn("Lp.", entry["nierozpoznane_kolumny"])  # nierozpoznana kolumna trafia do raportu

    def test_krosno_odd_longitude_header_found_by_values(self):
        raw = ("Lokalizacja AED,Szer. N,Dł. E (WGS-84),Uwagi\n"
               "\"Hala sportowa, ul. Bursaki 1\",\"49,6950\",\"21,7533\",wejście główne\n"
               "Basen miejski,49.6801,21.7712,\n").encode("utf-8")
        recs, entry, _ = run(raw)
        self.assertEqual(len(recs), 2, entry)
        self.assertEqual((recs[0]["latitude"], recs[0]["longitude"]), (49.695, 21.7533))

    def test_przemysl_tab_separated_with_quotes_and_multiline(self):
        raw = ("nazwa\tadres\tlat\tlon\topis\n"
               "\"Dworzec PKP\"\t\"Plac Legionów 1\"\t49.7838\t22.7765\t\"hol, przy kasach\nparter\"\n"
               "Urząd\tRynek 1\t49.7843\t22.7678\tsekretariat\n").encode("utf-8")
        recs, entry, notes = run(raw)
        self.assertIn("tabulator", notes[0])
        self.assertEqual(len(recs), 2)
        self.assertTrue(recs[0]["is_indoor"])  # „hol” => wewnątrz

    def test_json_variants_and_html_instead_of_file(self):
        for raw in (b'\xef\xbb\xbf[{"lat": "52,1", "lng": "21,0", "nazwa": "A"}]',
                    b'callback({"data": [{"lat": 52.1, "lng": 21.0, "nazwa": "A"}]});',
                    b'{"lat": 52.1, "lng": 21.0, "nazwa": "A"}\n{"lat": 52.2, "lng": 21.1, "nazwa": "B"}\n'):
            recs, entry, _ = run(raw, "json")
            self.assertGreaterEqual(len(recs), 1, raw)
            self.assertEqual(recs[0]["building_name"], "A")
        with self.assertRaises(czytniki.NieobslugiwanyPlik) as err:
            czytniki.czytaj(b"<!DOCTYPE html><html><body>Strona</body></html>", "json")
        self.assertIn("HTML", str(err.exception))

    def test_geojson_point(self):
        raw = json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [22.77, 49.78]},
             "properties": {"name": "Muzeum", "access": "yes", "indoor": "yes"}}]}).encode()
        recs, _, _ = run(raw, "geojson")
        self.assertEqual((recs[0]["latitude"], recs[0]["longitude"], recs[0]["building_name"]), (49.78, 22.77, "Muzeum"))
        self.assertTrue(recs[0]["is_indoor"])

    def test_generic_xml(self):
        raw = """<?xml version="1.0" encoding="UTF-8"?>
<defibrylatory><defibrylator id="1"><nazwa>Urząd Miasta</nazwa><adres>Rynek 1</adres>
<wspolrzedne><szerokosc>49,7843</szerokosc><dlugosc>22,7678</dlugosc></wspolrzedne></defibrylator>
<defibrylator id="2"><nazwa>Szpital</nazwa><adres>Monte Cassino 18</adres>
<wspolrzedne><szerokosc>49,7901</szerokosc><dlugosc>22,7555</dlugosc></wspolrzedne></defibrylator></defibrylatory>""".encode()
        recs, entry, notes = run(raw, "xml")
        self.assertEqual(len(recs), 2, entry)
        self.assertEqual(recs[1]["building_name"], "Szpital")

    def test_xlsx_title_rows_and_dates(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("brak openpyxl do zbudowania pliku testowego")
        from datetime import date
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Rejestr AED Gminy"])
        ws.append([])
        ws.append(["Miejsce", "Szerokość", "Długość", "Data przeglądu", "Status"])
        ws.append(["OSP", 50.06, 19.94, date(2026, 3, 1), "sprawny"])
        buf = io.BytesIO()
        wb.save(buf)
        recs, entry, notes = run(buf.getvalue(), "csv")  # zła deklaracja formatu: rozpoznajemy po zawartości
        self.assertEqual(len(recs), 1, entry)
        self.assertEqual((recs[0]["record_updated_at"], recs[0]["operational_status"]), ("2026-03-01", "SPRAWNY"))
        self.assertEqual(recs[0]["region"], "")  # bez kodu pocztowego i bez geokodera województwa nie zgadujemy
        recs, _, _ = run(buf.getvalue(), "xlsx", geo=FakeGeo())
        self.assertEqual(recs[0]["region"], "mazowieckie")  # z odwrotnego geokodowania (atrapa)


class OdwrotneTest(unittest.TestCase):
    def test_reverse_tries_axis_variants_and_remembers(self):
        import tempfile
        from rozwiazanie.scraping.geokod import Geokoder
        hit = {"results": {"1": {"city": "Marki", "street": "Józefa Piłsudskiego", "number": "95", "code": "05-270",
                                 "teryt": "1434041"}}}
        with tempfile.TemporaryDirectory() as tmp:
            geo = Geokoder(Path(tmp) / "g.json")
            asked = []

            def fake_get(params):
                asked.append(params["location"])
                return hit if params["srid"] == "2180" and params["location"].startswith("POINT(6") else {"results": None}
            geo._get = fake_get
            out = geo.odwrotne(52.326697, 21.107557)
            self.assertEqual(out, {"region": "mazowieckie", "city": "Marki", "street_address": "Józefa Piłsudskiego 95",
                                   "postal_code": "05-270"})
            self.assertEqual(len(asked), 3)            # 4326 lon/lat, 4326 lat/lon, 2180 x/y
            geo.odwrotne(52.32396, 21.098185)
            self.assertEqual(len(asked), 4)            # kolejny punkt: od razu wariant, który zadziałał
            self.assertEqual(geo.odwrotne(52.326697, 21.107557)["city"], "Marki")
            self.assertEqual(len(asked), 4)            # pamięć podręczna

    def test_blocked_service_is_not_cached_as_empty(self):
        import io as _io
        import tempfile
        from unittest import mock
        from rozwiazanie.scraping import geokod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(geokod, "PAUZA_S", 0), \
                mock.patch.object(geokod.urllib.request, "urlopen",
                                  return_value=_io.BytesIO(b'{"notice":"blocked for abuse"}')) as op:
            op.return_value.__enter__ = lambda self: self
            op.return_value.__exit__ = lambda self, *a: None
            geo = geokod.Geokoder(Path(tmp) / "g.json")
            self.assertIsNone(geo.odwrotne(52.326697, 21.107557))
            self.assertFalse(geo.online)
            self.assertEqual(geo.blokada, "blocked for abuse")
            self.assertEqual([k for k in geo.cache if not k.startswith("_")], [])  # brak adresu nie jest zapamiętany
            self.assertEqual(op.call_count, 1)       # po blokadzie nie pytamy dalej
            geo.zapisz()
            again = geokod.Geokoder(Path(tmp) / "g.json")   # kolejne uruchomienie: przerwa zapisana w pliku
            self.assertFalse(again.online)
            self.assertIn("wstrzymane do", again.blokada)
            self.assertIsNone(again.odwrotne(52.32396, 21.098185))
            self.assertEqual(op.call_count, 1)

    def test_query_limit_per_run(self):
        import tempfile
        from unittest import mock
        from rozwiazanie.scraping import geokod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(geokod, "PAUZA_S", 0), \
                mock.patch.object(geokod.urllib.request, "urlopen") as op:
            op.return_value.__enter__ = lambda self: self
            op.return_value.__exit__ = lambda self, *a: None
            op.return_value.read = lambda: b'{"results": null}'
            geo = geokod.Geokoder(Path(tmp) / "g.json", limit=2)
            geo.odwrotne(52.326697, 21.107557)
            self.assertEqual(op.call_count, 2)
            self.assertTrue(geo.limit_osiagniety)
            self.assertNotIn("r3:52.32670,21.10756", geo.cache)  # nie wszystkie warianty odpowiedziały
            self.assertIsNone(geo.adres("Fabryczna 2, Marki"))
            self.assertEqual(op.call_count, 2)

    def test_store_start_does_not_query_gugik(self):
        import tempfile
        from unittest import mock
        from rozwiazanie.backend.store import Store
        from rozwiazanie.scraping import danegov, geokod
        seen = {}

        def fake_load(src, progress=None, geokoder=None):
            seen["online"] = geokoder.online
            return [], []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(danegov, "load", fake_load), \
                mock.patch.object(geokod.Geokoder, "_get", side_effect=AssertionError("zapytanie do GUGiK")):
            Store(Path(tmp), {"danegov": {}}).refresh_danegov()
            self.assertFalse(seen["online"])
            Store(Path(tmp), {"danegov": {"geokodowanie": True}}).refresh_danegov()
            self.assertTrue(seen["online"])

    def test_coordinates_only_get_street_from_reverse(self):
        class Rev(FakeGeo):
            def odwrotne(self, lat, lon):
                return {"region": "mazowieckie", "city": "Marki", "street_address": "Fabryczna 2", "postal_code": "05-270"}
        raw = "Lp;Szerokosc;Dlugosc\n1;52,326697;21,107557\n".encode("utf-8")
        recs, entry, _ = run(raw, geo=Rev())
        r = recs[0]
        self.assertEqual((r["city"], r["street_address"], r["postal_code"]), ("Marki", "Fabryczna 2", "05-270"))
        self.assertEqual(entry["uwagi_wartosci"]["adres z odwrotnego geokodowania GUGiK"], 1)

    def test_puwg1992_roundtrip(self):
        e, n = standard.do_puwg1992(52.326697, 21.107557)
        lat, lon, uklad = standard.wspolrzedne(str(n), str(e))
        self.assertEqual((round(lat, 6), round(lon, 6), uklad), (52.326697, 21.107557, "PUWG 1992"))


class StandardTest(unittest.TestCase):
    def test_marki_addresses_only_geocoded(self):
        geo = FakeGeo()
        raw = "Lp;Miejsce;Adres\n1;Urząd Miasta Marki;Piłsudskiego 95\n2;Nieznane;\n".encode("utf-8")
        recs, entry, _ = run(raw, geo=geo)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r["latitude"], r["longitude"], r["city"], r["region"]), (52.3205, 21.1043, "Marki", "mazowieckie"))
        self.assertIn("Marki", geo.pytania[-1])                  # miasto z nazwy instytucji
        self.assertEqual(entry["odrzucone"], {"brak współrzędnych i adresu": 1})
        self.assertEqual(entry["uwagi_wartosci"]["geokodowanie GUGiK"], 1)

    def test_generic_description_is_not_exact_location(self):
        opis = ("Defibrylator AED (Automated External Defibrillator) to przenośne urządzenie medyczne, które zostało "
                "zaprojektowane w celu ratowania życia osobom z nagłym zatrzymaniem akcji serca (NZK).")
        raw = ("Lokalizacja;Opis lokalizacji;Szerokosc;Dlugosc\n"
               f"Dworzec PKP;{opis};49,7812;22,7751\nUrząd Miejski;{opis};49,7806;22,7771\n"
               f"Szkoła nr 1;{opis};49,7973;22,7582\n").encode("utf-8")
        recs, entry, _ = run(raw)
        self.assertEqual([r["exact_location"] for r in recs], ["", "", ""])
        self.assertEqual(recs[0]["building_name"], "Dworzec PKP")
        self.assertTrue(any("exact_location: pominięto" in u for u in entry.get("mapowanie", [])))
        # pojedynczy bardzo długi tekst w komórce też nie jest lokalizacją
        raw = f"Lokalizacja;Szerokosc;Dlugosc\n{opis * 3};49,7812;22,7751\nRatusz;49,7806;22,7771\n".encode("utf-8")
        recs, _, _ = run(raw)
        self.assertEqual([r["building_name"] for r in recs], ["", "Ratusz"])

    def test_generic_building_name_dropped(self):
        raw = "Nazwa;Lokalizacja;Szerokosc;Dlugosc\nDefibrylator;OSP Turaszówka;49,7188;21,7203\n".encode("utf-8")
        recs, _, _ = run(raw)
        self.assertEqual((recs[0]["building_name"], recs[0]["exact_location"]), ("", "OSP Turaszówka"))

    def test_coordinate_formats(self):
        self.assertEqual(standard.wspolrzedne("52,2297", "21,0122")[:2], (52.2297, 21.0122))
        self.assertEqual(standard.wspolrzedne("21.0122", "52.2297")[2], "zamienione lat/lon")
        lat, lon, uklad = standard.wspolrzedne("459309.4", "500000")  # PUWG 1992: (52°N, 19°E)
        self.assertEqual((round(lat, 4), round(lon, 4), uklad), (52.0, 19.0, "PUWG 1992"))
        self.assertAlmostEqual(standard.liczba("52°13'47\"N"), 52.2297, places=3)
        self.assertEqual(standard.para("POINT(21.01 52.23)"), (52.23, 21.01))
        self.assertEqual(standard.para("52,23, 21,01"), (52.23, 21.01))
        self.assertIsNone(standard.wspolrzedne("40.0", "2.0"))  # poza Polską

    def test_pair_column_detected_by_values(self):
        raw = "Obiekt;GPS;Dysponent\nApteka;52.2297, 21.0122;Gmina X\nKościół;52.2301, 21.0150;\n".encode()
        recs, entry, _ = run(raw)
        self.assertEqual(len(recs), 2)
        self.assertEqual(entry["kolumny"]["latitude+longitude"], "GPS")
        self.assertEqual(recs[1]["operator_name"], "Urząd Miasta Marki")  # brak dysponenta -> instytucja publikująca

    def test_dictionaries_and_values(self):
        self.assertEqual(standard.dostepnosc("Ogólnodostępny"), "24/7")
        self.assertEqual(standard.dostepnosc("", "Pn-Pt 8:00-16:00"), "GODZINY_OTWARCIA")
        self.assertEqual(standard.dostepnosc("tylko dla pracowników"), "TYLKO_PERSONEL")
        self.assertEqual(standard.ze_slownika("operational_status", "w naprawie"), "W_SERWISIE")
        self.assertEqual(standard.data_iso("31.12.2027"), "2027-12-31")
        self.assertEqual(standard.data_iso("03.2028"), "2028-03-01")
        self.assertEqual(standard.wojewodztwo("woj. Śląskie"), "śląskie")
        self.assertEqual(standard.wojewodztwo("1434035"), "mazowieckie")  # TERYT
        self.assertEqual(standard.kod_pocztowy("05270"), "05-270")
        self.assertIs(standard.logiczna("Na zewnątrz"), False)

    def test_bad_rows_do_not_break_import(self):
        raw = "lat;lon;nazwa\n52.1;21.0;A\nabc;def;B\n;;C\n52.2;21.1;D\n".encode()
        recs, entry, _ = run(raw)
        self.assertEqual([r["building_name"] for r in recs], ["A", "D"])
        self.assertEqual(sum(entry["odrzucone"].values()), 2)

    def test_new_column_name_via_json_synonym(self):
        cols = ["Pozycja N", "Pozycja E", "Gdzie wisi"]
        mapa = standard.mapuj_kolumny(cols, [{"Pozycja N": "52.1", "Pozycja E": "21.0", "Gdzie wisi": "hol"}])
        self.assertEqual((mapa["pola"]["latitude"], mapa["pola"]["longitude"]), ("Pozycja N", "Pozycja E"))
        self.assertIn("Gdzie wisi", mapa["nierozpoznane"])  # do dopisania jako synonim w common/aed_columns.json


if __name__ == "__main__":
    unittest.main()


class WidokiTest(unittest.TestCase):
    """Lista i Tabela muszą dostawać wiersz złotego standardu także dla rekordów z dawnej pamięci podręcznej."""

    def test_legacy_cache_record_has_standard_row(self):
        import tempfile
        from rozwiazanie.backend.schema import AED
        from rozwiazanie.backend.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp), {})
            r = AED("dgp-62093-1", 49.78121, 22.775094, "danegov", "https://dane.gov.pl/pl/dataset/4581/resource/62093",
                    "CC0 1.0", nazwa_obiektu="Dworzec PKP", adres="Plac Legionów 1, 37-700 Przemyśl",
                    extra={"zbior": "Lokalizacje AED w Przemyślu"})
            store.by_source["danegov"] = [r]
            store._rebuild()
            d = store.detail(0)
            st = d["standard"]
            self.assertEqual((st["latitude"], st["longitude"]), (49.78121, 22.775094))
            self.assertEqual((st["building_name"], st["city"], st["postal_code"]), ("Dworzec PKP", "Przemyśl", "37-700"))
            self.assertEqual(st["region"], "podkarpackie")
            self.assertEqual(st["data_source"], r.zrodlo_url)
            self.assertEqual(store.search(location="Przemyśl")["razem"], 1)

    def test_richer_format_of_same_dataset_wins(self):
        from unittest import mock
        from rozwiazanie.scraping import danegov as dg
        geo = json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [22.7765, 49.7838]}, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [22.7678, 49.7843]}, "properties": {}}]}).encode()
        csv_raw = "Lokalizacj;Adres_AED;Y;X\nDworzec PKP;Plac Legionów 1;49.7838;22.7765\nUrząd;Rynek 1;49.7843;22.7678\n".encode()
        ds = {"id": "4581", "attributes": {"title": "Lokalizacje AED w Przemyślu", "license_name": "CC0 1.0"}}
        res = {"data": [
            {"id": "62093", "attributes": {"title": "AED", "format": "geojson", "download_url": "https://x.invalid/a.geojson"}, "relationships": {}},
            {"id": "62095", "attributes": {"title": "AED", "format": "csv", "download_url": "https://x.invalid/a.csv"}, "relationships": {}}],
            "links": {}}

        def get_json(url, timeout=25):
            if "/datasets?q=" in url:
                return {"data": [ds], "links": {}}
            return res

        with mock.patch.object(dg, "_get_json", side_effect=get_json), \
                mock.patch.object(dg, "_get_bytes", side_effect=lambda u, timeout=40: geo if u.endswith("geojson") else csv_raw):
            recs, report = dg.load({"queries": ["defibrylator"]})
        self.assertEqual(len(recs), 2)  # ten sam zestaw liczony raz
        self.assertEqual(sorted(r.nazwa_obiektu for r in recs), ["Dworzec PKP", "Urząd"])  # wygrał CSV z nazwami
        self.assertIn("mniej wypełnionych pól", report[0]["pominieto"])
        self.assertEqual(recs[0].extra["std"]["street_address"], "Plac Legionów 1")  # „Adres_AED” po fragmencie nazwy
