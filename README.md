# System Ewidencji Zasobów AED

Prototyp na zadanie „Misja AED – Dane na ratunek”. Składa się z **dwóch niezależnych instancji**, które
`server.py` uruchamia razem:

| Instancja | Folder | Adres | Co to jest |
| --- | --- | --- | --- |
| **A. Portal dane.gov.pl** (makieta) | `portal/` | http://localhost:8000 | oryginalny frontend portalu (z `frontend_latest.zip`) i jego API. Jedyna zmiana to nowy zbiór „System Ewidencji Zasobów AED” |
| **B. Serwis AED** | `rozwiazanie/` | http://localhost:8001 | osobny serwis z własnym frontendem, backendem i scrapingiem. Strona główna to Rejestr AED |

Portal nie ma nic wspólnego z serwisem poza tym, że zbiór AED do niego linkuje i z niego pobiera dane
(tak jak prawdziwy portal pobiera zasób z adresu podanego przez dostawcę).

## Uruchomienie

Wymagany Python 3.9 lub nowszy. Zbudowany frontend portalu jest już w `portal/frontend/dist`, więc Node.js nie jest potrzebny.

**Windows:** dwuklik w `start.bat`. Skrypt zatrzymuje poprzednią instancję (restart), uruchamia obie instancje
i sam otwiera portal w przeglądarce. `stop.bat` zatrzymuje serwer; można też zamknąć okno konsoli.

Ręcznie:

```
cd aed-prototyp
py server.py --open     # Windows (albo: python server.py)
```

Jeśli port jest zajęty albo zarezerwowany przez Windows (błąd 10013), portal spróbuje portów 8765–8784,
a serwis 8785–8799. Porty można wskazać: `py server.py --port 8080 --serwis-port 8081`.
Inne opcje: `--offline` (bez łączenia z dane.gov.pl, dane z pamięci podręcznej), `-v` (więcej logów).

Testy (bez sieci): `python -m unittest discover -s tests -v`

## Struktura

```
aed-prototyp/
├── server.py              uruchamia obie instancje
├── config.json            źródło danych (danegov), serwis, zbiór AED w portalu (zbior_aed)
├── common/http.py         wspólne elementy serwerów HTTP
├── portal/                INSTANCJA A: makieta dane.gov.pl
│   ├── backend/
│   │   ├── app.py             serwer: frontend portalu, API zbioru AED, proxy do dane.gov.pl
│   │   ├── aed_dataset.py     zbiór AED w formacie API portalu 1.4 (wyszukiwarka, zbiór, zasoby, tabela, metadane)
│   │   ├── serwis_client.py   pobieranie danych zasobów z API serwisu AED
│   │   ├── portal_proxy.py    odczyt (tylko GET) z api.dane.gov.pl i cms.dane.gov.pl; zapisy są blokowane
│   │   └── uwagi.py           „Zgłoś uwagi” do zbioru AED: kolejka dostawcy
│   └── frontend/
│       ├── build.py           budowanie portalu z frontend_latest.zip + jedna zmiana (link „Przejdź”)
│       └── dist/              zbudowany portal
├── rozwiazanie/                INSTANCJA B: serwis AED
│   ├── frontend/
│   │   ├── index.html         Rejestr AED: wyszukiwarka z filtrami (strona główna)
│   │   └── vendor/leaflet/    Leaflet 1.9.4
│   ├── backend/
│   │   ├── app.py             serwer: strony serwisu i API /aed-api
│   │   ├── store.py           magazyn rekordów AED, wyszukiwarka, najbliższe AED, eksport
│   │   ├── schema.py          wzorcowy zakres danych
│   │   ├── hours.py           „czy dostępny teraz” na podstawie godzin
│   │   └── map_export.py      mapa AED (strona /mapa i plik mapa_aed.html)
│   └── scraping/              pobieranie danych o AED z dane.gov.pl (danegov.py, run.py) i agregacja
│                              wszystkich tabel do jednej we wzorcowym zakresie (agregacja.py)
└── tests/
```

## A. Portal dane.gov.pl

1. W zakładce **Dane** wpisz „AED”: zbiór „System Ewidencji Zasobów AED” pojawia się na liście jako osobny dataset.
2. Strona zbioru `/pl/dataset/aed,system-ewidencji-zasobow-aed` wygląda jak każdy zbiór portalu
   (np. `/pl/dataset/1354`): metadane, zakładki Dane / Warunki wykorzystywania / Historia zbioru, API.
3. Zasoby:

| Zasób | Typ | Strona zasobu | „Przejdź” prowadzi do |
| --- | --- | --- | --- |
| Rejestr AED | plik CSV, GeoJSON | widok tabelaryczny | rejestru w serwisie AED (`/`) |

Ikony „Pobierz metadane” zwracają metadane jak w portalu: CSV (wiersz na zasób, kolumny zbioru, dostawcy i zasobu)
oraz RDF/XML w DCAT-AP.

Makieta tylko **czyta** z produkcyjnego dane.gov.pl. Zapisy (uwagi do innych zbiorów, propozycje danych, formularze,
logowanie) dostają lokalną odpowiedź demo i nie wychodzą do dane.gov.pl. „Zgłoś uwagi” do zbioru AED trafia do
kolejki dostawcy w `data/uwagi`.

Ustawienia zbioru: `config.json` → `zbior_aed`. Adres względny `rejestr_url` prowadzi do
serwisu AED, a jego publiczny adres można ustawić w `serwis.url`.

## B. Serwis AED

| Adres | Strona |
| --- | --- |
| `/` | Rejestr AED: wyszukiwanie po nazwie, miejscu i dostępie; „Znajdź najbliższe” pokazuje 10 najbliższych AED z odległością i nawigacją |
| `/mapa` | mapa wszystkich AED; „Znajdź najbliższe” pokazuje Ciebie i najbliższy AED, „Strona główna” wraca do rejestru |

API serwisu:

| Endpoint | Opis |
| --- | --- |
| `GET /aed-api/search?q=&miejsce=&dostep=&zrodlo=&publiczny=1&limit=&offset=` | wyszukiwarka rejestru |
| `GET /aed-api/points`, `GET /aed-api/aed/{idx}` | punkty dla mapy i pełny rekord |
| `GET /aed-api/nearest?lat=..&lon=..&n=3&tylko_dostepne=1` | najbliższe AED, np. dla dyspozytora |
| `GET /aed-api/rejestr.json` | rejestr we wzorcowym zakresie dla portalu |
| `GET /aed-api/export.xlsx`, `/aed-api/export.csv` | zagregowana tabela we wzorcowym zakresie (`common/aed_columns.json`); administrator dostaje też kolumny chronione |
| `GET /aed-api/export.geojson`, `/aed-api/mapa_aed.html` | pliki do pobrania |
| `GET /aed-api/kolumny`, `GET /aed-api/auth/rola`, `GET /aed-api/auth/zaloguj`, `POST /aed-api/auth/logout` | tabela kolumn, rola i konto z portalu, przejście do logowania w portalu, wylogowanie |
| `GET /aed-api/stats`, `GET /aed-api/sources` | liczniki oraz stan źródeł i raport pobierania |
| `POST /aed-api/refresh` | ponowne pobranie z dane.gov.pl |

### Scraping

Jedynym źródłem danych jest **dane.gov.pl** (`rozwiazanie/scraping/danegov.py`): API 1.4, czyli wyszukanie zbiorów,
ich zasobów, potem wierszy albo pliku CSV/GeoJSON. Współrzędne pochodzą z ról mapowych nadanych przez dostawcę
(`label`, `b`, `l`), a gdy ich brak, z nazw kolumn. Licencja rekordu jest brana z metadanych zbioru.

Samo pobranie, bez serwera: `python -m rozwiazanie.scraping.run --raport`. Jakie zbiory widzi wyszukiwarka dane.gov.pl (bez pobierania plików): `python -m rozwiazanie.scraping.run --szukaj`; pytamy o kilka odmian słowa „defibrylator” i o „AED”, bo wyszukiwarka nie zawsze odmienia wyrazy, a dodatkowe frazy można dopisać w `config.json` (`danegov.queries`). Zagregowana tabela do pliku: `python -m rozwiazanie.scraping.run --offline --xlsx` (albo `--csv`), wynik w `data/rejestr_aed.xlsx`. Każdy zasób przechodzi przez standaryzację do złotego standardu (schemat Oliwii, `common/aed_columns.json`): `rozwiazanie/scraping/czytniki.py` czyta dowolny plik (CSV/XLSX/ODS/XLS/JSON/GeoJSON/XML/KML/ZIP, kodowanie i separator wykrywane automatycznie), `standard.py` mapuje kolumny po synonimach i po wartościach i normalizuje wartości (przecinek dziesiętny, zamienione lat/lon, PUWG 1992/2000, słowniki, daty, województwo), `geokod.py` uzupełnia braki z geokodera GUGiK (adresy bez współrzędnych, brakująca ulica przy samych współrzędnych; dane ze zbioru mają pierwszeństwo). Zwykły start korzysta tylko z pamięci `data/cache/geokod.json`, która jest w repozytorium; nowe zapytania wysyła osobny krok `python -m rozwiazanie.scraping.run --geokoduj` (najwyżej 300 zapytań, 1 s odstępu, po odmowie GUGiK przerwa 24 h zapisana w pliku), po którym plik commitujemy. Nową nazwę kolumny obsługuje się dopisaniem synonimu w `common/aed_columns.json`, bez zmiany kodu; nierozpoznane kolumny i odrzucone wiersze są w raporcie (`--raport`, `--diagnoza`). Agregacja (`rozwiazanie/scraping/agregacja.py`, logika eksportu XLSX z gałęzi natka_branch) zapisuje jedną tabelę: CSV z separatorem `;`, TRUE/FALSE, RRRR-MM-DD, duplikaty po SN albo do 15 m. Działa z `openpyxl` albo bez niego. Wynik trafia do `data/cache/danegov.json`,
więc serwis działa też bez internetu. Nie korzystamy z aplikacji ani serwisów, których regulamin zabrania pobierania danych.

## Dlaczego makieta portalu, a nie backend `mcod`

Backend portalu (`mcod`, Django) do uruchomienia potrzebuje m.in. PostgreSQL, Elasticsearch i Redis. Żeby prototyp
dało się uruchomić jedną komendą, API zbioru AED jest odtworzone w `portal/backend/aed_dataset.py` w formacie API
portalu 1.4, a pozostałe dane portalu są czytane z produkcyjnego dane.gov.pl. W prawdziwym portalu zbiór AED
dodaje dostawca w panelu, a zasoby wskazują pliki i strony serwisu AED.

### Logowanie przez dane.gov.pl

Serwis nie ma własnych haseł. „Zaloguj się przez dane.gov.pl” prowadzi do oryginalnego formularza „Zaloguj się”
makiety portalu (wybierz „Zaloguj się e-mailem i hasłem”). Po zalogowaniu portal wraca do rejestru, a serwis
sprawdza token portalu w `GET /api/auth/user` i bierze z konta rolę. Konto służb (`aed_rola: sluzby_aed`) i
administrator portalu widzą kolumny chronione; pozostali widzą dane publiczne. „Wyloguj” kończy sesję w portalu.

Konta demo (makieta portalu, `portal/backend/konta.py`; tylko na localhost):

| E-mail | Hasło | Rola w rejestrze |
| --- | --- | --- |
| `sluzby@aed.demo` | `demo-aed` | służby AED: kolumny chronione |
| `admin@aed.demo` | `demo-aed` | administrator portalu: kolumny chronione |
| `obywatel@aed.demo` | `demo-aed` | zwykłe konto: dane publiczne |

Na produkcji to samo działa z prawdziwym kontem dane.gov.pl po dodaniu pola roli w mcod (`mcod_wsad/README.md`).

## Ograniczenia prototypu

- Bez sieci strony portalu (np. lista zbiorów, treści CMS) i podkład mapy pokażą błędy ładowania;
  serwis AED działa na danych z pamięci podręcznej.
- Zbiór AED jest dopisywany do wyników wyszukiwania, gdy fraza zawiera np. „AED” lub „defibrylator” i nie są
  zaznaczone inne filtry. Reszta wyników pochodzi z produkcyjnego API.
- Dane pochodzą wyłącznie z dane.gov.pl, więc rejestr jest tak pełny, jak zbiory opublikowane tam przez dysponentów.
- Przy tworzeniu kodu korzystano z narzędzi AI (do ujawnienia zgodnie z regulaminem konkursu).

## Licencje komponentów

- Frontend portalu dane.gov.pl: MIT. Leaflet 1.9.4: BSD-2-Clause (`rozwiazanie/frontend/vendor/leaflet/LICENSE`).
- Godło RP w nagłówku serwisu: wzór z Wikimedia Commons, źródło i zasady użycia w `rozwiazanie/frontend/vendor/godlo/ZRODLO.md`.
- Podkład mapy (kafelki, jak w portalu dane.gov.pl): © współtwórcy OpenStreetMap.
