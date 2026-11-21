"""Źródło demonstracyjne: eksport OpenStreetMap (GeoJSON, tag emergency=defibrillator).

UWAGA LICENCYJNA: dane OSM są na licencji ODbL 1.0 (© współtwórcy OpenStreetMap).
W prototypie służą wyłącznie jako warstwa demonstracyjna / do analizy pokrycia,
z atrybucją. Nie są włączane do eksportu wzorcowego zbioru (patrz store.export_records).
E-maile i telefony z OSM są celowo pomijane.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.schema import AED, in_poland, map_access

NAME = "osm"
LABEL = "OpenStreetMap (warstwa demonstracyjna)"
LICENSE = "ODbL 1.0 – © współtwórcy OpenStreetMap"
ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"


def _first(props: dict, *keys: str) -> str:
    for k in keys:
        v = props.get(k)
        if v:
            return str(v).strip()
    return ""


def load(path: Path) -> list[AED]:
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    out: list[AED] = []
    for feat in data.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        if not in_poland(lat, lon):
            continue
        p = feat.get("properties") or {}
        osm_type, osm_id = p.get("@osm_type", "node"), p.get("@osm_id")
        addr = " ".join(
            x for x in [_first(p, "addr:street", "addr:place"), _first(p, "addr:housenumber")] if x
        )
        city = _first(p, "addr:city")
        if city:
            addr = f"{addr}, {city}" if addr else city
        indoor = p.get("indoor")
        out.append(
            AED(
                id_aed=f"osm-{osm_type}-{osm_id}",
                szerokosc=round(lat, 6),
                dlugosc=round(lon, 6),
                zrodlo=NAME,
                zrodlo_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                licencja=LICENSE,
                nazwa_obiektu=_first(p, "name", "operator", "description:pl", "description"),
                opis_lokalizacji=_first(
                    p, "defibrillator:location:pl", "defibrillator:location", "description:pl", "description"
                ),
                adres=addr,
                wewnatrz=None if indoor is None else indoor == "yes",
                pietro=_first(p, "level"),
                dostep=map_access(p.get("access")),
                godziny_dostepnosci=_first(p, "opening_hours"),
                dysponent=_first(p, "operator"),
                data_weryfikacji=_first(p, "check_date", "survey:date"),
            )
        )
    return out
