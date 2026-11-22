"""Źródłem agregatu są opublikowane pliki dostawców w tej instancji mcod."""
import csv
import io
import json
import secrets
from collections import Counter, defaultdict
from pathlib import Path

from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from django.core.files.uploadedfile import SimpleUploadedFile

from rozwiazanie.backend.columns import PUBLIC_FIELDS
from rozwiazanie.scraping.czytniki import czytaj
from rozwiazanie.scraping.danegov import standaryzuj_wiersze


def seed_sources(uid, editor, credentials):
    """Jednorazowo załaduj cztery lokalne kopie publicznych źródeł wraz z pochodzeniem."""
    data = json.loads(Path("/opt/aed/przyklady/danegov.json").read_bytes())
    batches = defaultdict(list)
    for row in data["records"]:
        batches[row["zrodlo_url"]].append(row)
    Org = apps.get_model("organizations", "Organization")
    Dataset = apps.get_model("datasets", "Dataset")
    Resource = apps.get_model("resources", "Resource")
    File = apps.get_model("resources", "ResourceFile")
    for url, rows in batches.items():
        first = rows[0]
        org, _ = Org.objects.get_or_create(uuid=uid("org/" + url), defaults={
            "title": first["extra"]["std"]["city"] + " – dostawca demonstracyjny",
            "institution_type": "local", "status": "published"})
        email = slugify(first["extra"]["std"]["city"]) + "@aed.demo"
        user, created = get_user_model().objects.get_or_create(email=email, defaults={
            "fullname": "Redaktor – " + first["extra"]["std"]["city"], "state": "active",
            "is_active": True, "is_staff": True, "phone": "000000000", "email_confirmed": timezone.now()})
        if created:
            password = secrets.token_urlsafe(16)
            user.set_password(password)
            user.save()
            credentials.append("%s %s\n" % (email, password))
        user.organizations.add(org)
        editor.organizations.remove(org)
        dataset, _ = Dataset.objects.get_or_create(uuid=uid("ds/" + url), defaults={
            "organization": org, "title": first["extra"]["zbior"], "url": url,
            "notes": "Lokalna kopia demonstracyjna wykazu z " + url, "status": "published",
            "license_chosen": Dataset.LICENSE_CC_BY if first["licencja"] == "CC BY 4.0" else Dataset.LICENSE_CC0})
        resource, created = Resource.objects.get_or_create(uuid=uid("src/" + url), defaults={
            "dataset": dataset, "title": first["extra"]["zbior"], "contains_aed_registry": True,
            "status": "published", "data_date": data["fetched_at"][:10], "created_by": user,
            "has_dynamic_data": False, "has_high_value_data": False,
            "has_high_value_data_from_ec_list": False, "has_research_data": False})
        if created:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=PUBLIC_FIELDS, extrasaction="ignore", delimiter=";")
            writer.writeheader()
            writer.writerows(row["extra"]["std"] for row in rows)
            File.objects.create(resource=resource, is_main=True, file=SimpleUploadedFile(
                "wykaz-%d.csv" % resource.pk, buf.getvalue().encode("utf-8-sig"), content_type="text/csv"))


def collect(store, uid):
    Resource = apps.get_model("resources", "Resource")
    resources = Resource.objects.filter(contains_aed_registry=True, status="published", dataset__status="published",
        dataset__organization__status="published", is_removed=False, dataset__is_removed=False,
        dataset__organization__is_removed=False, is_permanently_removed=False,
        dataset__is_permanently_removed=False, dataset__organization__is_permanently_removed=False).exclude(dataset__uuid=uid("wykaz")).select_related(
        "dataset__organization").order_by("pk")
    records, report = [], []
    for resource in resources:
        ds = resource.dataset
        org = ds.organization
        source = "https://mcod.local/pl/dataset/%s/resource/%s" % (ds.pk, resource.pk)
        info = {"zbior": ds.title, "zasob": resource.title, "dostawca": org.title, "url": source}
        report.append(info)
        if ds.license_code not in (ds.LICENSE_CC0, ds.LICENSE_CC_BY) or ds.license_condition_custom_description:
            info.update(rekordy=0, powod="Wymaga indywidualnego uzgodnienia warunków.")
            continue
        file = resource.files.filter(is_main=True).first()
        if not file or not file.file:
            info.update(rekordy=0, powod="Oczekiwanie na plik źródłowy.")
            continue
        with file.file.open("rb") as stream:
            rows, notes = czytaj(stream.read(), Path(file.file.name).suffix.lstrip("."))
        if not rows:
            info.update(rekordy=0, powod="Brak tabeli w pliku.", odczyt=notes)
            continue
        original = ds.url if ds.url and resource.uuid == uid("src/" + ds.url) else ""
        rid = original.rsplit("/", 1)[-1] if original else "lokalny-%d" % resource.pk
        ctx = {"resource_url": source, "dataset_title": ds.title, "license": ds.license_name,
               "zasob_url": original or source, "zmodyfikowano": str(resource.data_date or "")}
        points = standaryzuj_wiersze(rows, {}, ctx, info, rid=rid)
        info.pop("odrzucone_przyklady", None)
        if not points:
            info["powod"] = "Brak poprawnych lokalizacji."
        for point in points:
            point.extra.update(dostawca=org.title, oryginal=original)
        records.extend(points)
        info["rekordy"] = len(points)
    store.by_source["danegov"] = records
    store._rebuild()
    return records, report



def record_publication(resource, store, checksum):
    """Wywoływane pod blokadą transakcyjną publikatora, także dla pierwszego pomiaru istniejącego zasobu."""
    Publication = apps.get_model("resources", "AedPublication")
    counts = Counter(
        (row.get("region") or "", area.get("powiat") or "", area.get("gmina") or "")
        for row, area in zip(store.std, store.obszary)
    )
    areas = [dict(region=r, powiat=p, gmina=g, count=n) for (r, p, g), n in sorted(counts.items())]
    last = Publication.objects.filter(resource=resource).order_by("-pk").first()
    if last is None or last.csv_sha256 != checksum or last.areas != areas:
        Publication.objects.create(resource=resource, total=len(store.records), areas=areas, csv_sha256=checksum)
