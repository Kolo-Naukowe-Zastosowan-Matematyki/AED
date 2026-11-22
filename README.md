# RAED — Rejestr Defibrylatorów AED

RAED zbiera w jednym wykazie lokalizacje automatycznych defibrylatorów zewnętrznych (AED), które różne instytucje publikują w portalu danych. Mieszkaniec może znaleźć urządzenie na mapie, dyspozytor sprawdzić zgłoszoną sprawność, a redaktor poprawić dane u źródła. Każda pozycja zachowuje informację o swoim pochodzeniu. Projekt działa w lokalnej instancji oprogramowania **dane.gov.pl (mcod)**.

**Zakres demonstracji.** Dołączony wykaz zawiera 74 pozycje z czterech miast. Krosno i Przemyśl mają po 21, Legionowo 24, a Marki 8. Wybranie „Polska” pokazuje wszystkie pozycje tego wykazu. Miejscowi dostawcy w demonstracji reprezentują cztery źródła. Ich nazwy, oryginalne adresy zasobów i warunki wykorzystania można sprawdzić w [pliku pochodzenia](jury/Zrodla-AED.csv).

## Materiały dla jury

| Materiał | Gdzie go znaleźć |
| --- | --- |
| Prezentacja z krokami użytkownika, zrzutami z działającego prototypu i ograniczeniami | [Prezentacja techniczna (PDF)](prezentacja/Prezentacja-techniczna.pdf) |
| Scenariusz do samodzielnego sprawdzenia | [Instrukcja dla jury](jury/Instrukcja.md) |
| Publiczne dane do odczytu bez uruchamiania portalu | [Wykaz AED (CSV)](jury/Wykaz-AED.csv) i [źródła (CSV)](jury/Zrodla-AED.csv) |
| Wzorcowy zakres danych dla dostawcy | [Wzorzec AED (XLSX)](jury/Wzorzec-AED.xlsx) |
| Logotyp RAED | [JPG](ksiega_znaku/RAED.jpg) · [PNG](ksiega_znaku/RAED.png) · [PDF](ksiega_znaku/RAED.pdf) · [edytowalny SVG](ksiega_znaku/RAED.svg) |
| Zasady stosowania logotypu | [Księga znaku (PDF)](ksiega_znaku/Ksiega-znaku-RAED.pdf) |
| Prototyp i kod źródłowy | [Uruchomienie](#jak-uruchomić-prototyp) i [mapa kodu](#jak-działa-integracja-i-gdzie-jest-kod) |

## Jak skorzystać z rejestru

1. Otwórz rejestr. Wyniki dla Polski wczytują się przy wejściu. Wybierz widok **Mapa**, **Tabela** lub **Lista**. Aby zawęzić wyniki, wpisz np. „Legionowo” i wybierz „Szukaj”.
2. Na mapie otwórz znacznik. Sprawdź adres, opis miejsca i dostępne informacje o godzinach. W widoku listy możesz też przejść do źródła. Opcja „Znajdź najbliższe” wymaga zgody przeglądarki na użycie lokalizacji.
3. Użyj filtrów, np. „Dostępny 24/7”. Brak wartości oznacza, że źródło nie podało informacji. Odległość do urządzenia ani wpis w wykazie nie potwierdzają jego bieżącej dostępności.
4. Aby porównać wiele urządzeń, otwórz pełną tabelę, wybierz kolumny i pobierz wyniki. W górnym pasku możesz zmienić kontrast i wielkość tekstu. Na małym ekranie te opcje są pod przyciskiem „Czytelność”.
5. Aby sprawdzić liczby dla obszaru, w portalu otwórz zbiór **System Ewidencji Zasobów AED – wykaz defibrylatorów**, zasób **Wykaz AED** i kartę **Wykres**. Wybierz województwo, powiat albo gminę. Widok historii pokazuje kolejne zapisane stany wspólnego wykazu. Data pomiaru to data publikacji w lokalnej instancji.

## Jak dostawca przekazuje dane

1. Na karcie zbioru AED otwórz **Wzorcowy zakres danych AED – szablon XLSX** i pobierz plik. Ten sam wzorzec jest w katalogu `jury`. Szablon ma własną kartę zasobu obok aktualnego wykazu CSV.
2. W arkuszu **Wykaz publiczny** wpisz jedno urządzenie w każdym wierszu. Zachowaj 16 polskich nagłówków. Arkusz **Słownik pól** zawiera polskie nazwy, typy, wymagalność, widoczność i opisy 20 pól standardu. Cztery chronione pola są tam opisane dla dokumentacji. Ich wartości nie należą do pliku publicznego.
3. W panelu redakcyjnym dostawca publikuje plik w zbiorze swojej instytucji i zaznacza **Uwzględnij publiczny plik w wykazie AED**. Wypełniony wzorzec XLSX lub CSV może być plikiem wejściowym. Dostawca określa warunki wykorzystania i odpowiada za aktualność danych źródłowych.
4. Co minutę proces synchronizacji wyszukuje oznaczone, opublikowane zasoby. Ujednolica nazwy kolumn i współrzędne, łączy wiersze i aktualizuje zbiorczy wykaz oraz tabelę pochodzenia. Po wycofaniu pliku lub zdjęciu oznaczenia jego wiersze znikają z następnego przeliczenia. Wynik przetwarzania każdego źródła jest dostępny pod `/aed-api/sources`.

Polityka demonstracji dopuszcza CC0 i CC BY z przypisaniem źródła. Pliki z inną licencją lub indywidualnymi warunkami trafiają do raportu pominięć. Dołączone pliki CSV mają kodowanie UTF-8 i separator średnikowy. Tabela w portalu używa polskich nazw kolumn. Nazwy w pobieranych plikach CSV i XLSX odpowiadają nazwom z rejestru. Programy korzystające z rekordów JSON mogą nadal używać technicznych identyfikatorów pól.

## Kto widzi jakie dane

| Osoba | Uprawnienia w demonstracji |
| --- | --- |
| Mieszkaniec | Publiczna mapa, lista, tabela, źródła i eksport bez logowania. |
| Dyspozytor z grupy „Służby AED” | Widok dla służb i informacja o sprawności. |
| Redaktor instytucji | Publikowanie i aktualizacja zasobów własnego dostawcy w panelu mcod. |
| Superadministrator | Dodatkowo numer seryjny, daty ważności baterii i elektrod oraz oznaczenie potencjalnego duplikatu. Przykłady wartości chronionych są syntetyczne. |

Jeżeli minął najwcześniejszy ze znanych terminów baterii i elektrod, rejestr pokazuje **Po terminie**. Dyspozytor widzi wynik tej reguły bez ujawniania dat. Kolejne publikacje publicznego pliku oraz eksporty respektują zakres danych przewidziany dla odbiorcy.

## Jak uruchomić prototyp

1. Na Windows przygotuj Ubuntu w WSL, działający Docker Engine i Docker Compose v2 w tej dystrybucji. Rozpakuj cały projekt do jednego katalogu. Pierwszy start wymaga internetu do pobrania obrazów i zależności.
2. Uruchom `start.bat`. W Linuksie użyj `sh start.sh`. Skrypt uruchamia usługi, przygotowuje bazę, publikuje pliki i sprawdza odpowiedzi API. Poczekaj na końcowy komunikat „OK” z identyfikatorem zbioru i liczbą rekordów.
3. Na Windows uruchom `demo.bat`. Otwiera osobny profil Edge lub Chrome skonfigurowany na lokalne domeny. W innej przeglądarce skonfiguruj nazwy `mcod.local`, `api.mcod.local`, `admin.mcod.local` i `cms.mcod.local` na 127.0.0.1 oraz zaufanie do lokalnego certyfikatu.
4. Wejdź do [rejestru](https://mcod.local/), [portalu](https://mcod.local/pl) lub [panelu redakcyjnego](https://admin.mcod.local/). Hasła utworzonych kont operator znajdzie w lokalnym pliku `../.raed-lokalne/dane/konta-demo.txt`. Zespół nie musi dołączać tego pliku do zgłoszenia.
5. Po pokazie uruchom `stop.bat`. Wolumeny zachowują dane między uruchomieniami.

**Konfiguracja zarejestrowanego login.gov.pl.** Operator umieszcza klucz i certyfikat w `../.raed-lokalne/wk/key.pem` i `../.raed-lokalne/wk/cert.pem`. W `../.raed-lokalne/mcod.env` ustawia uzgodnione dla tej samej integracji wartości `LOGINGOVPL_ISSUER`, `LOGINGOVPL_SSO_URL`, `LOGINGOVPL_ARTIFACT_RESOLVE_URL`, `LOGINGOVPL_SL_URL` i `LOGINGOVPL_ASSERTION_CONSUMER_URL`. Adres powrotu prowadzi do `/logingovpl/idp` w domenie panelu. Po ponownym starcie operator powiązuje konto mcod z tożsamością WK.

## Jak działa integracja i gdzie jest kod

| Element | Odpowiedzialność i źródła |
| --- | --- |
| Katalog mcod | Modele Django instytucji, zbioru, zasobu i pliku. PostgreSQL przechowuje dane, Elasticsearch indeksuje zasoby, Celery i RabbitMQ przetwarzają zadania, Redis obsługuje m.in. sesje. [Backend portalu](mcod/) |
| Scalenie AED | Redaktor wybiera pliki podobnie jak w mechanizmie wykazów DGA. Publikator utrzymuje stały identyfikator wspólnego wykazu, zapisuje pomiary i udostępnia zasoby przez standardowe API portalu 1.4. [Scalanie](integracja/wykaz.py) · [polecenie publikacji](mcod/mcod/resources/management/commands/publikuj_aed.py) |
| Rejestr | Widoki Django korzystają z sesji portalu. Strony rejestru, mapa Leaflet, czytniki formatów, filtry i eksporty są w [kodzie aplikacji](rozwiazanie/). Nazwy pól, typy i synonimy są we [wspólnym schemacie](common/aed_columns.json). |
| Portal użytkownika | Nginx udostępnia portal Angular, API, CMS i strony rejestru. Projekt zawiera [wersję uruchomieniową i źródła Angular](portal/frontend/). |
| Uruchomienie i testy | [Skrypt startowy](start.sh), [konfiguracja usług AED](mcod/compose.aed.yml), [testy rejestru](tests/) i [test odbiorczy przez HTTPS](integracja/sprawdz.py). |

**Sprawdzenie techniczne.** Po starcie uruchom `sh integracja/test-registry.sh`. Dodatkowo z katalogu `mcod` uruchom poniższe polecenie. Test podmienia plik dostawcy, sprawdza zmianę wykazu i wycofanie oznaczenia, po czym wycofuje zmiany testowe.

```sh
docker compose -p aed2 -f docker-compose.local.yml -f compose.aed.yml exec rejestr python manage.py testuj_scalanie_aed
```

## Ograniczenia i dostępność

- Stan demonstracyjny obejmuje cztery miasta. Część źródeł podaje tylko adres lub nazwę budynku. Zespół nie prowadził terenowej weryfikacji każdego urządzenia. Liczby na wykresach oznaczają pozycje wykazu. Nierozpoznane jednostki terytorialne tworzą osobną grupę.
- Historia zaczyna się od pierwszej publikacji. Następny pomiar powstaje przy zmianie publicznego CSV lub przypisania do obszarów. Jedna publikacja daje jeden punkt historii.
- Wstępnie załadowane pliki pozwalają czytać dane lokalnie. Zewnętrzne kafelki mapy i nawigacja potrzebują internetu. Domyślnym sposobem logowania w demonstracji jest lokalne konto e-mail mcod. Rzeczywiste logowanie przez login.gov.pl wymaga zarejestrowanej integracji z Węzłem Krajowym i poświadczeń operatora.
- Celem dostępności jest poziom AA WCAG 2.2. W rejestrze sprawdzono m.in. kontrast w trybach użytkownika, powiększenie tekstu oraz układ mobilny o szerokości 320 i 390 px. Dostępne są również tabela i lista wyników. Te próby nie zastępują pełnego audytu wszystkich kryteriów oraz testów z użytkownikami technologii asystujących. [Standard WCAG — W3C](https://www.w3.org/WAI/standards-guidelines/wcag/)

## Pochodzenie i autorstwo

Bazę mcod i portalu Angular dostarczył organizator. Informacje o komponentach Leaflet i użytym godle znajdują się w katalogu `rozwiazanie/frontend/vendor`. Wkład projektu obejmuje m.in. standard danych AED, mechanizm scalania, rejestr, historię publikacji i materiały demonstracyjne. W pracach nad kodem i materiałami wykorzystano AI. Przed wysłaniem zespół powinien przejrzeć końcową wersję i samodzielnie potwierdzić swój wkład oraz prawa do zgłaszanych materiałów z uwzględnieniem warunków komponentów i danych źródłowych. [Kod źródłowy portalu dane.gov.pl](https://dane.gov.pl/source-code/)

