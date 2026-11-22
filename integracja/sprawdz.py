"""Test odbiorczy przez bramę HTTPS. Uruchom w kontenerze rejestr po publikacji."""
import csv
import io
import json
from pathlib import Path
import ssl
import time
from urllib.error import URLError
from urllib.request import urlopen

import django

from rozwiazanie.backend.columns import ROLE_PUBLIC, columns_for


def main():
    django.setup()
    from django.apps import apps
    from mcod.resources.management.commands.publikuj_aed import uid

    context = ssl.create_default_context(cafile="/usr/src/mcod_backend/mcod.local.pem")

    def get(path):
        with urlopen("https://mcod.local" + path, context=context, timeout=12) as response:
            return response.read()

    dataset = apps.get_model("datasets", "Dataset").objects.get(uuid=uid("wykaz"))
    resource = apps.get_model("resources", "Resource").objects.get(uuid=uid("wykaz.csv"))
    errors = (AssertionError, ValueError, KeyError, OSError, URLError)
    for attempt in range(60):
        try:
            resources = json.loads(get("/api/1.4/datasets/%d/resources" % dataset.pk))["data"]
            assert str(resource.pk) in {str(obj["id"]) for obj in resources}, "Lista zasobów w API"
            template = apps.get_model("resources", "Resource").objects.get(uuid=uid("Wzorzec-AED.xlsx"))
            assert str(template.pk) in {str(obj["id"]) for obj in resources}, "Wzorzec XLSX na karcie zbioru"
            assert get("/api/1.4/resources/%d/file" % template.pk) == Path("/opt/aed/Wzorzec-AED.xlsx").read_bytes(), "Treść wzorca XLSX"
            result = json.loads(get("/api/1.4/search?q=AED&per_page=100"))["data"]
            assert any(obj.get("attributes", {}).get("title", "").replace("<mark>", "").replace("</mark>", "")
                       == dataset.title for obj in result), "Zbiór nie pojawił się jeszcze w indeksie"
            content = get("/api/1.4/resources/%d/file" % resource.pk)
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
            assert len(rows) > 1, "Pusty plik opublikowanego zasobu"
            assert rows[0] == [c["nazwa"] for c in columns_for(ROLE_PUBLIC)], "Polskie publiczne nagłówki CSV"
            assert type(resource).objects.filter(pk=resource.pk, has_table=True,
                                                 data_tasks_last_status="SUCCESS").exists(), "Walidacja tabeli mcod"
            table = json.loads(get("/api/1.4/resources/%d/data?per_page=1" % resource.pk))
            assert table["data"] and table["meta"]["count"] == len(rows) - 1, "Widok tabelaryczny mcod"
            fields = table["meta"]["data_schema"]["fields"]
            headers = table["meta"]["headers_map"]
            labels = {headers[field["name"]]: field.get("description") for field in fields}
            assert labels == {c["nazwa"]: c["nazwa"].rstrip("?") for c in columns_for(ROLE_PUBLIC)}, "Nagłówki wykazu AED"
            statistics = json.loads(get("/aed-api/wykresy/%d" % resource.pk))
            assert sum(area["count"] for area in statistics["areas"]) == statistics["total"] == len(rows) - 1
            assert statistics["history"][-1]["total"] == statistics["total"], "Historia publikacji"
            assert b"Rejestr AED" in get("/"), "Brak strony rejestru"
            assert json.loads(get("/aed-api/stats"))["aed_razem"] > 0, "Pusty rejestr"
            print("OK — zbiór %d, zasób %d, %d wierszy publicznego CSV." %
                  (dataset.pk, resource.pk, len(rows)-1))
            return
        except errors as exc:
            if attempt == 59:
                raise
            if attempt % 10 == 0:
                print("Oczekiwanie na portal i indeksację:", exc, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()

