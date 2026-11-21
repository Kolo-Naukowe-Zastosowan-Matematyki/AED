# Wsad AED do backendu dane.gov.pl (mcod)

Miejsce na wsad to mechanizm DGA „Wykaz chronionych danych” (stałe pisane CAPSEM). Pełna analiza: `tools-aed/WPIECIE_BACKEND.md`.
W tym folderze są pliki do wklejenia w mcod. Nie zmieniają mechaniki publikacji.

## 1. Tabela kolumn z flagą „chroniona”
`aed_constants.py` → `mcod/resources/aed_constants.py` (obok `dga_constants.py`).
Ta sama tabela jest w `common/aed_columns.json` serwisu rejestru, a `tests/test_wsad.py` sprawdza, że obie są zgodne.

## 2. Stałe w `mcod/settings/base.py` (obok `MAIN_DGA_*`, ok. l. 1706)

```python
MAIN_AED_DATASET_OWNER_ORGANIZATION_PK = env("MAIN_AED_DATASET_OWNER_ORGANIZATION_PK", default=None)  # instytucja odpowiedzialna
MAIN_AED_DATASET_DEFAULT_TITLE = "System Ewidencji Zasobów AED – wykaz zbiorczy"
MAIN_AED_RESOURCE_DEFAULT_TITLE = "Wykaz AED"
MAIN_AED_DATASET_CATEGORIES_TITLES = ["Zdrowie"]
MAIN_AED_DATASET_TAGS_NAMES = ["AED", "defibrylator", "wykaz AED"]
AED_REGISTRY_URL = env("AED_REGISTRY_URL", default="https://rejestr-aed.example")  # serwis rejestru
```

## 3. Rola dla serwisu rejestru: jedno pole w API konta
Serwis rejestru sprawdza token portalu przez `GET {API_URL}/auth/user`. Dziś ta odpowiedź **nie zawiera** roli
(`is_superuser`/`is_staff` są tylko w schemacie eksportu CSV, `users/serializers.py:89-90`). Wsad:

```python
# mcod/users/serializers.py, class UserApiAttrs (ok. l. 274)
system_role = fields.Str(dump_only=True)   # "admin" | "editor" | "representative" | "official" | "user"
```
`User.system_role` już istnieje (`mcod/users/models.py:521`), więc to jest cała zmiana po stronie portalu.

## 4. Konfiguracja serwisu na produkcji
`config.json` prototypu:

```json
"auth": {"tryb": "portal", "api_url": "https://api.dane.gov.pl"}
```
W trybie `demo` (domyślnym) serwis ma atrapę logowania administratora (hasło w `AED_ADMIN_HASLO`, domyślnie `admin-aed`).

## 5. Dalsze kroki (wg wzorca DGA, opis w WPIECIE_BACKEND.md, sekcja 4)
`resources/aed_utils.py` i `resources/tasks/aed.py` (zbiorczy zasób z `MAIN_AED_COLUMNS`, bez kolumn chronionych), wpis beat w `celeryapp.py`,
flaga `contains_aed_registry` na zasobie i jej pole w formularzu/adminie.
