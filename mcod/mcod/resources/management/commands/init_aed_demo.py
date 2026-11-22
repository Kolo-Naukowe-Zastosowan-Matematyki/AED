"""Dokończ inicjalizację po przerwaniu pomiędzy załadowaniem fixture a zapisem etapu."""
import json
from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def handle(self, **options):
        call_command("migrate")
        fixture = Path(apps.get_app_config("core").path) / "fixtures" / "basic_data.json"
        data = json.loads(fixture.read_text(encoding="utf-8"))
        if all(apps.get_model(row["model"])._base_manager.filter(pk=row["pk"]).exists() for row in data):
            self.stdout.write("Dane początkowe mcod są już w bazie.")
            return
        call_command("init_mcod_db")

