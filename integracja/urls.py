import json
import os
from pathlib import Path

from django.apps import apps
from django.http import JsonResponse
from django.urls import path, re_path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from rozwiazanie.backend.app import Rejestr, setup

BASE = Path(__file__).resolve().parents[1]
setup(BASE, json.loads((BASE / "config.json").read_text(encoding="utf-8")),
      offline=os.getenv("AED_OFFLINE") == "1")


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "HEAD", "POST"])
def rejestr(request):
    return Rejestr(request)._route("GET" if request.method == "HEAD" else request.method)


@never_cache
@require_http_methods(["GET", "HEAD"])
def wykresy(request, resource_id):
    from mcod.resources.aed import uid

    revisions = apps.get_model("resources", "AedPublication").objects.filter(
        resource_id=resource_id, resource__uuid=uid("wykaz.csv"), resource__status="published",
        resource__dataset__status="published", resource__dataset__organization__status="published",
        resource__is_removed=False, resource__dataset__is_removed=False,
        resource__dataset__organization__is_removed=False,
        resource__is_permanently_removed=False, resource__dataset__is_permanently_removed=False,
        resource__dataset__organization__is_permanently_removed=False,
    ).order_by("-pk")
    latest = revisions.first()
    if latest is None:
        return JsonResponse({"blad": "Brak opublikowanych pomiarów wykazu."}, status=404)
    history = revisions.filter(pk__lte=latest.pk).order_by("pk").values("recorded_at", "total")
    return JsonResponse({"total": latest.total, "areas": latest.areas, "history": list(history)})


urlpatterns = [
    path("aed-api/wykresy/<int:resource_id>", wykresy),
    re_path(r"^.*$", rejestr),
]

