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
        self.assertEqual(columns.PUBLIC_FIELDS[:2], ["szerokosc_geograficzna", "dlugosc_geograficzna"])
        self.assertEqual(columns.PROTECTED_FIELDS, ["numer_seryjny_aed", "data_waznosci_elektrod",
                                                    "data_waznosci_baterii", "osoba_kontaktowa", "telefon_kontaktowy"])


class ApplyRoleTest(unittest.TestCase):
    class FakeProtected:
        demo = True

        def get(self, id_aed):
            return {f: f"wartosc-{f}" for f in columns.PROTECTED_FIELDS}

    def test_public_gets_no_protected(self):
        item = {"id_aed": "x", "adres": "A", "numer_seryjny_aed": "NIE-POKAZUJ"}
        out = columns.apply_role(item, columns.ROLE_PUBLIC, self.FakeProtected())
        self.assertNotIn("numer_seryjny_aed", out)
        self.assertNotIn("_chronione", out)
        self.assertEqual(out["adres"], "A")

    def test_admin_gets_protected(self):
        out = columns.apply_role({"id_aed": "x"}, columns.ROLE_ADMIN, self.FakeProtected())
        self.assertEqual(out["numer_seryjny_aed"], "wartosc-numer_seryjny_aed")
        self.assertEqual(out["_chronione"], columns.PROTECTED_FIELDS)


class AuthTest(unittest.TestCase):
    def test_role_from_mcod_account(self):
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"system_role": "admin"}}}), "admin")
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"system_role": "editor"}}}), "publiczny")
        self.assertEqual(Auth.role_from_account({}), "publiczny")

    def test_demo_login(self):
        auth = Auth({"haslo_demo": "tajne"})
        self.assertIsNone(auth.login("zle"))
        token = auth.login("tajne")
        self.assertEqual(auth.role({"Cookie": f"aed_token={token}"}), "admin")
        self.assertEqual(auth.role({"Authorization": f"Bearer {token}"}), "admin")
        self.assertEqual(auth.role({"Cookie": "aed_token=cudzy"}), "publiczny")
        auth.logout({"Cookie": f"aed_token={token}"})
        self.assertEqual(auth.role({"Cookie": f"aed_token={token}"}), "publiczny")


class HttpEndToEndTest(unittest.TestCase):
    """Serwis offline na losowym porcie: anonim nie dostaje kolumn chronionych, admin dostaje."""

    @classmethod
    def setUpClass(cls):
        from common.http import Server
        from rozwiazanie.backend.app import setup
        handler = setup(BASE, {"auth": {"haslo_demo": "test-haslo"}}, offline=True)
        cls.server = Server(("127.0.0.1", 0), handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/aed-api"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())

    def login(self, password):
        req = urllib.request.Request(self.url + "/auth/login", data=json.dumps({"haslo": password}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.headers["Set-Cookie"].split(";")[0]

    def test_public_vs_admin(self):
        pub = self.get("/search?limit=100")
        self.assertEqual(pub["rola"], "publiczny")
        for rec in pub["wyniki"]:
            self.assertFalse(set(rec) & set(columns.PROTECTED_FIELDS))
        self.assertTrue(all(not c["chroniona"] for c in self.get("/kolumny")["kolumny"]))

        with self.assertRaises(urllib.error.HTTPError) as err:
            self.login("zle-haslo")
        self.assertEqual(err.exception.code, 401)

        cookie = self.login("test-haslo")
        adm = self.get("/search?limit=100", {"Cookie": cookie})
        self.assertEqual(adm["rola"], "admin")
        if adm["wyniki"]:
            self.assertTrue(set(columns.PROTECTED_FIELDS) <= set(adm["wyniki"][0]))
        # zasób dla portalu dane.gov.pl zostaje publiczny także dla administratora
        reg = self.get("/rejestr.json", {"Cookie": cookie})
        for rec in reg["rekordy"]:
            self.assertFalse(set(rec) & set(columns.PROTECTED_FIELDS))


if __name__ == "__main__":
    unittest.main()
