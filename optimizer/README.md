# optimizer — profile wag OTP z algorytmu genetycznego (NSGA-II)

Algorytm genetyczny NSGA-II przeszukuje wagi zapytania OpenTripPlannera (`modes` + `preferences` w `planConnection`) i przybliża front Pareto dwóch celów: **czas przejazdu (min)** i **aktywne kcal (max)**. Warunek: trasa nie może być dużo dłuższa od najszybszej trasy komunikacją. Z frontu wybieramy 3 gotowe profile wag (**fast / balanced / active**) oraz **suwak „czas ↔ ruch”** (7 ząbków wzdłuż frontu), które backend wkleja do zapytań OTP. Liczymy je offline, raz — osobno dla użytkownika **z rowerem** (`bike`) i **bez roweru** (`walk`). Szczegóły projektu (genom, kryteria, ograniczenie, pary OD, budżety) są w [DESIGN.md](DESIGN.md).

## Wymagania

- Python 3.12 + `numpy` (poza tym tylko biblioteka standardowa).
- Działający OTP 2 pod `http://localhost:8080/otp/gtfs/v1`, uruchomiony według [docs/OTP_QUICKSTART.md](../docs/OTP_QUICKSTART.md). Bez OTP działają tylko testy jednostkowe, a test integracyjny jest pomijany.
- Wszystkie komendy uruchamiamy z katalogu głównego repo.

## Struktura

| Plik | Rola |
|---|---|
| `genome.py` | genom `x ∈ [0,1]^12` (10 wspólnych + 2 geny tylko dla `walk`) → `decode(x)` = zmienne GraphQL `{modes, preferences}` |
| `nsga2.py` | rdzeń NSGA-II: dominacja z ograniczeniem (Deb), sortowanie frontów, crowding, SBX, mutacja, hypervolume |
| `evaluate.py` | klient OTP (wątki + cache JSONL), metryki tras (kcal, kroki), baseline KMK, kara `cv` |
| `od_pairs.json` | 10 par źródło–cel w Krakowie (4 z nich w trybie quick) |
| `run_ga.py` | CLI: przebieg GA → `front.json`, `profiles.json`, `slider.json`, raport |
| `profiles.py` | deduplikacja i filtr niezdominowanych punktów frontu, wybór profili fast/balanced/active |
| `report.py` | wykres `front.svg` i tabela `front.md` (np. na slajd) |
| `slider.py` | suwak offline: `front.json` → `slider.json` (7 ząbków po długości łuku, scalanie bliskich punktów) |
| `slider_select.py` | suwak online dla jednej trasy (biblioteka backendu + CLI demo) |
| `slider_eval.py` | ocena suwaka na parach spoza treningu |
| `tests/` | testy `unittest`; `test_integration_otp.py` wymaga działającego OTP |

Pełna mapa plików: [PLIKI.md](PLIKI.md).

## Komendy

```bash
# wszystkie testy (test integracyjny jest pomijany, gdy OTP nie odpowiada; ~35 s, gdy odpowiada)
python3 -m unittest discover -s optimizer/tests -t . -v

# sam test integracyjny (pełny pipeline quick w katalogu tymczasowym); inny OTP: OTP_URL=...
python3 -m unittest optimizer.tests.test_integration_otp -v

# tryb quick, dwa warianty: pop=12, gen=4, 4 pary, ~240 zapytań, ~20-30 s na zimno, < 1 s z ciepłym cache
python3 -m optimizer.run_ga --mode quick --seed 1 --variant bike --out optimizer/out/quick_bike
python3 -m optimizer.run_ga --mode quick --seed 1 --variant walk --out optimizer/out/quick_walk

# inna liczba ząbków suwaka, bez kotwicy K1 w populacji startowej
python3 -m optimizer.run_ga --mode quick --seed 1 --variant bike --ticks 5 --no-anchor --out optimizer/out/quick_bike5

# tryb full: pop=24, gen=12, 10 par, ~3100 zapytań, ~15 min
python3 -m optimizer.run_ga --mode full --seed 1 --variant bike --out optimizer/out/full_bike \
    --cache optimizer/out/full_bike/otp_cache.jsonl

# suwak offline z istniejącego frontu (run_ga robi to sam; to do ponownego przeliczenia, np. z innym ε scalania)
python3 -m optimizer.slider optimizer/out/quick_bike/front.json --n 7 --variant bike --out optimizer/out/quick_bike/slider.json

# raport (SVG + MD) z istniejącego frontu; slider.json obok front.json jest dołączany automatycznie
python3 -m optimizer.report optimizer/out/quick_bike/front.json [--profiles PATH] [--out DIR]

# suwak dla jednej trasy na żywym OTP (wymaga OTP; nowa_huta_agh z od_pairs.json)
python3 -m optimizer.slider_select --slider optimizer/out/quick_bike/slider.json --pair nowa_huta_agh
# ... ze smogiem (pozycje s > 0.5 zablokowane, domyślnie czysta komunikacja)
python3 -m optimizer.slider_select --slider optimizer/out/quick_bike/slider.json --pair nowa_huta_agh --lock smog
# ... dowolna trasa i termin
python3 -m optimizer.slider_select --slider optimizer/out/quick_walk/slider.json \
    --from 50.0617,19.9373 --to 50.0663,19.9232 --deadline 2026-10-05T08:30:00+02:00

# ocena suwaka na 6 parach spoza quick (OTP rozgrzany; ~10 s)
python3 -m optimizer.slider_eval --slider optimizer/out/quick_bike/slider.json --pairs held-out \
    --out optimizer/out/quick_bike/slider_eval.json
python3 -m optimizer.slider_eval --slider optimizer/out/quick_walk/slider.json --pairs held-out \
    --out optimizer/out/quick_walk/slider_eval.json
```

- **Trybu full nie uruchamialiśmy w ramach projektu** (decyzja zespołu: liczy się projekt algorytmu, a nie wynik obliczeń). Jeśli ktoś go puści, niech zachowa **plik cache razem z wynikiem**. OTP uruchomiony na zimno nie jest w 100% deterministyczny (ok. 1 na 150 odpowiedzi się różni), więc identyczny wynik da się odtworzyć tylko z tego samego cache.
- Domyślny cache to `optimizer/cache/otp_cache.jsonl`. `--no-cache` go wyłącza, a `--cache PATH` wskazuje inny plik. Przy ciepłym cache przebieg quick trwa < 1 s.
- Flagi `run_ga`: `--variant bike|walk` (domyślnie `bike`; `walk` = użytkownik bez roweru, żadna trasa nie ma `BICYCLE`), `--ticks N` (liczba ząbków, domyślnie 7), `--no-anchor` (bez kotwicy K1), `--workers K` (10 równoległych zapytań), `--pop`/`--gens` (nadpisują tryb), `--url`, `--pairs`, `--no-report`.
- `slider_select`: `--pair ID` albo `--from lat,lon --to lat,lon --deadline ISO`, `--lock smog|weather`, `--buffer MIN` (bufor przed terminem, domyślnie 3), `--json PATH` (zapis wyniku). Domyślnie bez cache; kod wyjścia 2, gdy OTP nie odpowiada.
- `slider_eval`: `--pairs held-out|all`, `--out PATH`, `--workers`, `--cache` (tylko dla przebiegu jakościowego; pomiar czasu budowy jest zawsze bez cache).
- `optimizer/cache/` i `optimizer/out/` są w `.gitignore`.

## Wyniki (katalog `--out`)

Gotowe wyniki quick leżą w `optimizer/out/quick_bike/` (użytkownik z rowerem) i `optimizer/out/quick_walk/` (bez roweru). Backend wybiera katalog wg przełącznika „mam rower”.

| Plik | Zawartość |
|---|---|
| `front.json` | `{"meta", "front": [...]}`: niezdominowane, dopuszczalne (`cv == 0`) punkty bez duplikatów zapytań, posortowane po czasie. Każdy punkt ma `x`, `query {modes, preferences}`, `f_time_ratio`, `active_kcal`, `steps`, `duration_min`, `cv`, `per_pair`. `meta` zawiera seed, wariant, aktywne geny, baseline'y, historię generacji (HV, cache), liczbę zapytań i `meta.anchor` (metryki kotwicy K1 + `in_front`) |
| `slider.json` | `{"meta", "ticks": [7 × tick]}`: suwak offline; tick = `{s, u, index, modes, preferences, metrics}`. `meta`: `variant`, `distinct` (różne punkty frontu po scaleniu), `merged`, `merge_eps` |
| `profiles.json` | `{"fast"\|"balanced"\|"active": {"modes", "preferences", "metrics"}}`: `fast` ≡ tick 0, `active` ≡ ostatni tick, `balanced` = kolano frontu |
| `slider_eval.json` | wynik `slider_eval` (6 par held-out): `summary` (`monotonic_rate`, `mean_distinct`, `mean_positions`, `build_s_p50`, `build_s_max`, `targets_met`), `per_pair`, `meta` |
| `front.svg` | wykres frontu (oś X: czas względem najszybszej trasy KMK, oś Y: kcal) z ząbkami suwaka i profilami |
| `front.md` | tabele: profile, suwak, punkty frontu, z osadzonym `front.svg` |
| `checkpoint.json` | front po każdej generacji; można go podejrzeć w trakcie długiego przebiegu |

### Smog / zła pogoda: co jest domyślne

Przy blokadzie (`--lock smog|weather`, w backendzie `lock_reason`) pozycje suwaka `s > 0.5` są zablokowane (`[zablok.]`), a domyślna pozycja dobierana jest kolejno: (a) czysta komunikacja (`anchor`) → domyślna; (b) gdy jej brak — najkrótszy spacer (`walk`) jako fallback (etykieta CLI `[fallback pieszo]`, w wyniku pole `fallback`); (c) gdy nie ma ani (a), ani (b) — najmniej aktywna niezablokowana trasa bez roweru, z ostrzeżeniem w `warnings`. Spacer wygrywa z rowerem, bo to krótszy wysiłek i krótsza ekspozycja na zanieczyszczone powietrze; zasada z CLAUDE.md „smog → nie promować roweru/spaceru” oznacza, że spacer jest domyślny tylko wtedy, gdy nie ma komunikacji (np. bardzo krótka trasa Rynek → AGH). Przykłady: `out/smog_demo.txt` (rynek_agh → spacer; nowa_huta_agh → komunikacja; dla porównania bez blokady domyślny jest rower).

## Jak backend ma użyć suwaka (zalecane)

Jeden punkt wejścia: `plan_route_slider` — sam ustawia `arrive_by = termin − bufor`, wysyła 9 zapytań (7 ząbków + `anchor` = czysta komunikacja + `walk` = sam spacer), wybiera z odpowiedzi trasy, które zdążą i mieszczą się w limicie, scala duplikaty i zwraca lokalny mini-front z pozycjami `s ∈ [0, 1]`.

```python
import json

from optimizer.slider_select import plan_route_slider

with open("optimizer/out/quick_bike/slider.json", encoding="utf-8") as f:
    slider = json.load(f)                      # "mam rower" -> quick_bike, inaczej quick_walk

origin = {"lat": 50.0717, "lon": 20.0373, "label": "Nowa Huta, Plac Centralny"}
destination = {"lat": 50.0663, "lon": 19.9232, "label": "AGH"}

rs = plan_route_slider(
    slider, origin, destination, "2026-10-05T09:00:00+02:00",
    lock_reason=None,                          # np. "smog", gdy indeks jakości powietrza jest zły
    # walk_speed=1.4, bike_speed=4.2,          # własne tempo użytkownika [m/s] (opcjonalnie)
    # weight=82.0, height=1.80,                # profil użytkownika: kcal i kroki liczone z jego danych
)
print("default:", rs["default_index"], "| baseline:", rs["baseline_min"], "min | dropped:", rs["dropped"])
for i, p in enumerate(rs["positions"]):
    m = p["metrics"]
    print(i, f'{p["s"]:.2f}', m["duration_min"], "min", m["active_kcal"], "kcal", m["steps"], "steps",
          "slack", m["slack_min"], m["modes"], p["sources"],
          "LOCKED" if p["locked"] else "", "FALLBACK" if p["fallback"] else "")
```

Uruchomione z katalogu głównego repo (`PYTHONPATH=. python3 plik.py`; OTP musi działać) wypisuje dla tej trasy (OTP z 2026-10-03, wynik zależy od grafu):

```text
default: 2 | baseline: 40.5 min | dropped: {'late': 0, 'too_long': 1, 'no_route': 0, 'error': 0, 'duplicate': 2, 'dominated': 2}
0 0.00 34.83 min 104.8 kcal 0 steps slack 8.0 ['BICYCLE', 'TRAM', 'BICYCLE'] ['tick:0', 'tick:1']
1 0.11 36.78 min 128.9 kcal 0 steps slack 8.0 ['BICYCLE', 'TRAM', 'BICYCLE'] ['tick:3']
2 0.84 46.4 min 378.9 kcal 0 steps slack 3.0 ['BICYCLE'] ['tick:4', 'tick:5']
3 1.00 49.7 min 397.7 kcal 0 steps slack 11.0 ['BICYCLE', 'TRAM', 'BICYCLE'] ['tick:6']
```

Poziom niższy (gdy backend ma własny klient HTTP, pulę wątków albo cache) — te same kroki ręcznie:

```python
import json

from optimizer.evaluate import OTPClient
from optimizer.slider_select import (ROUTE_QUERY, build_route_slider, query_arrive_by,
                                     tick_requests)

slider = json.load(open("optimizer/out/quick_walk/slider.json", encoding="utf-8"))
origin = {"lat": 50.0717, "lon": 20.0373}
destination = {"lat": 50.0663, "lon": 19.9232}
deadline = "2026-10-05T09:00:00+02:00"

requests = tick_requests(slider, origin, destination)        # 7 ząbków + "anchor" + "walk" = 9 żądań
client = OTPClient("http://localhost:8080/otp/gtfs/v1", workers=8,
                   arrive_by=query_arrive_by(deadline), query=ROUTE_QUERY)
results = client.plan_many(requests)
rs = build_route_slider(results, requests, deadline, lock_reason="smog")
print(len(requests), "requests ->", len(rs["positions"]), "positions, default", rs["default_index"], rs["dropped"])
```

Dla wariantu `walk` i tej trasy wypisuje: `9 requests -> 2 positions, default 0 {'late': 0, 'too_long': 1, 'no_route': 0, 'error': 0, 'duplicate': 6, 'dominated': 0}`. **Pamiętaj:** klient musi mieć `arrive_by=query_arrive_by(deadline)`, inaczej trasy kończą się tuż przed terminem i wpadają w `late`.

**Pola wyniku:**

| Pole | Znaczenie |
|---|---|
| `positions[]` | trasy uporządkowane po czasie, każda: `s` (współrzędna suwaka 0 = najszybciej … 1 = najwięcej ruchu), `route_key`, `sources` (tagi żądań, które dały tę trasę: `tick:i`, `anchor`, `walk`), `metrics` {`duration_min`, `active_kcal`, `steps`, `end`, `slack_min` = zapas do terminu, `modes`}, `itinerary` (surowa trasa OTP z geometrią, liniami i przystankami — do rysowania), `locked`, `fallback` |
| `s` | pozycja po długości łuku mini-frontu (równy krok = równa zmiana „wrażenia”), 4 miejsca po przecinku |
| `default_index` | pozycja do pokazania na starcie: bez blokady najbliższa `s = 0.5`; przy `lock_reason` — czysta komunikacja |
| `locked` | `True` dla pozycji `s > 0.5`, gdy podano `lock_reason` (smog / pogoda: „nie promować roweru”); UI pokazuje je szare z komunikatem |
| `fallback` | `True` dla trasy KMK dorzuconej przy `lock_reason` na `s = 0` (gdy w mini-froncie była zdominowana przez rower); pozostałe pozycje są wtedy przeskalowane, żeby `s` pozostało posortowane |
| `lock_reason` | echo przekazanej przyczyny blokady |
| `dropped` | liczniki odrzuceń: `late` (nie zdąży przed terminem − bufor), `too_long` (> 190% najszybszej), `no_route`, `error`, `duplicate` (ta sama trasa z kilku żądań), `dominated`; suma pozycji (źródeł) i odrzuceń = liczba żądań |
| `baseline_min` | najszybsza trasa komunikacją (a gdy jej brak — piesza), baza limitu 190% |
| `warnings` | komunikaty diagnostyczne po polsku (OTP niedostępny, błędy części żądań, brak trasy KMK przy blokadzie…) |
| `otp_stats`, `n_requests` | liczniki cache/zapytań i liczba wysłanych żądań |

- **Prędkości użytkownika:** `walk_speed` i `bike_speed` [m/s] podmieniają `walk.speed` / `bicycle.speed` tylko w kopii żądań (slider wejściowy bez zmian). Wagi suwaka były dobrane przy 1,33 / 4,5 m/s; dla mocno innego tempa kolejność ząbków może być nieco inna, ale mini-front i tak jest liczony z realnych tras. `weight` i `height` służą tylko do przeliczenia kcal i kroków (dane zostają lokalnie).
- **Limit wydłużenia:** trasa może trwać najwyżej **190%** najszybszej (`evaluate.MAX_TIME_RATIO = 1.9`), liczone od `baseline_min`.

## Jak backend ma użyć profilu (3 stałe profile, bez suwaka)

Profil to gotowe zmienne `modes` i `preferences` do `planConnection` (składnia: [docs/OTP.md](../docs/OTP.md)):

```python
import json
import urllib.request

OTP = "http://localhost:8080/otp/gtfs/v1"
QUERY = """
query Plan($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
           $arriveBy: OffsetDateTime!, $modes: PlanModesInput, $prefs: PlanPreferencesInput) {
  planConnection(origin: $from, destination: $to, dateTime: { latestArrival: $arriveBy },
                 modes: $modes, preferences: $prefs, first: 3) {
    routingErrors { code description }
    edges { node { start end duration legs { mode duration distance } } }
  }
}"""


def loc(lat, lon, label):
    return {"label": label, "location": {"coordinate": {"latitude": lat, "longitude": lon}}}


with open("optimizer/out/quick_bike/profiles.json", encoding="utf-8") as f:
    profile = json.load(f)["active"]          # "fast" | "balanced" | "active"

prefs = json.loads(json.dumps(profile["preferences"]))   # copy before editing
# Speeds in the profile are constants (1.33 / 4.5 m/s); override with the user's own pace if known.
prefs["street"]["bicycle"]["speed"] = 4.2
prefs["street"]["walk"]["speed"] = 1.4

body = {"query": QUERY, "variables": {
    "from": loc(50.0717, 20.0373, "Nowa Huta, Plac Centralny"),
    "to": loc(50.0663, 19.9232, "AGH"),
    "arriveBy": "2026-10-05T08:30:00+02:00",
    "modes": profile["modes"],
    "prefs": prefs,
}}
req = urllib.request.Request(OTP, data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
plan = json.load(urllib.request.urlopen(req, timeout=60))["data"]["planConnection"]
print(plan["routingErrors"])
for e in plan["edges"]:
    n = e["node"]
    print(n["start"], "->", n["end"], round(n["duration"] / 60), "min",
          [leg["mode"] for leg in n["legs"]])
```

- **Prędkości** `walk.speed` i `bicycle.speed` są w profilu stałe (1,33 i 4,5 m/s), bo GA ich nie optymalizuje. Backend może je nadpisać tempem użytkownika (`walk_speed`, `bike_speed` w `plan_route_slider`, albo ręcznie jak wyżej).
- Profile to **dodatkowe zapytania** obok K1–K7 z [docs/OTP.md](../docs/OTP.md), a nie ich zamiennik. Kandydatów z profili i z K1–K7 łączy backend, który filtruje trasy po terminie przyjazdu i wybiera 3 karty: „Najszybsza”, „Cel kaloryczny” i „Cel kroków”.

## Wyniki quick (seed 1, pop 12 × 4 pokolenia, 4 pary)

To przebieg quick (smoke test), a nie wynik docelowy. Liczby z `out/quick_{bike,walk}/`:

| Wariant | Punkty frontu | `slider.distinct` (po scaleniu ε) | fast: czas × / kcal / kroki | balanced | active |
|---|---:|---:|---|---|---|
| `bike` | 12 | 7 (scalono 1) | 0,70× / ~69 / 0 | 0,88× / ~249 / 0 | 0,99× / ~257 / 0 |
| `walk` | 6 | 2 (scalono 4) | 1,005× / ~58 / 1448 | 1,03× / ~76 / 1919 | 1,03× / ~76 / 1923 |

Wartości < 1 oznaczają, że trasa jest szybsza od najszybszej trasy samą komunikacją (KMK + pieszo), bo rower skraca dojścia. Ten sam seed z innym, zimnym cache może dać nieco inny środek frontu przez niedeterminizm OTP.

**Ocena suwaka na 6 parach spoza quick** (`slider_eval.json`; cele: monotonia ≥ 0.8, distinct ≥ 4, build < 2 s):

| Miara | `bike` | `walk` |
|---|---:|---:|
| `monotonic_rate` (surowe ząbki) | 0.00 ✗ | 1.00 ✓ |
| `mean_distinct` (różne trasy z 7 ząbków) | 5.33 ✓ | 1.17 ✗ |
| `mean_positions` (po `build_route_slider`) | 4.50 | 1.67 |
| czas budowy p50 / max | 1.05 / 1.31 s ✓ | 0.24 / 1.38 s ✓ |

Interpretacja i porównanie z rundą 1 — `DESIGN.md` §14.

## Znane ograniczenia

- **Monotonia `bike` = 0.00 dotyczy surowych ząbków** poza parami treningowymi (tick 0 = rower + KMK bywa wolniejszy od roweru bezpośredniego). Użytkownik jest chroniony: `build_route_slider` sortuje po realnych metrykach i usuwa zdominowane trasy.
- **`walk` ma ~1–2 pozycje na większości par** — OTP zwraca mało sensownych wariantów pieszo + KMK; wagi nie wystarczą, potrzebny jest mechanizm „wysiądź wcześniej” (DESIGN §15). Na krótkich parach, gdzie najlepszy jest sam spacer, ticki KMK dają `no_route`, a suwak ma jedną pozycję.
- **Front `bike` jest rowerowy.** Przy f2 = kcal rower (MET 7,0) wygrywa ze spacerem (MET 3,5), więc profile `bike` mają 0 kroków. Kartę „Cel kroków” obsługuje wariant `walk` albo osobne zapytania piesze (K5–K7 w docs/OTP.md).
- **Trening tylko na 4 parach** (quick); full (10 par) nie był uruchamiany. Jeden zestaw ticków dla wszystkich tras, jedna pora dnia (poniedziałek 8:30), kcal roweru bez korekty za podjazdy.
- **Niedeterminizm OTP na zimno.** Powtarzalność zapewnia tylko ten sam plik cache, więc cache trzeba przechowywać razem z wynikiem.
- Kalorie i kroki użytkownika backend liczy z jego wagi i wzrostu (`weight`, `height`); są tylko lokalnie, nigdy na serwerze.
