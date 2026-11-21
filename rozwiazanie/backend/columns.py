"""Tabela wzorcowego zakresu danych AED z flagą „chroniona” i filtr kolumn zależny od roli.

Definicja kolumn: common/aed_columns.json (ta sama tabela co mcod_wsad/aed_constants.py).
Kolumny chronione nigdy nie trafiają na portal dane.gov.pl ani do odpowiedzi dla roli publicznej.
Wartości chronione trzymamy osobno od danych publicznych:
  data/chronione/chronione.json        dane od dostawców (poza repozytorium, .gitignore)
  rozwiazanie/dane_demo/chronione_demo.json przykładowe, zmyślone wartości do pokazu (gdy brak pliku powyżej)
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger("aed.columns")
ROOT = Path(__file__).resolve().parents[2]
COLUMNS_FILE = ROOT / "common" / "aed_columns.json"
DEMO_FILE = ROOT / "rozwiazanie" / "dane_demo" / "chronione_demo.json"

ROLE_ADMIN = "admin"
ROLE_PUBLIC = "publiczny"


def load_columns(path: Path = COLUMNS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["kolumny"]


COLUMNS = load_columns()
PUBLIC_FIELDS = [c["pole"] for c in COLUMNS if not c["chroniona"]]
PROTECTED_FIELDS = [c["pole"] for c in COLUMNS if c["chroniona"]]
# kolumny chronione podawane przez dostawców (possible_duplicate wylicza agregacja, nie dostawca)
PROVIDED_PROTECTED_FIELDS = [c["pole"] for c in COLUMNS if c["chroniona"] and c.get("wymagalnosc") != "automatyczne"]


def columns_for(role: str) -> list[dict]:
    """Opis kolumn widocznych dla roli (do nagłówków tabeli w interfejsie)."""
    return [c for c in COLUMNS if role == ROLE_ADMIN or not c["chroniona"]]


class ProtectedData:
    """Wartości kolumn chronionych, kluczem jest id_aed."""

    def __init__(self, base: Path):
        self.path = base / "data" / "chronione" / "chronione.json"
        self.lock = threading.Lock()
        self.demo = False
        self.values: dict[str, dict] = {}
        self.reload()

    def reload(self):
        path = self.path if self.path.exists() else DEMO_FILE
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError) as exc:
            log.warning("Nie udało się wczytać danych chronionych z %s: %s", path, exc)
            raw = {}
        rows = raw.get("rekordy", {}) if isinstance(raw, dict) else {}
        with self.lock:
            # tylko kolumny oznaczone w tabeli jako chronione, nic więcej
            self.values = {str(k): {f: v.get(f, "") for f in PROVIDED_PROTECTED_FIELDS}
                           for k, v in rows.items() if isinstance(v, dict)}
            self.demo = path == DEMO_FILE
        log.info("Dane chronione: %d rekordów (%s)", len(self.values), "demo" if self.demo else path)

    def get(self, id_aed: str) -> dict:
        with self.lock:
            return dict(self.values.get(id_aed) or {f: "" for f in PROVIDED_PROTECTED_FIELDS})


def apply_role(item: dict, role: str, protected: ProtectedData) -> dict:
    """Zwraca rekord z kolumnami dozwolonymi dla roli. Filtrowanie zawsze po stronie serwera."""
    out = {k: v for k, v in item.items() if k not in PROTECTED_FIELDS}
    if role == ROLE_ADMIN:
        out.update(protected.get(str(item.get("id_aed", ""))))
        out["_chronione"] = PROTECTED_FIELDS
    return out
