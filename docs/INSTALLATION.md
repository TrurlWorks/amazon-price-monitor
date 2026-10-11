# Amazon Price Monitor 0.8.4 — instalacja i obsługa

## Wymagania

- Linux lub inne środowisko obsługujące Docker Engine i Docker Compose v2
- Git
- Wolny port TCP 8080 (lub inny wskazany w `.env`)
- Lokalny dysk na bazę SQLite i obrazy Docker

## Pobieranie

Na stronie repozytorium GitHub kliknij **Code → HTTPS** i skopiuj adres. Sklonuj projekt za pomocą `git clone <adres-repozytorium>`, a następnie przejdź do katalogu `amazon-price-monitor`.

## Pierwsze uruchomienie

Utwórz prywatną konfigurację:

```sh
cp .env.example .env
```

Sprawdź ustawienia `.env`, zwłaszcza:

| Zmienna | Znaczenie |
| --- | --- |
| `HTTP_PORT` | Port udostępnianego interfejsu |
| `BIND_ADDRESS` | Adres lokalnego interfejsu, na którym publikowany jest port |
| `PRODUCT_PROVIDER` | `mock` (testy offline) lub `amazon_page` |
| `MONITOR_MOCK_SCENARIO` | Scenariusz danych testowych |
| `POLL_INTERVAL_SECONDS` | Odstęp kontroli cen |
| `FAILED_RETRY_SECONDS` | Podstawowy odstęp ponowień po błędach |
| `QUEUE_GAP_SECONDS` | Minimalny odstęp startów zadań kolejki |

Na początek zalecany jest `PRODUCT_PROVIDER=mock`. Wartości dostarczone w `.env.example` mogą być inne i trzeba je świadomie sprawdzić.

Uruchom:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Domyślny adres na komputerze uruchamiającym Docker to **http://localhost:8080**. Dla innego urządzenia w zaufanej sieci LAN skonfiguruj `BIND_ADDRESS` oraz zaporę sieciową. Program nie ma uwierzytelniania ani wbudowanego HTTPS: **nie wystawiaj go bezpośrednio do internetu**.

## Diagnostyka

```sh
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 worker
docker compose logs --tail=100 web
docker compose logs --tail=100 migrate
```

Na początku usługi `data-init` i `migrate` mogą zakończyć pracę kodem 0 — to normalne dla usług jednorazowych. API, web i worker powinny pozostać uruchomione.

## Zatrzymanie

```sh
docker compose down
```

Nie dodawaj `-v` bez świadomej decyzji. Dane SQLite znajdują się w lokalnym katalogu `data/` i nie powinny być publikowane w Git.

## Kopia zapasowa

Przed aktualizacją zatrzymaj usługi poleceniem `docker compose down`, po czym skopiuj w prywatne miejsce **cały katalog `data/` oraz `.env`**. To zapobiega niespójnym kopiom aktywnej bazy w trybie WAL. Nie przesyłaj tych plików do publicznego repozytorium.

## Aktualizacja

W sklonowanym repozytorium wykonaj kopię zapasową, a następnie:

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

Po aktualizacji sprawdź logi migracji i stan usług. Migracje na nowej bazie przetestowano do rewizji `0008`; aktualizację bazy zawierającej własne dane należy poprzedzić kopią zapasową.

## Ograniczenia

Bezpośrednie pobieranie informacji ze stron Amazon.pl może być blokowane lub ograniczone regulaminowo. Program nie omija CAPTCHA i nie gwarantuje ciągłości pomiarów ani zgodności cen z ofertami spersonalizowanymi. Przed korzystaniem z providera `amazon_page` zapoznaj się z aktualnymi zasadami źródła danych.
