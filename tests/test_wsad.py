"""Testy wsadu AED: tabela kolumn chronionych, filtr kolumn wg roli i logowanie administratora.

Uruchomienie:  python -m unittest discover -s tests -v
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from mcod_wsad import aed_constants as wsad  # noqa: E402
from rozwiazanie.backend import columns  # noqa: E402
from rozwiazanie.backend.auth import Auth  # noqa: E402


class ColumnsTableTest(unittest.TestCase):
    def test_json_and_mcod_constants_match(self):
        js = [(c["pole"], c["nazwa"], c["typ"], c["wymagana"], c["chroniona"]) for c in columns.COLUMNS]
        self.assertEqual(js, [tuple(c) for c in wsad.AED_COLUMNS])

    def test_main_columns_have_no_protected(self):
        self.assertFalse(set(wsad.MAIN_AED_COLUMNS) & set(wsad.AED_PROTECTED_COLUMNS))

    def test_natalia_columns_and_protected(self):
        # złoty standard (schemat Oliwii): 20 kolumn, nagłówek CSV w tej kolejności
        self.assertEqual(";".join(c["pole"] for c in columns.COLUMNS),
                         "aed_sn;latitude;longitude;region;city;postal_code;street_address;is_indoor;building_name;"
                         "exact_location;availability_type;opening_hours;is_locked;operational_status;operator_name;"
                         "pad_expiration_date;battery_expiration_date;record_updated_at;data_source;possible_duplicate")
        self.assertEqual(len(columns.PUBLIC_FIELDS), 16)
        self.assertEqual(columns.PROTECTED_FIELDS, ["aed_sn", "pad_expiration_date", "battery_expiration_date",
                                                    "possible_duplicate"])


class ApplyRoleTest(unittest.TestCase):
    class FakeProtected:
        demo = True

        def get(self, id_aed):
            return {f: f"wartosc-{f}" for f in columns.PROTECTED_FIELDS}

    def test_public_gets_no_protected(self):
        item = {"id_aed": "x", "adres": "A", "aed_sn": "NIE-POKAZUJ"}
        out = columns.apply_role(item, columns.ROLE_PUBLIC, self.FakeProtected())
        self.assertNotIn("aed_sn", out)
        self.assertNotIn("_chronione", out)
        self.assertEqual(out["adres"], "A")

    def test_admin_gets_protected(self):
        out = columns.apply_role({"id_aed": "x"}, columns.ROLE_ADMIN, self.FakeProtected())
        self.assertEqual(out["aed_sn"], "wartosc-aed_sn")
        self.assertEqual(out["_chronione"], columns.PROTECTED_FIELDS)


class AuthTest(unittest.TestCase):
    def test_role_from_portal_account(self):
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"system_role": "admin"}}}), "admin")
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"aed_rola": "sluzby_aed"}}}), "admin")
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"system_role": "editor"}}}), "publiczny")
        self.assertEqual(Auth.role_from_account({}), "publiczny")

    def test_token_from_portal_cookie(self):
        self.assertEqual(Auth.token_from({"Cookie": "x=1; local_apiauthtoken=abc"}), "abc")
        self.assertEqual(Auth.token_from({"Authorization": "Bearer xyz"}), "xyz")
        self.assertEqual(Auth.token_from({"Cookie": "aed_token=stary"}), "")  # dawne hasło serwisu już nie działa
        self.assertEqual(Auth().role({"Cookie": "local_apiauthtoken=abc"}), "publiczny")  # bez portalu: publiczny


class HttpEndToEndTest(unittest.TestCase):
    """Makieta portalu + serwis offline: logowanie kontem demo w portalu, rola w serwisie z /api/auth/user."""

    @classmethod
    def setUpClass(cls):
        from common.http import Server
        from portal.backend.app import setup as setup_portal
        from rozwiazanie.backend.app import setup
        handler = setup(BASE, {}, offline=True)
        cls.server = Server(("127.0.0.1", 0), handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/aed-api"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.portal = Server(("127.0.0.1", 0), setup_portal(BASE, {}, cls.url, cls.url.rsplit("/", 1)[0]))
        cls.portal_url = f"http://127.0.0.1:{cls.portal.server_address[1]}"
        threading.Thread(target=cls.portal.serve_forever, daemon=True).start()
        handler.auth.api_url = cls.portal_url + "/api"
        handler.auth.login_url = cls.portal_url + "/pl/user/login?redirect=/pl/aed-powrot"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.portal.shutdown()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    def login(self, email, password="demo-aed"):
        body = {"data": {"type": "user", "attributes": {"email": email, "password": password}}}
        req = urllib.request.Request(self.portal_url + "/api/auth/login", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return "local_apiauthtoken=" + json.loads(r.read().decode())["data"]["attributes"]["token"]

    def test_public_vs_services(self):
        pub = self.get("/search?limit=100")
        self.assertEqual(pub["rola"], "publiczny")
        for rec in pub["wyniki"]:
            self.assertFalse(set(rec) & set(columns.PROTECTED_FIELDS))
        self.assertTrue(all(not c["chroniona"] for c in self.get("/kolumny")["kolumny"]))

        with self.assertRaises(urllib.error.HTTPError) as err:
            self.login("sluzby@aed.demo", "zle-haslo")
        self.assertEqual(err.exception.code, 401)

        cookie = self.login("obywatel@aed.demo")  # zwykłe konto: zalogowany, ale bez kolumn chronionych
        acc = self.get("/auth/rola", {"Cookie": cookie})
        self.assertEqual((acc["rola"], acc["uzytkownik"]), ("publiczny", "Jan Kowalski (demo)"))

        cookie = self.login("sluzby@aed.demo")
        self.assertEqual(self.get("/auth/rola", {"Cookie": cookie})["rola"], "admin")
        adm = self.get("/search?limit=100", {"Cookie": cookie})
        self.assertEqual(adm["rola"], "admin")
        if adm["wyniki"]:
            self.assertTrue(set(columns.PROVIDED_PROTECTED_FIELDS) <= set(adm["wyniki"][0]))
        # zasób dla portalu dane.gov.pl zostaje publiczny także dla służb
        reg = self.get("/rejestr.json", {"Cookie": cookie})
        for rec in reg["rekordy"]:
            self.assertFalse(set(rec) & set(columns.PROTECTED_FIELDS))

        req = urllib.request.Request(self.url + "/auth/logout", data=b"", method="POST", headers={"Cookie": cookie})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(any("local_apiauthtoken=;" in c for c in r.headers.get_all("Set-Cookie")))
        self.assertEqual(self.get("/auth/rola", {"Cookie": cookie})["rola"], "publiczny")  # sesja w portalu zamknięta

    def test_login_link_goes_to_portal(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as err:
            opener.open(self.url + "/auth/zaloguj", timeout=5)
        self.assertEqual(err.exception.code, 302)
        self.assertTrue(err.exception.headers["Location"].endswith("/pl/user/login?redirect=/pl/aed-powrot"))


if __name__ == "__main__":
    unittest.main()
