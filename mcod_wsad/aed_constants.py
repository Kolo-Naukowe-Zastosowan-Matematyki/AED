"""Wsad AED do backendu dane.gov.pl (mcod). Docelowo: mcod/resources/aed_constants.py.

Wzorowane na mcod/resources/dga_constants.py („Wykaz chronionych danych”, DGA):
  DGA_COLUMNS                        -> AED_COLUMNS (z flagą „chroniona”)
  MAIN_DGA_REQUIRED_SOURCE_COLUMNS   -> MAIN_AED_REQUIRED_SOURCE_COLUMNS
  MAIN_DGA_COLUMNS                   -> MAIN_AED_COLUMNS (tylko kolumny publiczne + dysponent)
  ALLOWED_DGA_INSTITUTIONS           -> ALLOWED_AED_INSTITUTIONS

Złoty standard danych AED (schemat Oliwii, nazwy techniczne API/DB). Ta sama tabela jest w common/aed_columns.json serwisu rejestru (test tests/test_wsad.py pilnuje zgodności).
Kolumny chronione nie trafiają do zbiorczego zasobu na portalu, zostają w rejestrze AED i widzi je tylko
użytkownik z User.system_role == "admin".
"""
from typing import List, NamedTuple

try:  # w mcod
    from mcod.organizations.models import Organization

    _LOCAL, _STATE, _OTHER = (Organization.INSTITUTION_TYPE_LOCAL, Organization.INSTITUTION_TYPE_STATE,
                              Organization.INSTITUTION_TYPE_OTHER)
except ImportError:  # poza mcod (testy prototypu)
    _LOCAL, _STATE, _OTHER = "local", "state", "other"


class AEDColumn(NamedTuple):
    pole: str
    nazwa: str
    typ: str
    wymagana: bool
    chroniona: bool


AED_RESOURCE_EXTENSIONS: List[str] = ["csv", "xlsx", "xls", "ods", "json", "geojson", "xml"]
AED_CSV_SEPARATOR = ";"  # nagłówek CSV do bezpośredniego importu (złoty standard)
AED_BOOL_VALUES = ("TRUE", "FALSE")

AED_COLUMNS: List[AEDColumn] = [
    AEDColumn("aed_sn", "Numer seryjny (SN)", "string", True, True),
    AEDColumn("latitude", "Szerokość geograficzna", "number", True, False),
    AEDColumn("longitude", "Długość geograficzna", "number", True, False),
    AEDColumn("region", "Województwo", "string", True, False),
    AEDColumn("city", "Miejscowość", "string", True, False),
    AEDColumn("postal_code", "Kod pocztowy", "string", False, False),
    AEDColumn("street_address", "Ulica i numer", "string", True, False),
    AEDColumn("is_indoor", "Czy wewnątrz budynku?", "boolean", True, False),
    AEDColumn("building_name", "Nazwa obiektu", "string", False, False),
    AEDColumn("exact_location", "Dokładna lokalizacja", "string", True, False),
    AEDColumn("availability_type", "Kategoria dostępności", "string", True, False),
    AEDColumn("opening_hours", "Godziny otwarcia", "string", False, False),
    AEDColumn("is_locked", "Czy wymagany klucz/kod?", "boolean", True, False),
    AEDColumn("operational_status", "Status sprawności", "string", True, False),
    AEDColumn("operator_name", "Dysponent / Operator", "string", True, False),
    AEDColumn("pad_expiration_date", "Data ważności elektrod", "date", False, True),
    AEDColumn("battery_expiration_date", "Data zakończenia baterii", "date", False, True),
    AEDColumn("record_updated_at", "Data aktualizacji", "date", True, False),
    AEDColumn("data_source", "Dostawca danych", "string", True, False),
    AEDColumn("possible_duplicate", "Potencjalny duplikat", "boolean", False, True),
]

AED_PUBLIC_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if not c.chroniona]
AED_PROTECTED_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if c.chroniona]

MAIN_AED_REQUIRED_SOURCE_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if c.wymagana and not c.chroniona]
# operator_name (dysponent) jest już w tabeli, jak „Nazwa dysponenta zasobu” w MAIN_DGA_COLUMNS
MAIN_AED_COLUMNS: List[str] = AED_PUBLIC_COLUMNS

ALLOWED_AED_INSTITUTIONS: List[str] = [_LOCAL, _STATE, _OTHER]

# Rola mcod (mcod/users/models.py: User.system_role), która widzi kolumny chronione
AED_PROTECTED_COLUMNS_ROLES: List[str] = ["admin"]
