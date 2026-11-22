"""Test HTTP z Django 2.2.9; uruchamiany także w docelowym obrazie mcod."""
import os
import unittest
from pathlib import Path

import django
from django.conf import settings

if not settings.configured and not os.environ.get("DJANGO_SETTINGS_MODULE"):
    settings.configure(SECRET_KEY="test", ROOT_URLCONF="integracja.urls",
                       INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions"],
                       DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
                       MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware",
                                   "django.contrib.auth.middleware.AuthenticationMiddleware",
                                   "django.middleware.csrf.CsrfViewMiddleware"],
                       SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
                       ALLOWED_HOSTS=["testserver"], API_TOKEN_COOKIE_NAME="local_apiauthtoken")
os.environ.setdefault("AED_OFFLINE", "1")
django.setup()

from django.test import Client
from rozwiazanie.backend.columns import PROTECTED_FIELDS


class RegistryHttpTest(unittest.TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_registry_and_exports(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(self.client.get("/").content, (root / "rozwiazanie/frontend/index.html").read_bytes())
        for path in ["/mapa", "/tabela", "/aed-api/export.csv", "/aed-api/export.xlsx", "/aed-api/export.geojson"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        result = self.client.get("/aed-api/search", {"miejsce": "Legionowo"}).json()
        self.assertGreater(result["razem"], 0)
        self.assertFalse(set(PROTECTED_FIELDS).intersection(result["wyniki"][0]))

    def test_portal_login_and_csrf(self):
        self.assertEqual(self.client.get("/aed-api/auth/zaloguj")["Location"], "/pl/user/login?redirect=/rejestr")
        self.assertEqual(self.client.post("/aed-api/auth/logout").status_code, 403)
        self.client.get("/")
        response = self.client.post("/aed-api/auth/logout", HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value)
        self.assertEqual(response.json()["rola"], "publiczny")

