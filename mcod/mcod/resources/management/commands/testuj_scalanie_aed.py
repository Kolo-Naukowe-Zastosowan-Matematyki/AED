"""Sprawdza podmianę zawartości i wycofanie źródła w wycofywanej transakcji."""
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from .publikuj_aed import uid


class Command(BaseCommand):
    def handle(self, **options):
        from integracja.wykaz import collect, record_publication
        from rozwiazanie.backend.store import Store

        store = Store(Path("/opt/aed"), {})
        with transaction.atomic():
            sources = apps.get_model("resources", "Resource").objects.filter(contains_aed_registry=True)
            initial, report = collect(store, uid)
            if len({row["dostawca"] for row in report}) < 2:
                raise CommandError("Oczekiwano co najmniej dwóch dostawców.")
            resource = apps.get_model("resources", "Resource").objects.get(uuid=uid("wykaz.csv"))
            snapshots = apps.get_model("resources", "AedPublication").objects.filter(resource=resource)
            source = sources.order_by("pk").first()
            main = source.files.get(is_main=True)
            count = len(initial)
            with tempfile.NamedTemporaryFile(dir=settings.RESOURCES_MEDIA_ROOT, suffix=".csv") as temp:
                temp.write("szerokość geograficzna;długość geograficzna;miejscowość;building_name\n52.22;21.01;Warszawa;TEST SCALANIA\n".encode())
                temp.flush()
                type(main).objects.filter(pk=main.pk).update(file=Path(temp.name).name)
                changed, _ = collect(store, uid)
                if sum(x.nazwa_obiektu == "TEST SCALANIA" for x in changed) != 1:
                    raise CommandError("Podmiana pliku nie zmieniła wykazu.")
                record_publication(resource, store, "a" * 64)
                last = snapshots.latest("pk")
                if last.total != len(changed) or sum(area["count"] for area in last.areas) != last.total:
                    raise CommandError("Suma obszarów różni się od liczby AED w wersji.")
                record_publication(resource, store, "a" * 64)
                if snapshots.latest("pk").pk != last.pk:
                    raise CommandError("Ponowienie publikacji utworzyło zbędny pomiar.")
                sources.filter(pk=source.pk).update(contains_aed_registry=False)
                remaining, _ = collect(store, uid)
                if len(remaining) != len(changed)-1 or any(x.nazwa_obiektu == "TEST SCALANIA" for x in remaining):
                    raise CommandError("Wycofany zasób nadal należy do wykazu.")
                record_publication(resource, store, "b" * 64)
                if snapshots.latest("pk").total != last.total - 1:
                    raise CommandError("Historia nie odzwierciedla wycofania źródła.")
            transaction.set_rollback(True)
        self.stdout.write("OK: %d dostawców, %d rekordów; podmiana pliku i wycofanie źródła potwierdzone." %
                          (len({row["dostawca"] for row in report}), count))

