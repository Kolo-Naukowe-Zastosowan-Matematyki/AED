"""Wsad AED do backendu dane.gov.pl (mcod). Docelowo: mcod/resources/aed_constants.py.

Wzorowane na mcod/resources/dga_constants.py („Wykaz chronionych danych”, DGA):
  DGA_COLUMNS                        -> AED_COLUMNS (z flagą „chroniona”)
  MAIN_DGA_REQUIRED_SOURCE_COLUMNS   -> MAIN_AED_REQUIRED_SOURCE_COLUMNS
  MAIN_DGA_COLUMNS                   -> MAIN_AED_COLUMNS (tylko kolumny publiczne + dysponent)
  ALLOWED_DGA_INSTITUTIONS           -> ALLOWED_AED_INSTITUTIONS

Ta sama tabela jest w common/aed_columns.json serwisu rejestru (test tests/test_wsad.py pilnuje zgodności).
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


AED_RESOURCE_EXTENSIONS: List[str] = ["csv", "xlsx", "xls"]

AED_COLUMNS: List[AEDColumn] = [
    AEDColumn("numer_seryjny_aed", "Numer seryjny AED", "string", False, True),
    AEDColumn("szerokosc_geograficzna", "Szerokość geograficzna (b)", "number", True, False),
    AEDColumn("dlugosc_geograficzna", "Długość geograficzna (l)", "number", True, False),
    AEDColumn("wojewodztwo", "Województwo", "string", False, False),
    AEDColumn("miejscowosc", "Miejscowość", "string", False, False),
    AEDColumn("kod_pocztowy", "Kod pocztowy", "string", False, False),
    AEDColumn("adres_uliczny", "Adres", "string", True, False),
    AEDColumn("wewnatrz_budynku", "Wewnątrz budynku", "bool", False, False),
    AEDColumn("nazwa_budynku", "Nazwa obiektu", "string", False, False),
    AEDColumn("dokladna_lokalizacja", "Dokładna lokalizacja", "string", False, False),
    AEDColumn("typ_dostepnosci", "Typ dostępności", "string", True, False),
    AEDColumn("godziny_dostepnosci", "Godziny dostępności", "string", False, False),
    AEDColumn("czy_zamkniety", "Szafka zamknięta", "bool", False, False),
    AEDColumn("status_operacyjny", "Status operacyjny", "string", False, False),
    AEDColumn("nazwa_operatora", "Dysponent", "string", True, False),
    AEDColumn("data_waznosci_elektrod", "Data ważności elektrod", "date", False, True),
    AEDColumn("data_waznosci_baterii", "Data ważności baterii", "date", False, True),
    AEDColumn("data_aktualizacji_rekordu", "Data aktualizacji rekordu", "date", False, False),
    AEDColumn("zrodlo_danych", "Źródło danych", "string", True, False),
    AEDColumn("mozliwy_duplikat", "Możliwy duplikat", "bool", False, False),
    AEDColumn("osoba_kontaktowa", "Osoba kontaktowa", "string", False, True),
    AEDColumn("telefon_kontaktowy", "Telefon kontaktowy", "string", False, True),
]

AED_PUBLIC_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if not c.chroniona]
AED_PROTECTED_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if c.chroniona]

MAIN_AED_REQUIRED_SOURCE_COLUMNS: List[str] = [c.pole for c in AED_COLUMNS if c.wymagana and not c.chroniona]
# nazwa_operatora (dysponent) jest już w tabeli, jak „Nazwa dysponenta zasobu” w MAIN_DGA_COLUMNS
MAIN_AED_COLUMNS: List[str] = AED_PUBLIC_COLUMNS

ALLOWED_AED_INSTITUTIONS: List[str] = [_LOCAL, _STATE, _OTHER]

# Rola mcod (mcod/users/models.py: User.system_role), która widzi kolumny chronione
AED_PROTECTED_COLUMNS_ROLES: List[str] = ["admin"]
