"""Publikacja publicznej migawki przez dostawcę w lokalnej instancji mcod."""
import csv
import hashlib
import io
import json
import os
import secrets
from datetime import date
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from mcod.core.api.search.tasks import update_related_task
from mcod.resources.aed import uid


class Command(BaseCommand):
    help = "Publikuje lub aktualizuje wykaz AED w instancji konkursowej."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--demo", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        from rozwiazanie.backend.store import Store

        root = Path("/opt/aed")
        # Dwie równoległe publikacje dotyczą tej samej migawki katalogowej.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7941210])

        store = Store(root, {})

        org_model = apps.get_model("organizations", "Organization")
        dataset_model = apps.get_model("datasets", "Dataset")
        resource_model = apps.get_model("resources", "Resource")
        org, _ = org_model.objects.get_or_create(
            uuid=uid("dostawca"), defaults={"title": "Zespół rejestru AED (dostawca demonstracyjny)",
                                           "status": "published", "institution_type": "private"})
        Users = get_user_model()
        group, _ = Group.objects.get_or_create(name="Służby AED")
        credentials = []
        for email, name, staff in [
            ("redaktor@aed.demo", "Redaktor dostawcy AED", True),
            ("sluzby@aed.demo", "Służby AED", False),
            ("obywatel@aed.demo", "Obywatel", False),
        ]:
            user, created = Users.objects.get_or_create(email=email, defaults={
                "fullname": name, "state": "active", "is_active": True, "is_staff": staff,
                "email_confirmed": timezone.now(), "phone": "000000000" if staff else ""})
            if created:
                password = secrets.token_urlsafe(16)
                user.set_password(password)
                user.save()
                credentials.append("%s %s\n" % (email, password))
            if email == "sluzby@aed.demo":
                user.groups.add(group)
            if staff:
                user.organizations.add(org)
                editor = user

        from integracja.wykaz import collect, record_publication, seed_sources
        if options["demo"]:
            seed_sources(uid, editor, credentials)
        if credentials:
            def write_accounts():
                filename = str(root / "data" / "konta-demo.txt")
                with os.fdopen(os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as f:
                    f.writelines(credentials)
                self.stdout.write("Hasła kont demonstracyjnych zapisano w ../.raed-lokalne/dane/konta-demo.txt.")
            transaction.on_commit(write_accounts)

        records, report = collect(store, uid)
        cache = root / "data/cache/danegov.json"
        previous = json.loads(cache.read_bytes()) if cache.exists() else {}
        changed = (previous.get("report") != report or previous.get("records") !=
                   [dict(r.to_dict(), extra=r.extra) for r in records])
        store.status["danegov"] = {"pobrano": (previous.get("fetched_at") or date.today().isoformat())[:10]}
        public_csv = store.export_csv()
        digest = hashlib.sha256(public_csv).hexdigest()
        changed = changed or previous.get("csv_sha256") != digest
        if not changed and options["watch"]:
            existing = resource_model.objects.filter(uuid=uid("wykaz.csv")).first()
            if existing:
                record_publication(existing, store, digest)
                return
        if changed:
            transaction.on_commit(lambda: store._save_cache("danegov", records, report, csv_sha256=digest))
        dataset, _ = dataset_model.objects.get_or_create(uuid=uid("wykaz"), defaults={
            "organization": org, "title": "System Ewidencji Zasobów AED – wykaz defibrylatorów",
            "notes": "Publiczna agregacja lokalnych wykazów. Pochodzenie i warunki wykorzystania "
                     "podaje zasób Źródła. Brak godzin nie potwierdza dostępności urządzenia.",
            "license_condition_source": True, "license_chosen": dataset_model.LICENSE_CC_BY,
            "created_by": editor, "modified_by": editor, "status": "published"})
        for name in ["AED", "defibrylator", "wykaz AED"]:
            tag, _ = apps.get_model("tags", "Tag").objects.get_or_create(name=name, language="pl")
            dataset.tags.add(tag)
        health = apps.get_model("categories", "Category").objects.get(title="Zdrowie")
        dataset.categories.add(health)
        if not options["watch"]:
            source_ids = []
            for source in dataset_model.objects.filter(resources__contains_aed_registry=True).distinct():
                if source.url and source.uuid == uid("ds/" + source.url):
                    if not source.categories.exists():
                        source.categories.add(health)
                    source_ids.append(source.pk)
            if source_ids:
                update_related_task.apply_async_on_commit(args=("datasets", "Dataset", source_ids))
        stamp = date.today() if changed or not previous.get("fetched_at") else date.fromisoformat(previous["fetched_at"][:10])
        store.status["danegov"] = {"pobrano": stamp.isoformat()}
        defaults = {"dataset": dataset, "status": "published", "data_date": stamp,
                    "created_by": editor, "modified_by": editor,
                    "has_dynamic_data": False, "has_high_value_data": False,
                    "has_high_value_data_from_ec_list": False, "has_research_data": False}
        sources = io.StringIO()
        writer = csv.writer(sources, delimiter=";")
        writer.writerow(["ID AED", "Szerokość", "Długość", "Zbiór źródłowy", "Adres zasobu", "Warunki wykorzystania", "Dostawca", "Oryginał"])
        for row in store.records:
            writer.writerow([row.id_aed, row.szerokosc, row.dlugosc, row.extra.get("zbior", ""), row.zrodlo_url, row.licencja, row.extra["dostawca"], row.extra["oryginal"]])
        files = [
            ("wykaz.csv", "Wykaz AED", public_csv, "text/csv"),
            ("zrodla.csv", "Źródła i warunki wykorzystania wykazów AED", sources.getvalue().encode("utf-8-sig"), "text/csv"),
        ]
        files.append(("Wzorzec-AED.xlsx", "Wzorcowy zakres danych AED – szablon XLSX",
                      (root / "Wzorzec-AED.xlsx").read_bytes(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        File = apps.get_model("resources", "ResourceFile")
        for filename, title, body, mime in files:
            resource, _ = resource_model.objects.get_or_create(uuid=uid(filename), defaults=dict(defaults, title=title, show_tabular_view=filename.endswith(".csv")))
            if filename == "wykaz.csv":
                record_publication(resource, store, digest)
            main = File.objects.filter(resource=resource, is_main=True).first()
            if main and main.file:
                with main.file.open("rb") as existing:
                    if existing.read() == body:
                        if resource.show_tabular_view and resource.data_tasks_last_status == "FAILURE" and not options["watch"]:
                            resource.revalidate_tabular_data(apply_on_commit=True)
                        continue
            if main is None:
                main = File(resource=resource, is_main=True)
            main.file = SimpleUploadedFile(filename, body, content_type=mime)
            resource.data_date = stamp
            resource.save()
            main.save()
        resource_model.objects.get_or_create(uuid=uid("strona"), defaults=dict(
            defaults, title="Rejestr AED – tabela i mapa", type="website", link="https://mcod.local/"))
        self.stdout.write("Zbiór: https://mcod.local/pl/dataset/%s,%s" % (dataset.pk, dataset.slug))
        self.stdout.write("API: https://api.mcod.local/1.4/datasets/%s/resources" % dataset.pk)

