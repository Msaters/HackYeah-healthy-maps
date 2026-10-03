# optimizer — profile wag OTP z algorytmu genetycznego (NSGA-II)

Algorytm genetyczny NSGA-II przeszukuje wagi zapytania OpenTripPlannera (`modes` + `preferences` w `planConnection`) i przybliża front Pareto dwóch celów: **czas przejazdu (min)** i **aktywne kcal (max)**. Warunek: trasa nie może być dużo dłuższa od najszybszej trasy komunikacją. Z frontu wybieramy 3 gotowe profile wag (**fast / balanced / active**), które backend wkleja do zapytań OTP. Liczymy je offline, raz. Szczegóły projektu (genom, kryteria, ograniczenie, pary OD, budżety) są w [DESIGN.md](DESIGN.md).

## Wymagania

- Python 3.12 + `numpy` (poza tym tylko biblioteka standardowa).
- Działający OTP 2 pod `http://localhost:8080/otp/gtfs/v1`, uruchomiony według [docs/OTP_QUICKSTART.md](../docs/OTP_QUICKSTART.md). Bez OTP działają tylko testy jednostkowe, a test integracyjny jest pomijany.
- Wszystkie komendy uruchamiamy z katalogu głównego repo.

## Struktura

| Plik | Rola |
|---|---|
| `genome.py` | genom `x ∈ [0,1]^10` → `decode(x)` = zmienne GraphQL `{modes, preferences}` |
| `nsga2.py` | rdzeń NSGA-II: dominacja z ograniczeniem (Deb), sortowanie frontów, crowding, SBX, mutacja, hypervolume |
| `evaluate.py` | klient OTP (wątki + cache JSONL), metryki tras (kcal, kroki), baseline KMK, kara `cv` |
| `od_pairs.json` | 10 par źródło–cel w Krakowie (4 z nich w trybie quick) |
| `run_ga.py` | CLI: przebieg GA → `front.json`, `profiles.json`, raport |
| `profiles.py` | deduplikacja i filtr niezdominowanych punktów frontu, wybór profili fast/balanced/active |
| `report.py` | wykres `front.svg` i tabela `front.md` (np. na slajd) |
| `tests/` | testy `unittest`; `test_integration_otp.py` wymaga działającego OTP |

## Komendy

```bash
# wszystkie testy (test integracyjny jest pomijany, gdy OTP nie odpowiada; ~1 min, gdy odpowiada)
python3 -m unittest discover -s optimizer/tests -t . -v

# sam test integracyjny (pełny pipeline quick w katalogu tymczasowym); inny OTP: OTP_URL=...
python3 -m unittest optimizer.tests.test_integration_otp -v

# tryb quick: pop=12, gen=4, 4 pary, ~240 zapytań, ~1 min
python3 -m optimizer.run_ga --mode quick --seed 1 --out optimizer/out/quick

# tryb full: pop=24, gen=12, 10 par, ~3100 zapytań, ~15 min
python3 -m optimizer.run_ga --mode full --seed 1 --out optimizer/out/full \
    --cache optimizer/out/full/otp_cache.jsonl

# raport (SVG + MD) z istniejącego frontu
python3 -m optimizer.report optimizer/out/quick/front.json [--profiles PATH] [--out DIR]
```

- **Trybu full nie uruchamialiśmy w ramach projektu** (decyzja zespołu: liczy się projekt algorytmu, a nie wynik obliczeń). Jeśli ktoś go puści, niech zachowa **plik cache razem z wynikiem**. OTP uruchomiony na zimno nie jest w 100% deterministyczny (ok. 1 na 150 odpowiedzi się różni), więc identyczny wynik da się odtworzyć tylko z tego samego cache.
- Domyślny cache to `optimizer/cache/otp_cache.jsonl`. `--no-cache` go wyłącza, a `--cache PATH` wskazuje inny plik. Przy ciepłym cache przebieg quick trwa < 1 s.
- Inne flagi: `--workers K` (domyślnie 10 równoległych zapytań), `--pop`/`--gens` (nadpisują tryb), `--url`, `--pairs`, `--no-report`.
- `optimizer/cache/` i `optimizer/out/` są w `.gitignore`.

## Wyniki (katalog `--out`)

| Plik | Zawartość |
|---|---|
| `front.json` | `{"meta", "front": [...]}`: niezdominowane, dopuszczalne (`cv == 0`) punkty bez duplikatów zapytań (różne wagi mogą dać identyczne trasy i metryki), posortowane po czasie. Każdy punkt ma `x`, `query {modes, preferences}`, `f_time_ratio`, `active_kcal`, `steps`, `duration_min`, `cv`, `per_pair`. `meta` zawiera seed, baseline'y, historię generacji (HV, cache) i liczbę zapytań |
| `profiles.json` | `{"fast"\|"balanced"\|"active": {"modes", "preferences", "metrics"}}`: `fast` = najszybszy punkt, `active` = najwięcej kcal, `balanced` = kolano frontu |
| `front.svg` | wykres frontu (oś X: czas względem najszybszej trasy KMK, oś Y: kcal) z zaznaczonymi profilami |
| `front.md` | tabela profili i wszystkich punktów frontu, z osadzonym `front.svg` |
| `checkpoint.json` | front po każdej generacji (schemat jak `front.json` + `generation`); można go podejrzeć w trakcie długiego przebiegu |

## Jak backend ma użyć profilu

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


with open("optimizer/out/quick/profiles.json", encoding="utf-8") as f:
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

- **Prędkości** `walk.speed` i `bicycle.speed` są w profilu stałe (1,33 i 4,5 m/s), bo GA ich nie optymalizuje. Backend może je nadpisać tempem użytkownika.
- Profile to **dodatkowe zapytania** obok K1–K7 z [docs/OTP.md](../docs/OTP.md), a nie ich zamiennik. Kandydatów z profili i z K1–K7 łączy backend, który filtruje trasy po terminie przyjazdu i wybiera 3 karty: „Najszybsza”, „Cel kaloryczny” i „Cel kroków”.

## Przykładowy wynik (quick, seed 1, 4 pary)

To tylko przykład z trybu quick, a nie wynik docelowy:

| Profil | Czas × vs najszybsza KMK | Aktywne kcal (70 kg) |
|---|---:|---:|
| fast | 0,80× | ~107 |
| balanced | 0,83× | ~197 |
| active | 0,90× | ~254 |

Wartości < 1 oznaczają, że trasa jest szybsza od najszybszej trasy samą komunikacją (KMK + pieszo), bo rower skraca dojścia. Ten sam seed z innym, zimnym cache może dać nieco inny środek frontu (np. balanced 0,88×/~250 kcal) przez niedeterminizm OTP.

## Znane ograniczenia

- **Front jest rowerowy.** Przy f2 = kcal rower (MET 7,0) zawsze wygrywa ze spacerem (MET 3,5), więc profile mają 0 kroków. Kartę „Cel kroków” obsługują osobne zapytania piesze (K5–K7 w docs/OTP.md), a nie te profile.
- **Niedeterminizm OTP na zimno.** Powtarzalność zapewnia tylko ten sam plik cache, więc cache trzeba przechowywać razem z wynikiem.
- **Jeden zestaw profili** dla wszystkich (70 kg, jedna godzina przyjazdu `2026-10-05T08:30`, wybrane pary OD). Nie ma profili dla pory dnia, pogody ani typu trasy. Kalorie użytkownika backend liczy osobno, z jego wagi.
