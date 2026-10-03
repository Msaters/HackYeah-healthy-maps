# OpenTripPlanner 2 — szkolenie dla zespołu

Wersja: **OTP 2.10.0** (Docker `opentripplanner/opentripplanner:2.10.0`). Składnię API sprawdzono w schemacie GraphQL tej wersji.

Spis treści:
1. Co to jest i jaką rolę gra u nas
2. Jak OTP działa w środku
3. Pliki, katalogi, komendy
4. Nasza konfiguracja
5. API GraphQL — składnia
6. Gotowe zapytania pod nasze karty
7. Jak czytać odpowiedź (kcal, kroki, mapa)
8. Pułapki
9. Debugowanie
10. Ściąga

---

## 1. Co to jest i jaką rolę gra u nas

OpenTripPlanner (OTP) to serwer open source (Java), który wyznacza trasy multimodalne: pieszo, rowerem, samochodem, komunikacją, wypożyczanym rowerem i ich połączeniami. Dostaje mapę (OSM), rozkłady (GTFS) i opcjonalnie dane na żywo, a wystawia API GraphQL.

**U nas OTP jest silnikiem, a nie produktem.** Podział pracy:

| OTP robi | My robimy (backend) |
|---|---|
| liczy trasy pieszo / rower / KMK / bike&ride / Park-e-Bike | wysyła kilka zapytań z różnymi ustawieniami (kandydaci) |
| uwzględnia opóźnienia KMK na żywo | liczy kcal, kroki, CO₂ z odcinków |
| planuje „na godzinę przyjazdu” | odrzuca trasy, które się spóźnią |
| zwraca odcinki z geometrią i wysokościami | wybiera 3 karty i scala duplikaty |
| | smog, pogoda, ostrzeżenia, cel dzienny |

Frontend nigdy nie gada z OTP bezpośrednio — tylko przez backend.

---

## 2. Jak OTP działa w środku

### Dwie fazy: budowa grafu i serwowanie

```
       BUDOWA (raz, minuty)                         SERWOWANIE (ciągle)
OSM (.pbf) ──┐                                   ┌─ zapytanie GraphQL
GTFS (.zip) ─┼─► graf ulic + przystanki ─► graph.obj ─► routing ─► trasy
DEM (.tif) ──┘   + rozkłady + wysokości                 ▲
                                          dane na żywo ─┘ (GTFS-RT, GBFS co 30–60 s)
```

- **Budowa (`--build --save`)**: OTP czyta OSM i tworzy graf ulic (każdy odcinek drogi z informacją, kto może nim jechać: pieszy, rower, auto). Dokleja przystanki z GTFS do najbliższych ulic, wczytuje rozkłady i — jeśli jest DEM — nadaje odcinkom wysokości (stąd podjazdy). Wynik zapisuje do `graph.obj`.
- **Serwowanie (`--load --serve`)**: wczytuje `graph.obj`, uruchamia updatery danych na żywo i odpowiada na zapytania.

### Jak liczona jest trasa
1. **Dojście / dojazd do przystanków (access)** i **od przystanków do celu (egress)** — wyszukiwanie po grafie ulic (pieszo, rowerem, rowerem z parkowaniem, wypożyczanym rowerem).
2. **Część komunikacyjna** — algorytm **RAPTOR**: przegląda kursy runda po rundzie (runda = kolejna przesiadka). Szybki, bo działa na rozkładach, a nie na grafie.
3. **Trasa bez komunikacji (direct)** — np. cała droga rowerem.
4. **Koszt uogólniony (generalized cost)** — OTP nie minimalizuje czasu, tylko „koszt”:
   - sekunda jazdy KMK ≈ 1,
   - sekunda chodzenia × `walk.reluctance` (domyślnie 2.0),
   - sekunda jazdy rowerem × `bicycle.reluctance` (domyślnie 2.0),
   - + kara za każde wejście do pojazdu (`boardCost`), przesiadki, czekanie.
   
   **Dlatego OTP z natury unika chodzenia i roweru.** Żeby dostać „zdrowe” warianty, obniżamy `reluctance` (np. 0.8) — wtedy minuta ruchu „kosztuje” mniej niż minuta w tramwaju.
5. **Filtrowanie wyników** — OTP usuwa trasy podobne do siebie i wyraźnie „droższe” od najlepszej. Skutek: w jednym zapytaniu rzadko dostaniesz i tramwaj, i długi spacer. **Dlatego robimy osobne zapytania na każdy rodzaj karty** (sekcja 6).

### Dane na żywo
Updatery w `router-config.json` co 30–60 s pobierają:
- **TripUpdates** — opóźnienia; OTP przesuwa czasy kursów,
- **VehiclePositions** — pozycje pojazdów,
- **ServiceAlerts** — komunikaty (trafiają do `legs.alerts`),
- **GBFS** — stacje i dostępne rowery (u nas Park-e-Bike z naszego backendu).

---

## 3. Pliki, katalogi, komendy

### Katalog bazowy `otp/` (w Dockerze widziany jako `/var/opentripplanner`)

| Plik | Co to | W repo? |
|---|---|---|
| `build-config.json` | co wczytać przy budowie (OSM, GTFS, DEM, zakres dat) | tak |
| `router-config.json` | ustawienia serwera: domyślne parametry tras, updatery na żywo | tak |
| `otp-config.json` | flagi funkcji (opcjonalny, u nas brak) | — |
| `download.sh` | pobranie danych wejściowych | tak |
| `krakow.osm.pbf` | mapa | nie (.gitignore) |
| `krk-a.gtfs.zip`, `krk-t.gtfs.zip` | rozkłady autobusów i tramwajów | nie |
| `dem_*.tif` | wysokości | nie |
| `graph.obj` | zbudowany graf | nie |

**Zmiana `build-config.json` lub danych → trzeba przebudować graf.**
**Zmiana `router-config.json` → wystarczy restart serwera.**

### Komendy

```bash
# 1. dane (raz)
./otp/download.sh

# 2. budowa grafu (raz, kilka–kilkanaście minut)
docker run --rm -e JAVA_TOOL_OPTIONS=-Xmx6g \
  -v "$PWD/otp:/var/opentripplanner" \
  opentripplanner/opentripplanner:2.10.0 --build --save

# 3. serwer (przy każdym starcie, ~kilkadziesiąt sekund)
docker run --rm -p 8080:8080 --add-host=host.docker.internal:host-gateway \
  -e JAVA_TOOL_OPTIONS=-Xmx6g \
  -v "$PWD/otp:/var/opentripplanner" \
  opentripplanner/opentripplanner:2.10.0 --load --serve
```

Przydatne flagi:
- `--buildStreet` + `--loadStreet`: zbuduj osobno sam graf ulic (wolne), potem szybko dokładaj tylko rozkłady. Opłaca się, gdy często zmieniamy GTFS.
- `--port 8081`: inny port.

Serwer jest gotowy, gdy w logach przestaną przybywać komunikaty o wczytywaniu, a `http://localhost:8080/` się otwiera.

---

## 4. Nasza konfiguracja

### `build-config.json`
- `osm`: `krakow.osm.pbf`
- `transitFeeds`: dwa GTFS z identyfikatorami **`krk-a`** (autobusy) i **`krk-t`** (tramwaje)
- `dem`: 4 kafelki Copernicus 30 m
- `transitServiceStart/End`: `-P7D` / `P30D` — rozkłady od tygodnia wstecz do 30 dni naprzód (mniej danych = szybciej)

### `router-config.json`
- `routingDefaults`: chód 1.33 m/s (~4.8 km/h), rower 4.5 m/s (~16 km/h), domyślnie 5 tras
- updatery: TripUpdates / VehiclePositions / ServiceAlerts dla `krk-a` i `krk-t`, GBFS Park-e-Bike (`network: park-e-bike`) z `http://host.docker.internal:8000/gbfs/gbfs.json`

**`feedId` w updaterach musi być identyczny jak w `build-config.json`** — inaczej opóźnienia nie dopasują się do kursów.

### Fakty o danych KMK
- GTFS tramwajowy obowiązuje od 2.10 do 30.12.2026.
- ZTP nie publikuje kolumny `bikes_allowed`, ale regulamin KMK pozwala bezpłatnie przewozić rower (z biletem, gdy jest miejsce). `otp/patch_gtfs_bikes.py` (uruchamiany przez `download.sh`) dopisuje `bikes_allowed=1` do wszystkich kursów → działa „rower w tramwaju” (`access/egress/transfer: [BICYCLE]`).
- Identyfikatory w OTP mają prefiks feedu: przystanek `krk-t:stop_123`, linia `krk-t:route_4`.

---

## 5. API GraphQL — składnia

- Endpoint: `POST http://localhost:8080/otp/gtfs/v1`, body `{"query": "...", "variables": {...}}`
- Konsola do testowania z podpowiedziami: **http://localhost:8080/graphiql**
- Mapa do podglądu tras (debug UI): **http://localhost:8080/**

### Zapytanie `planConnection` — najważniejsze argumenty

```graphql
planConnection(
  origin:      { location: { coordinate: { latitude: 50.0720, longitude: 20.0370 } }, label: "Nowa Huta" }
  destination: { location: { coordinate: { latitude: 50.0647, longitude: 19.9234 } }, label: "AGH" }

  dateTime: { latestArrival: "2026-10-05T09:00:00+02:00" }   # albo earliestDeparture: "...", nie oba naraz

  modes: {
    direct: [BICYCLE]                    # trasa bez komunikacji: WALK | BICYCLE | BICYCLE_RENTAL | BICYCLE_PARKING | CAR ...
    directOnly: false                    # true = tylko trasy bez komunikacji
    transitOnly: false                   # true = tylko trasy z komunikacją
    transit: {
      access:   [WALK]                   # dojście do pierwszego przystanku: WALK | BICYCLE | BICYCLE_PARKING | BICYCLE_RENTAL ...
      egress:   [WALK]                   # od ostatniego przystanku: WALK | BICYCLE | BICYCLE_RENTAL ...
      transfer: [WALK]                   # przesiadki: WALK | BICYCLE
      transit:  [{ mode: TRAM }, { mode: BUS }]
    }
  }

  preferences: {
    street: {
      walk:    { speed: 1.33, reluctance: 2.0 }
      bicycle: {
        speed: 4.5
        reluctance: 2.0
        optimization: { type: SAFE_STREETS }    # SAFE_STREETS | FLAT_STREETS | SHORTEST_DURATION
        # albo: optimization: { triangle: { safety: 0.5, flatness: 0.3, time: 0.2 } }   (suma = 1)
        rental: {
          allowedNetworks: ["park-e-bike"]
          destinationBicyclePolicy: { allowKeeping: true }   # rower zostaje przy tobie u celu
        }
      }
    }
  }

  via: [{ visit: { label: "Rondo Mogilskie", coordinate: { latitude: 50.0657, longitude: 19.9590 } } }]
  first: 5                               # ile tras zwrócić
  searchWindow: "PT1H"                   # okno wyszukiwania (opcjonalne)
) { ... }
```

Uwagi do składni:
- `access`/`egress` z rowerem: `BICYCLE` jako egress działa tylko, jeśli access i transfer też są `BICYCLE` (rower jedzie z tobą w pojeździe; wymaga `bikes_allowed` — dopisuje je `patch_gtfs_bikes.py`). Rower zostawiony przy przystanku: **`BICYCLE_PARKING`** jako access (bike&ride).
- Dla rowerów z wypożyczalni podawaj sam tryb rental, bez `WALK` (dojście pieszo OTP dołoży sam).
- Czasy w formacie ISO z **przesunięciem strefy**: do 25.10.2026 `+02:00`, potem `+01:00`. Najlepiej generować w kodzie z `zoneinfo("Europe/Warsaw")`.

### Pola odpowiedzi, których używamy

```graphql
{
  routingErrors { code description }
  edges {
    node {                                   # Itinerary = jedna trasa
      start end duration                     # ISO, ISO, sekundy
      walkDistance walkTime                  # metry, sekundy
      elevationGained elevationLost          # metry (wymaga DEM)
      numberOfTransfers
      legs {                                 # odcinki
        mode                                 # WALK | BICYCLE | TRAM | BUS ...
        duration distance                    # sekundy, metry
        start { scheduledTime estimated { time delay } }
        end   { scheduledTime estimated { time delay } }
        from { name lat lon }
        to   { name lat lon }
        route { shortName }                  # numer linii, np. "4"
        headsign                             # kierunek
        realTime                             # czy czasy uwzględniają dane na żywo
        rentedBike                           # odcinek na wypożyczonym rowerze (Park-e-Bike)
        legGeometry { points }               # polilinia (Google encoded polyline)
        steps { streetName distance elevationProfile { distance elevation } }
        alerts { alertHeaderText }
      }
    }
  }
}
```

---

## 6. Gotowe zapytania pod nasze karty

Wszystkie z `dateTime: { latestArrival: <termin> }`. Backend wysyła je **równolegle**, zbiera wszystkie trasy w jedną pulę kandydatów i dopiero wtedy wybiera karty.

| Kandydat | `modes` | `preferences` | Dla karty |
|---|---|---|---|
| K1 komunikacja | `transit: { access:[WALK], egress:[WALK], transfer:[WALK] }` | domyślne | Najszybsza |
| K2 rower całość | `direct:[BICYCLE], directOnly:true` | `bicycle.optimization: SAFE_STREETS` | Cel kaloryczny |
| K3 bike&ride | `transit: { access:[BICYCLE_PARKING], egress:[WALK] }` | `bicycle.reluctance: 1.0` | Cel kaloryczny |
| K4 Park-e-Bike | `direct:[BICYCLE_RENTAL]`, `transit: { access:[BICYCLE_RENTAL], egress:[BICYCLE_RENTAL] }` | `rental: { allowedNetworks:["park-e-bike"], destinationBicyclePolicy:{ allowKeeping:true } }` | Cel kaloryczny |
| K5 pieszo całość | `direct:[WALK], directOnly:true` | — | Cel kroków |
| K6 dużo chodzenia + KMK | `transit: { access:[WALK], egress:[WALK] }` | `walk.reluctance: 0.8`, `walk.speed: 1.45` | Cel kroków |
| K7 wysiadka wcześniej | jak K1 + `via: [{ visit: { coordinate: <przystanek 2 przed celem> } }]` | `walk.reluctance: 0.8` | Cel kroków |

Potem:
1. odrzuć trasy z `end` > termin − 3 min,
2. Najszybsza = najpóźniejszy `start` (najkrócej w drodze) spośród wszystkich,
3. Cel kaloryczny = max kcal, Cel kroków = max kroków,
4. scal karty z tą samą trasą (porównaj listę `mode` + `route.shortName` odcinków).

### Przykład w Pythonie (K1)

```python
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

OTP = "http://localhost:8080/otp/gtfs/v1"

QUERY = """
query Plan($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
           $arriveBy: OffsetDateTime!, $modes: PlanModesInput, $prefs: PlanPreferencesInput) {
  planConnection(origin: $from, destination: $to,
                 dateTime: { latestArrival: $arriveBy },
                 modes: $modes, preferences: $prefs, first: 5) {
    routingErrors { code description }
    edges { node {
      start end duration walkDistance elevationGained
      legs { mode duration distance route { shortName } rentedBike
             from { name } to { name } legGeometry { points } }
    } }
  }
}"""

def loc(lat, lon, label):
    return {"label": label, "location": {"coordinate": {"latitude": lat, "longitude": lon}}}

arrive = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Europe/Warsaw")).isoformat()
variables = {
    "from": loc(50.0720, 20.0370, "Nowa Huta"),
    "to": loc(50.0647, 19.9234, "AGH"),
    "arriveBy": arrive,
    "modes": {"transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}},
    "prefs": None,
}
r = httpx.post(OTP, json={"query": QUERY, "variables": variables}, timeout=30)
data = r.json()["data"]["planConnection"]
```

Szybki test z terminala:
```bash
curl -s localhost:8080/otp/gtfs/v1 -H 'Content-Type: application/json' \
  -d '{"query":"{ planConnection(origin:{location:{coordinate:{latitude:50.072,longitude:20.037}}}, destination:{location:{coordinate:{latitude:50.0647,longitude:19.9234}}}, first:2) { edges { node { duration legs { mode route { shortName } } } } } }"}' | jq
```

---

## 7. Jak czytać odpowiedź

### Kalorie i kroki z odcinków

```python
MET = {"WALK": 3.5, "BICYCLE": 7.0, "BICYCLE_RENTAL": 4.0, "TRAM": 1.3, "BUS": 1.3}

def leg_kcal(leg, weight_kg):
    mode = "BICYCLE_RENTAL" if leg["rentedBike"] else leg["mode"]   # Park-e-Bike = e-rower
    return MET.get(mode, 1.3) * weight_kg * leg["duration"] / 3600

def itinerary_steps(it, height_m):
    walk_m = sum(l["distance"] for l in it["legs"] if l["mode"] == "WALK")
    return round(walk_m / (0.415 * height_m))
```
- Podjazdy: `elevationGained` całej trasy albo `steps.elevationProfile` per odcinek — dolicz do kcal rowerowych (np. +MET przy dodatnim nachyleniu). Bez DEM te pola są 0.
- `walkDistance` na poziomie trasy obejmuje też prowadzenie roweru — do kroków lepiej sumować odcinki `WALK`.

### Mapa
- `legGeometry.points` to **encoded polyline** (format Google). Dekodowanie: Python `polyline.decode(points)` (pakiet `polyline`), JS `@mapbox/polyline`. Uwaga: zwraca `[lat, lon]`, a MapLibre/GeoJSON chce `[lon, lat]`.
- Kolor odcinka wg `mode`, numer linii z `route.shortName`.

### Czasy i opóźnienia
- `start.scheduledTime` = z rozkładu, `start.estimated.time` = z danymi na żywo (jeśli są), `estimated.delay` np. `"PT2M"`.
- Na karcie pokazuj czas szacowany, jeśli jest, i oznaczenie „na żywo” (`realTime: true`).

---

## 8. Pułapki

| Problem | Przyczyna | Co robić |
|---|---|---|
| Pusta lista tras, `routingErrors: NO_TRANSIT_CONNECTION` / `OUTSIDE_SERVICE_PERIOD` | data spoza `transitServiceStart/End` albo spoza ważności GTFS | sprawdź datę zapytania i zakres w `build-config.json` |
| `WALKING_BETTER_THAN_TRANSIT` (brak tras z KMK) | cel blisko — pieszo wychodzi lepiej niż komunikacją | to nie błąd: pokaż trasę pieszą / rowerową |
| `LOCATION_NOT_FOUND`, `OUTSIDE_BOUNDS` | punkt poza mapą (przycięty OSM) albo w środku budynku/rzeki | punkty w obrębie Krakowa, przyciągaj do ulicy |
| Trasa o godzinę za wcześnie / za późno | czas bez strefy albo zła strefa (+01 vs +02) | zawsze `ZoneInfo("Europe/Warsaw")` |
| Brak opóźnień mimo updaterów | `feedId` w router-config ≠ build-config | ujednolić `krk-a` / `krk-t` |
| Nigdy nie ma Park-e-Bike | backend GBFS nie działa / zły `network` / brak `allowKeeping` | sprawdź logi OTP i `allowedNetworks` |
| Brak „roweru w tramwaju” (`NO_TRANSIT_CONNECTION`) | GTFS bez `bikes_allowed` | `python3 otp/patch_gtfs_bikes.py` + przebudowa grafu |
| `BIKE_RENTAL needs to be combined with WALK` | sam `BICYCLE_RENTAL` w access/egress | podaj `[WALK, BICYCLE_RENTAL]`; działa tylko z uruchomionym feedem GBFS |
| Wszystkie trasy to tramwaj, mimo że chcę ruch | domyślne `reluctance` = 2.0 + filtr wyników | osobne zapytania z niższym `reluctance` (sekcja 6) |
| `elevationGained` = 0 | DEM nie wczytany | sprawdź `dem` w build-config i logi budowy |
| OutOfMemory przy budowie | za mało RAM dla całej Małopolski | `osmium extract` do Krakowa, `-Xmx6g` |
| Długi start serwera | normalne przy dużym grafie | `--buildStreet`/`--loadStreet`, nie przebudowuj bez potrzeby |
| Pobieranie GTFS się urywa | niestabilny serwer ZTP | `download.sh` wznawia i sprawdza archiwa; trzymaj kopię |

---

## 9. Debugowanie

1. **Mapa debug (http://localhost:8080/)** — klikasz start i cel, wybierasz tryby, widzisz trasy na mapie. Pierwsze miejsce, gdy „coś nie tak z trasą”.
2. **GraphiQL (http://localhost:8080/graphiql)** — pisanie zapytań z podpowiedziami i dokumentacją schematu (przycisk „Docs”). Tu najpierw testuj zapytanie, potem przenoś do kodu.
3. **Logi kontenera** — przy budowie: ile przystanków dołączono, czy wczytano DEM; przy serwowaniu: błędy updaterów (np. GBFS niedostępny).
4. **`itineraryFilter: { itineraryFilterDebugProfile: LIST_ALL }`** w `planConnection` — pokazuje także trasy, które filtr by usunął. Przydatne, gdy „zdrowy” wariant znika.

---

## 10. Ściąga

```text
Budowa grafu   docker run ... --build --save        (po zmianie danych / build-config)
Serwer         docker run ... -p 8080:8080 --load --serve
API            POST localhost:8080/otp/gtfs/v1      query planConnection
Konsola        localhost:8080/graphiql
Mapa debug     localhost:8080/

Na godzinę     dateTime: { latestArrival: "2026-10-05T09:00:00+02:00" }
Tylko rower    modes: { direct:[BICYCLE], directOnly:true }
Bike&ride      modes: { transit:{ access:[BICYCLE_PARKING], egress:[WALK] } }
Park-e-Bike    modes: { direct:[BICYCLE_RENTAL] } + rental.destinationBicyclePolicy.allowKeeping:true
Więcej ruchu   preferences.street.walk.reluctance: 0.8 / bicycle.reluctance: 1.0
Przez punkt    via: [{ visit: { coordinate: {...} } }]
Bezpieczniej   bicycle.optimization: { type: SAFE_STREETS }
```

Dokumentacja: https://docs.opentripplanner.org/en/latest/ — sekcje *Basic Tutorial*, *Build Configuration*, *Router Configuration*, *GBFS Config*, *RouteRequest*.

---

## 11. Wyniki pierwszego uruchomienia (3.10.2026)

- Budowa grafu: **~2 min**, 3336 przystanków, 382 tys. węzłów, `graph.obj` 182 MB. Start serwera: ~30 s.
- Wszystkie 7 updaterów działają; trasy na dziś mają `realTime: true` (opóźnienia KMK).
- Ostrzeżenia `NEGATIVE_DWELL_TIME` / `NO_SERVICE_ON_DATE` z TripUpdates są normalne (błędy w danych ZTP) — ignorować.
- Ostrzeżenie „Elevation is missing at a large number of points” — normalne, każdy kafelek DEM pokrywa tylko część obszaru; wysokości działają (`↑72 m` dla roweru Nowa Huta → AGH).
- **Bike&ride wymaga `"staticBikeParkAndRide": true`** w `build-config.json` (import 4876 stojaków z OSM). Bez tego `BICYCLE_PARKING` zwraca `NO_STOPS_IN_RANGE`.
- **Wniosek produktowy:** samo `latestArrival` przepuszcza absurdalne trasy (np. 110 min pieszo zamiast 42 min tramwajem — też „zdąży”). Backend musi ograniczać czas wyjścia: np. trasa najwyżej o X min dłuższa od najszybszej albo „wychodzę nie wcześniej niż …”.

### Jak testować
```bash
python3 otp/smoke_test.py                              # poniedziałek 9:00, rozkład
python3 otp/smoke_test.py --arrive 2026-10-03T18:00    # dziś — z danymi na żywo
```
Ręcznie: mapa http://localhost:8080/ (klik start/cel, wybór trybów) i konsola http://localhost:8080/graphiql.

Zarządzanie kontenerem: `docker logs -f otp`, `docker stop otp`, `docker start otp`.

---

## 12. Własne wagi

**Zasada:** wagi do strojenia ustawiamy w zapytaniu (`preferences`, `modes.transit.transit[].cost`) — działa od razu. Do `router-config.json` → `routingDefaults` przenosimy tylko ustalone wartości domyślne (wymaga `docker restart otp`).

### W zapytaniu (sprawdzone na serwerze 2.10, introspekcja)
| Ścieżka w `planConnection` | Domyślnie | Znaczenie |
|---|---|---|
| `preferences.street.walk.reluctance` | 2.0 | mnożnik kosztu sekundy chodzenia (niżej = więcej chodzenia) |
| `preferences.street.walk.speed` | 1.35 m/s | prędkość marszu |
| `preferences.street.walk.boardCost` | 600 | kara za każde wejście do pojazdu (w sekundach) |
| `preferences.street.walk.safetyFactor` | 1.0 | 0 = najkrócej, 1 = najbezpieczniej |
| `preferences.street.bicycle.reluctance` | 2.0 | mnożnik kosztu sekundy jazdy rowerem |
| `preferences.street.bicycle.speed` | 5.0 m/s | prędkość roweru |
| `preferences.street.bicycle.optimization` | `SAFE_STREETS` | `SAFE_STREETS` / `FLAT_STREETS` / `SHORTEST_DURATION` albo `triangle: {safety, flatness, time}` (suma 1) |
| `preferences.street.bicycle.boardCost` | 600 | kara za wejście do pojazdu z rowerem |
| `preferences.transit.board.waitReluctance` | 1.0 | mnożnik kosztu czekania na przystanku |
| `preferences.transit.transfer.cost` | 0 | dodatkowa kara za przesiadkę (sekundy) |
| `preferences.transit.transfer.slack` | `PT2M` | minimalny czas na przesiadkę |
| `preferences.transit.transfer.maximumTransfers` | 11 | maks. liczba przesiadek |
| `modes.transit.transit: [{mode: BUS, cost: {reluctance: 1.3}}]` | 1.0 | mnożnik kosztu jazdy danym trybem (tu: autobus „gorszy” od tramwaju) |

Przykład (przetestowany): mniej przesiadek, chodzenie tańsze, autobus mniej lubiany:
```graphql
preferences: {
  street:  { walk: { reluctance: 1.0, boardCost: 300, speed: 1.4 } }
  transit: { transfer: { cost: 120, slack: "PT3M", maximumTransfers: 2 }, board: { waitReluctance: 1.5 } }
}
modes: { transitOnly: true, transit: { access: [WALK], egress: [WALK], transfer: [WALK],
         transit: [{ mode: TRAM }, { mode: BUS, cost: { reluctance: 1.3 } }] } }
```
Dodaj `generalizedCost` do pól trasy, żeby widzieć efekt wag. Uwaga: OTP **sortuje po czasie, nie po koszcie** — trasa z najniższym `generalizedCost` nie musi być pierwsza.

### Domyślne na serwerze (`otp/router-config.json`)
```json
"routingDefaults": {
  "walk":    { "speed": 1.33, "reluctance": 2.0, "boardCost": 600 },
  "bicycle": { "speed": 4.5, "reluctance": 2.0, "optimization": "safe-streets" },
  "waitReluctance": 1.0,
  "transferPenalty": 0,
  "transferSlack": "PT2M",
  "itineraryFilters": { "nonTransitGeneralizedCostLimit": "1h + 2.0 t" }
}
```
Po zmianie: `docker restart otp` (~30 s).
