# OTP — uruchomienie krok po kroku

Wszystkie komendy z katalogu repo:
```bash
cd ~/HY2026/HackYeah-healthy-maps
```

## 0. Jednorazowo: Docker bez sudo
```bash
docker run --rm hello-world
```
Jeśli `permission denied`:
```bash
sudo usermod -aG docker $USER
```
potem wyloguj się i zaloguj (albo w tym terminalu: `newgrp docker`).

## 1. Jednorazowo: pobranie danych (~250 MB)
```bash
./otp/download.sh
```
Na końcu wypisze listę plików: `krakow.osm.pbf`, `krk-a.gtfs.zip`, `krk-t.gtfs.zip`, 4× `dem_*.tif`.

## 2. Budowa grafu (~2 min; tylko po zmianie danych lub `build-config.json`)
```bash
docker run --rm -e JAVA_TOOL_OPTIONS=-Xmx8g \
  -v "$PWD/otp:/var/opentripplanner" \
  opentripplanner/opentripplanner:2.10.0 --build --save
```
Sukces: na końcu `Graph written: graph.obj`, a w `otp/` jest `graph.obj` (~180 MB).

## 3. Start serwera
```bash
docker run -d --name otp -p 8080:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e JAVA_TOOL_OPTIONS=-Xmx6g \
  -v "$PWD/otp:/var/opentripplanner" \
  opentripplanner/opentripplanner:2.10.0 --load --serve
```
Poczekaj ~30 s i sprawdź logi:
```bash
docker logs -f otp
```
Gotowe, gdy pojawi się `OTP 2.10.0 is ready for routing!` (wyjście z logów: Ctrl+C — serwer działa dalej).

Błąd `Conflict. The container name "/otp" is already in use` → serwer już istnieje, wystarczy `docker start otp`.

## 4. Test
```bash
python3 otp/smoke_test.py                              # przyjazd w poniedziałek 9:00 (rozkład)
python3 otp/smoke_test.py --arrive 2026-10-03T18:00    # dziś — z opóźnieniami na żywo
```
Każdy scenariusz powinien mieć ✓ i 1–3 trasy. Oznaczenie „na żywo” = działają dane GTFS-RT.

## 5. Przeglądarka (na tym samym komputerze)
- Mapa: **http://localhost:8080/** — zaznacz na mapie start i cel (kliknięcie / menu pod prawym przyciskiem), ustaw tryby i godzinę w panelu wyszukiwania.
- Konsola zapytań: **http://localhost:8080/graphiql** — wklej zapytanie, uruchom ▶, przycisk „Docs” = dokumentacja API.

Zawsze z `http://` i portem `:8080`.

Szybki test bez przeglądarki:
```bash
curl -s localhost:8080/otp/gtfs/v1 -H 'Content-Type: application/json' \
  -d '{"query":"{ planConnection(origin:{location:{coordinate:{latitude:50.0717,longitude:20.0373}}}, destination:{location:{coordinate:{latitude:50.0663,longitude:19.9232}}}, first:1) { edges { node { duration legs { mode route { shortName } } } } } }"}'
```

## 6. Codzienna obsługa
| Co | Komenda |
|---|---|
| zatrzymaj | `docker stop otp` |
| uruchom ponownie | `docker start otp` |
| logi | `docker logs -f otp` |
| po przebudowie grafu | `docker rm -f otp`, potem krok 3 |
| po zmianie `router-config.json` | `docker restart otp` |
| czy działa | `docker ps` (status `Up`) |

## 7. Gdy nie działa
| Objaw | Przyczyna / rozwiązanie |
|---|---|
| przeglądarka: „nie można połączyć” | brak `:8080` lub `https://` zamiast `http://`; `docker ps` — czy `otp` jest `Up` |
| `docker ps` nie pokazuje `otp` | `docker start otp` albo krok 3 |
| biała strona na `localhost:8080` | mapa ładuje skrypty z internetu — sprawdź sieć / bloker; `graphiql` działa niezależnie |
| smoke test: `Connection refused` | serwer jeszcze startuje — poczekaj 30 s |
| smoke test: `NO_STOPS_IN_RANGE` przy bike&ride | brak `staticBikeParkAndRide: true` w `build-config.json` → przebuduj graf (krok 2) |
| `OutOfMemoryError` | zamknij inne programy albo zmniejsz `-Xmx` |

Szczegóły i składnia API: `docs/OTP.md`.
