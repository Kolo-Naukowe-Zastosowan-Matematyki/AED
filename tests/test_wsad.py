"""Testy wsadu AED: tabela kolumn chronionych, filtr kolumn wg roli i logowanie administratora.

Uruchomienie:  python -m unittest discover -s tests -v
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.parse
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
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"aed_rola": "sluzby_aed"}}}), "sluzby_aed")
        self.assertEqual(Auth.role_from_account({"data": {"attributes": {"system_role": "editor"}}}), "publiczny")
        self.assertEqual(Auth.role_from_account({}), "publiczny")

    def test_token_from_portal_cookie(self):
        self.assertEqual(Auth.token_from({"Cookie": "x=1; local_apiauthtoken=abc"}), "abc")
        self.assertEqual(Auth.token_from({"Authorization": "Bearer xyz"}), "xyz")
        self.assertEqual(Auth.token_from({"Cookie": "aed_token=stary"}), "")  # dawne hasło serwisu już nie działa
        self.assertEqual(Auth().role({"Cookie": "local_apiauthtoken=abc"}), "publiczny")  # bez portalu: publiczny


if __name__ == "__main__":
    unittest.main()
