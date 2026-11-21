# Moduł „Mapa AED” wbudowany w portal dane.gov.pl

Prototyp na zadanie „Misja AED – Dane na ratunek”. Po uruchomieniu `server.py` otwiera się **strona główna
portalu dane.gov.pl** (jego oryginalny frontend Angular), z nową pozycją „Mapa AED” w menu i banerem akcji.
Moduł działa pod adresem `/pl/aed`.

## Uruchomienie

Wymagany Python 3.9 lub nowszy. Zbudowany frontend jest już w `frontend/dist`, więc Node.js nie jest potrzebny.

**Windows:** dwuklik w `start.bat`. Skrypt zatrzymuje poprzednią instancję (restart), uruchamia serwer i sam otwiera
przeglądarkę na właściwym porcie. `stop.bat` zatrzymuje serwer; można też zamknąć okno konsoli.

Ręcznie:

```
cd aed-prototyp
py server.py --open     # Windows (albo: python server.py)
```

Otwórz adres podany w konsoli, domyślnie http://localhost:8000. Jeśli port jest zajęty albo zarezerwowany
przez Windows (błąd 10013), serwer sam spróbuje portów 8765–8784. Port można też wskazać: `py server.py --port 8765`.
Inne opcje: `--offline` (bez łączenia z dane.gov.pl, dane z pamięci podręcznej), `-v` (więcej logów).

Opcjonalnie, dla strefy 4 (weryfikacja zdjęć): `pip install -r vision/requirements.txt`. Bez Pillow zgłoszenia
działają, ale zdjęcie nie jest wstępnie oceniane.

Testy (bez sieci): `python -m unittest discover -s tests -v`

Dla eksportu XLSX zainstaluj zależność:

```
pip install -r requirements.txt
```

Arkusz XLSX można wygenerować bez uruchamiania serwera:

```
python -m scraping.run --xlsx
```

## Cztery strefy kodu

```
aed-prototyp/
├── server.py          punkt wejścia: czyta config.json i uruchamia backend
├── config.json        źródła danych (frazy wyszukiwania, konkretne zbiory i zasoby)
├── backend/           STREFA 1: serwer HTTP, API modułu, model danych, zgłoszenia
├── scraping/          STREFA 2: pobieranie danych o AED ze źródeł
├── frontend/          STREFA 3: moduł Angular wbudowywany w frontend portalu
├── vision/            STREFA 4: rozpoznawanie AED na zdjęciach zgłoszeń
└── tests/
```

### Strefa 1: `backend/`

| Plik | Rola |
| --- | --- |
| `app.py` | serwer HTTP: API modułu `/aed-api/…`, serwowanie zbudowanego portalu z `frontend/dist`, przekierowanie zapytań portalu |
| `portal_proxy.py` | przekazuje zapytania portalu do produkcji: `/api/` → `api.dane.gov.pl/1.4`, `/cms/` → `cms.dane.gov.pl`, `/media/`, `/flags/` |
| `store.py` | magazyn rekordów AED z obu źródeł, wyszukiwanie najbliższych, eksport, statystyki |
| `schema.py` | wzorcowy zakres danych (pola rekordu, słownik dostępu) |
| `hours.py` | sprawdzanie „czy dostępny teraz” na podstawie godzin (`opening_hours`) |
| `submissions.py` | zgłoszenia nowych AED od użytkowników (status „do weryfikacji”, bez danych osobowych) |

API modułu:

| Endpoint | Opis |
| --- | --- |
| `GET /aed-api/points` | wszystkie punkty w formacie kompaktowym dla mapy |
| `GET /aed-api/aed/{idx}` | pełny rekord |
| `GET /aed-api/search` | wyszukiwanie i filtrowanie rekordów rejestru AED |
| `GET /aed-api/nearest?lat=..&lon=..&n=3&tylko_dostepne=1` | najbliższe AED, np. dla dyspozytora |
| `GET /aed-api/stats`, `GET /aed-api/sources` | liczniki oraz stan źródeł i raport pobierania |
| `POST /aed-api/refresh` | ponowne pobranie z dane.gov.pl |
| `GET /aed-api/export.csv`, `/aed-api/export.xlsx`, `/aed-api/export.geojson` | zbiór we wzorcowym zakresie (tylko dane z dane.gov.pl) |
| `POST /aed-api/zdjecie?lat=..&lon=..` | wstępna ocena zdjęcia (strefa 4) |
| `POST /aed-api/zgloszenia`, `GET /aed-api/zgloszenia` | zgłoszenie nowego AED i lista zgłoszeń |

### Strefa 2: `scraping/`

| Źródło | Plik | Jak pobierane | Licencja | W eksporcie |
| --- | --- | --- | --- | --- |
| **dane.gov.pl** (główne) | `danegov.py` | API 1.4: wyszukanie zbiorów, ich zasobów, potem wierszy (`/resources/{id}/data`, max 100 na stronę) albo pliku CSV/GeoJSON. Współrzędne z ról mapowych nadanych przez dostawcę (`label`, `b`, `l`), a gdy ich brak, po nazwach kolumn. | wg metadanych zbioru | tak |
| **OpenStreetMap** (`../material/PL.geojson`) | `osm.py` | plik lokalny | ODbL 1.0 | **nie**, tylko warstwa demonstracyjna z atrybucją |

Samo pobranie, bez serwera: `python -m scraping.run --raport`. Wynik z dane.gov.pl trafia do
`data/cache/danegov.json`, więc moduł działa też bez internetu. Z danych OSM celowo pomijane są telefony i e-maile.
Nie korzystamy z aplikacji ani serwisów, których regulamin zabrania pobierania danych.

### Strefa 3: `frontend/`

- `portal-module/src/app/pages/aed/` to kod modułu w Angularze 18, w konwencjach portalu (komponenty standalone,
  trasy z `ngx-translate-router`, style z jego zmiennych, tryby wysokiego kontrastu).
- `build.py` wgrywa moduł do źródeł portalu (`../material/frontend_latest.zip`), dopisuje trasę, pozycję w menu,
  baner na stronie głównej i tłumaczenia, a potem buduje portal do `frontend/dist`. Każda zmiana w kodzie portalu
  jest oznaczona komentarzem `AED-MODULE`. Przebudowa wymaga Node.js 20+: `python frontend/build.py`.
- `dist/` to gotowy, zbudowany portal z modułem.

Ekrany modułu:

| Adres | Ekran |
| --- | --- |
| `/pl/aed` | start: jeden duży przycisk „Znajdź najbliższy AED” i „Zadzwoń 112”, pod spodem cztery kafle |
| `/pl/aed/teraz` | **tryb ratunkowy** na cały ekran: strzałka i odległość do najbliższego AED, czas dojścia, gdzie dokładnie wisi, „Prowadź do AED” (nawigacja piesza w telefonie), „Inny AED”, kompas, skrócona instrukcja pierwszej pomocy z metronomem |
| `/pl/aed/mapa` | mapa na pełną szerokość, bez paska bocznego; nad nią wyszukiwanie i filtry, pod nią lista najbliższych AED |
| `/pl/aed/pomoc` | pierwsza pomoc krok po kroku, metronom 110/min, link do „Stayin’ Alive” |
| `/pl/aed/zglos` | zgłoszenie AED w trzech krokach: zdjęcie, miejsce, opis |
| `/pl/aed/dane` | źródła, eksport zbioru, instrukcja dla instytucji „jak opublikować dane o AED w dane.gov.pl” |
| `/rejestr.html` | osobna wyszukiwarka rejestru AED, z filtrami, szczegółami lokalizacji i odnośnikami do źródeł |

Tryb ratunkowy nie jest zasłaniany modalem RODO portalu przy pierwszej wizycie (modal pokaże się przy następnej zwykłej wizycie).

### Strefa 4: `vision/`

`verify.py` wstępnie ocenia zdjęcie dołączone do zgłoszenia, zanim trafi ono do weryfikacji przez człowieka.
Sprawdza zielony znak AED (ISO 7010), ostrość i jasność, datę i GPS z EXIF (porównuje z deklarowanym miejscem)
oraz duplikaty (dHash). Wynik to `prawdopodobnie_aed`, `niepewne` albo `odrzuc`, z listą uwag dla użytkownika.
Opcjonalnie można włączyć model CLIP (`transformers`, `torch`). To heurystyka wspierająca moderatora, a nie decyzja automatyczna.

## Dlaczego osobny serwis, a nie aplikacja w backendzie portalu

Backend portalu (`mcod`, Django) do uruchomienia potrzebuje m.in. PostgreSQL, Elasticsearch i Redis. Żeby prototyp
dało się uruchomić jedną komendą, moduł AED działa jako osobny, mały serwis (`/aed-api`), a dane portalu
(zbiory, CMS) są pobierane z produkcyjnego dane.gov.pl. Frontend jest natomiast prawdziwym frontendem portalu
z wbudowanym modułem. W docelowym wdrożeniu API modułu można przenieść do `mcod` jako osobną aplikację Django
albo zostawić jako mikroserwis za tym samym reverse proxy.

## Ograniczenia prototypu

- Połączenie z prawdziwym API dane.gov.pl nie zostało sprawdzone w środowisku, w którym powstał kod (brak dostępu
  do sieci). Parser jest przetestowany na zasymulowanych odpowiedziach zgodnych z kodem backendu portalu.
  Bez sieci strony portalu (np. lista zbiorów, treści CMS) pokażą błędy ładowania, a moduł AED działa na danych lokalnych.
- Czas dojścia jest szacowany (5 km/h, współczynnik 1,3); prawdziwa trasa piesza otwiera się w aplikacji map.
- Rozpoznawanie znaku AED na zdjęciach to heurystyka, wymaga testów na prawdziwych zdjęciach.
- Treść pierwszej pomocy wymaga weryfikacji z aktualnymi wytycznymi ERC / Polskiej Rady Resuscytacji.
- Przy tworzeniu kodu korzystano z narzędzi AI (do ujawnienia zgodnie z regulaminem konkursu).

## Licencje komponentów

- Frontend portalu dane.gov.pl: MIT. Leaflet 1.9.4: BSD-2-Clause.
- Podkład mapy i dane demonstracyjne: © współtwórcy OpenStreetMap, ODbL.
