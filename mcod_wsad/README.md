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
aed_rola = fields.Str(dump_only=True)      # "sluzby_aed" dla kont służb (PRM, PSP, dyspozytorzy), inaczej ""
```
`User.system_role` już istnieje (`mcod/users/models.py:521`). `aed_rola` to nowe pole konta (np. nadawane w panelu
administratora, wzorem flag ról w `User`). Serwis daje dostęp do kolumn chronionych przy `aed_rola == "sluzby_aed"`
albo `system_role == "admin"`.

## 4. Konfiguracja serwisu na produkcji
`config.json` prototypu:

```json
"auth": {"api_url": "https://api.dane.gov.pl/1.4", "logowanie_url": "https://dane.gov.pl/pl/user/login?redirect=…"}
```
Lokalnie `server.py` ustawia oba adresy na makietę portalu (konta demo w README prototypu). Serwis czyta token
z ciasteczka frontendu portalu (`apiauthtoken`, na localhost `local_apiauthtoken`), więc na produkcji rejestr
musi działać w domenie dane.gov.pl (np. `rejestr-aed.dane.gov.pl`), żeby dostać to ciasteczko.

## 5. Dalsze kroki (wg wzorca DGA, opis w WPIECIE_BACKEND.md, sekcja 4)
`resources/aed_utils.py` i `resources/tasks/aed.py` (zbiorczy zasób z `MAIN_AED_COLUMNS`, bez kolumn chronionych), wpis beat w `celeryapp.py`,
flaga `contains_aed_registry` na zasobie i jej pole w formularzu/adminie.
