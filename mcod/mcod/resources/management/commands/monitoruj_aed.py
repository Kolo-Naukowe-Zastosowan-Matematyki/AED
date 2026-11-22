import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections


class Command(BaseCommand):
    help = "Co minutę sprawdza opublikowane zasoby dostawców i aktualizuje wykaz AED."

    def handle(self, **options):
        while True:
            close_old_connections()
            try:
                call_command("publikuj_aed", watch=True)
            except Exception:
                logging.getLogger("mcod").exception("Aktualizacja wykazu AED nie powiodła się")
            time.sleep(60)

