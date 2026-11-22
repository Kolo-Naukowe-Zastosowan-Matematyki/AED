"""Pokazuje różnicę opisów kolumn wykazu AED: API mcod vs columns_for(ROLE_PUBLIC)."""
import json
import ssl
from urllib.request import urlopen

import django

from rozwiazanie.backend.columns import ROLE_PUBLIC, columns_for

django.setup()
from django.apps import apps  # noqa: E402
from mcod.resources.management.commands.publikuj_aed import uid  # noqa: E402

ctx = ssl.create_default_context(cafile="/usr/src/mcod_backend/mcod.local.pem")
r = apps.get_model("resources", "Resource").objects.get(uuid=uid("wykaz.csv"))
print("zasob", r.pk, "uuid", r.uuid, "has_table", r.has_table, "status", r.data_tasks_last_status)
t = json.loads(urlopen("https://mcod.local/api/1.4/resources/%d/data?per_page=1" % r.pk, context=ctx).read())
h = t["meta"]["headers_map"]
api = {h[f["name"]]: f.get("description") for f in t["meta"]["data_schema"]["fields"]}
exp = {c["nazwa"]: c["nazwa"].rstrip("?") for c in columns_for(ROLE_PUBLIC)}
for k in sorted(set(api) | set(exp)):
    if api.get(k, "<brak>") != exp.get(k, "<brak>"):
        print("ROZNICA", repr(k), "API:", repr(api.get(k, "<brak>")), "oczekiwane:", repr(exp.get(k, "<brak>")))
print("koniec, zgodnych:", sum(api.get(k) == v for k, v in exp.items()), "/", len(exp))
