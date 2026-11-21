"""Wspólny (wzorcowy) model rekordu AED używany przez wszystkie źródła.

Nazwy pól odpowiadają szkicowi wzorcowego zakresu danych z dokumentu strategii.
Współrzędne: WGS84 (EPSG:4326). Dane osobowe (e-maile, telefony osób) nie są przenoszone.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Kolejność kolumn w eksporcie CSV
FIELDS = [
    "id_aed",
    "nazwa_obiektu",
    "opis_lokalizacji",
    "adres",
    "szerokosc",
    "dlugosc",
    "wewnatrz",
    "pietro",
    "dostep",
    "godziny_dostepnosci",
    "dysponent",
    "data_weryfikacji",
    "zrodlo",
    "zrodlo_url",
    "licencja",
]

# Słownik pola "dostep"
DOSTEP = {
    "publiczny": "Publiczny",
    "w_godzinach": "W godzinach otwarcia obiektu",
    "ograniczony": "Ograniczony (na zgłoszenie)",
    "prywatny": "Prywatny",
    "nieznany": "Brak informacji",
}

# Polska z marginesem: odrzucamy punkty spoza tego prostokąta
PL_BBOX = (48.9, 14.0, 55.1, 24.3)  # min_lat, min_lon, max_lat, max_lon


@dataclass
class AED:
    id_aed: str
    szerokosc: float
    dlugosc: float
    zrodlo: str
    zrodlo_url: str
    licencja: str
    nazwa_obiektu: str = ""
    opis_lokalizacji: str = ""
    adres: str = ""
    wewnatrz: bool | None = None
    pietro: str = ""
    dostep: str = "nieznany"
    godziny_dostepnosci: str = ""
    dysponent: str = ""
    data_weryfikacji: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


def in_poland(lat: float, lon: float) -> bool:
    a, b, c, d = PL_BBOX
    return a <= lat <= c and b <= lon <= d


def to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):  # API dane.gov.pl potrafi zwracać {"val":..., "repr":...}
        value = value.get("val", value.get("repr"))
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def map_access(raw: str | None) -> str:
    """Mapuje wartości w stylu OSM/polskim na słownik pola 'dostep'."""
    if not raw:
        return "nieznany"
    r = str(raw).strip().lower()
    if r in ("yes", "permissive", "public", "publiczny", "tak", "ogólnodostępny", "ogolnodostepny", "24h"):
        return "publiczny"
    if r in ("customers", "w godzinach", "w godzinach otwarcia"):
        return "w_godzinach"
    if r in ("permit", "ograniczony", "na zgłoszenie", "delivery", "destination"):
        return "ograniczony"
    if r in ("private", "no", "prywatny", "nie"):
        return "prywatny"
    return "nieznany"
