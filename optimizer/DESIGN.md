# Optymalizator wag OTP (NSGA-II) — dokument projektowy

Offline'owy algorytm genetyczny NSGA-II, który przybliża **front Pareto** OpenTripPlannera dla dwóch celów
— **czas przejazdu → min** i **ruch (aktywne kcal) → max** — i zwraca 3 gotowe profile wag OTP
(`fast` / `balanced` / `active`) oraz **suwak „czas ↔ ruch”** (7 ząbków wzdłuż frontu), które backend wkleja
do zapytań `planConnection`. Dwa warianty: `bike` (użytkownik ma rower) i `walk` (bez roweru, §10).
Interfejsy wiążące: `.hy-loop/state.md` („Ustalone interfejsy”). Kontekst OTP: `docs/OTP.md` §2, §6, §11, §12.

## 1. Cel i motywacja

- **OTP nie minimalizuje czasu, tylko koszt uogólniony** (`generalizedCost`, `docs/OTP.md` §2): sekunda w KMK ≈ 1,
  sekunda chodzenia × `walk.reluctance`, sekunda roweru × `bicycle.reluctance`, plus kary za wejście,
  przesiadkę i czekanie. Domyślne `reluctance = 2.0` sprawia, że OTP z natury **unika ruchu**.
- Wagi to więc **pokrętło kompromisu czas/ruch**: obniżenie `walk.reluctance` sprawia, że minuta spaceru
  „kosztuje” mniej niż minuta w tramwaju, i OTP sam znajdzie trasę z większą liczbą kroków.
- **Dlaczego nie ręczne strojenie:** kilkanaście parametrów oddziałuje na siebie nieliniowo (np. niska niechęć do roweru
  nic nie daje, gdy `access = WALK`), a efekt zależy od pary skąd–dokąd. Ręcznie dostroimy jeden punkt;
  GA daje cały front i wybiera z niego punkty w sposób powtarzalny i uzasadniony („to nie są magiczne liczby”).
- **Dlaczego offline:** jedna ocena genomu = kilka–kilkanaście zapytań do OTP (po jednym na parę OD).
  Pełny przebieg to ~3 tys. zapytań, ~15 min (§8) — za drogo na żądanie użytkownika. Liczymy raz,
  zapisujemy `profiles.json` i `slider.json`; backend w runtime wysyła tylko 9 dodatkowych zapytań (§13).

## 2. Genom

Genom `x ∈ [0,1]^12` (`DIM = 12`: 10 genów wspólnych + 2 geny aktywne tylko w wariancie `walk`); `genome.decode(x, variant="bike")` → `{"modes": …, "preferences": …}` = zmienne GraphQL `planConnection`.
Skala liniowa: `v = lo + x·(hi−lo)`; skala log: `v = lo·(hi/lo)^x`.

| # | Parametr OTP (ścieżka) | Typ | Zakres | Skala | Uzasadnienie zakresu |
|---|---|---|---|---|---|
| 0 | `preferences.street.walk.reluctance` | float | 0.5–5 | log | <1 = chodzenie „tańsze” niż jazda (aktywne), >2 = OTP unika chodzenia (szybkie); domyślnie 2.0 |
| 1 | `preferences.street.bicycle.reluctance` | float | 0.5–5 | log | jak dla chodzenia |
| 2–4 | `preferences.street.bicycle.optimization.triangle` `{safety, flatness, time}` | 3×float | [0,1] → suma 1 | lin | infrastruktura rowerowa vs płasko vs szybko |
| 5 | `preferences.transit.board.waitReluctance` | float | 0.5–2 | lin | tolerancja czekania na przystanku (domyślnie 1.0) |
| 6 | `preferences.transit.transfer.cost` [s] | int | 0–600 | lin | 0 = przesiadki bez kary, 600 = przesiadka „wyceniona” na 10 min |
| 7 | `modes.transit.transit[{mode: BUS, cost.reluctance}]` | float | 0.8–3 | lin | preferencja tramwaju nad autobusem (korki); <1 dopuszcza preferencję autobusu |
| 8 | `modes.transit.access` | kat. | {WALK, BICYCLE, BICYCLE_PARKING} | floor | dojście / rower do przystanku / bike&ride |
| 9 | `modes.direct` | kat. | {brak, WALK, BICYCLE} | floor | czy dopuścić trasę bez komunikacji |
| 10 | `preferences.street.walk.boardCost` [s] — **tylko `walk`** | int | 0–1800 | lin | kara za każde wejście do pojazdu (domyślnie OTP 600); duża → OTP woli iść dalej pieszo zamiast przesiadać się |
| 11 | `preferences.street.walk.safetyFactor` — **tylko `walk`** | float | 0–1 | lin | waga bezpieczeństwa ulic pieszych (domyślnie 1.0); inne ulice → inne trasy piesze |

**Stałe (poza genomem):** `walk.speed = 1.33 m/s`, `bicycle.speed = 4.5 m/s` (`FIXED_WALK_SPEED` / `FIXED_BIKE_SPEED`,
wartości z `otp/router-config.json`). W rundzie 1 prędkości były genami (1.1–1.6 i 3.5–6.5 m/s) i GA
„kupował” kalorie **wolniejszą jazdą** — `kcal = MET × czas`, więc wolniej = dłużej = więcej kcal (profil
`active` z pierwszego przebiegu quick miał rower 3.7 m/s). Prędkość to **cecha użytkownika**, nie preferencja
trasy: backend może nadpisać ją prędkością z profilu, a wagi pozostają ważne.

- **Log dla reluctance:** parametr działa multiplikatywnie (stosunek kosztu ruchu do kosztu jazdy).
  Przejście 0.5→1.0 zmienia zachowanie OTP tak samo mocno jak 2.5→5.0; w skali liniowej 90% zakresu
  leżałoby w mało ciekawym obszarze >1, a mutacja prawie nie trafiałaby w strefę „aktywną”. Log daje
  równą gęstość próbkowania na każdą dekadę zmian.
- **Kategoryczne przez `floor(x·k)`** (k = 3, wynik obcięty do k−1, żeby `x = 1` dało ostatnią kategorię):
  operatory SBX i mutacja działają na ciągłym `x`, dekoder dzieli [0,1] na k równych przedziałów. Dzięki temu
  jeden algorytm obsługuje oba typy genów, a mała mutacja zwykle nie zmienia kategorii (stabilność).
- **Triangle normalizowany:** 3 geny → `(w_i+ε) / Σ(w+ε)` (ε = 1e-6, więc same zera dają 1/3), zaokrąglone do
  3 miejsc z dokładną sumą 1 — OTP wymaga sumy 1. `transfer.cost` jest zaokrąglany do pełnych sekund.
- **`direct = brak`** → `transitOnly: true` (bez tego OTP i tak doda trasę pieszą).
- **egress/transfer wynikają z access:** `access = BICYCLE` → `egress = transfer = [BICYCLE]` (rower jedzie z nami);
  w pozostałych przypadkach `[WALK]` (przy `BICYCLE_PARKING` rower zostaje na stojaku). Osobne geny
  dawałyby niespójne kombinacje (rower na wyjściu bez roweru na wejściu) i marnowały budżet.
- **Bez `BICYCLE_RENTAL`:** w Krakowie nie ma roweru na minuty; Park-e-Bike to nasz własny feed GBFS
  z **symulowaną** dostępnością i ograniczeniami godzinowymi (wypożyczenie do 20:00). Optymalizacja na
  symulowanych danych przeuczyłaby wagi na fikcję. Park-e-Bike zostaje sztywnym kandydatem K4 w backendzie.

- **Warianty:** `decode(x, variant)` z `VARIANTS = ("bike", "walk")`; dla `walk` część genów jest nieaktywna (§10).
  Domyślny `bike` dekoduje się identycznie jak w GA v1 (test regresji).

## 3. Kryteria

Oba kryteria są **minimalizowane**:

- **f1 = średnia po parach `duration / baseline_fastest[pair]`** (`f_time_ratio`).
  `baseline_fastest` = najkrótszy `duration` z zapytania z domyślnymi wagami OTP (KMK + WALK, jak K1),
  liczony raz na parę; gdy KMK nie zwróci trasy — najkrótszy spacer. **Dlaczego względny, a nie minuty:** średnia w minutach byłaby zdominowana przez
  najdłuższe pary (+10 min na trasie 60-min przeważa +5 min na 15-min, choć ta druga to +33%).
  Stosunek waży każdą parę jednakowo i jest interpretowalny („trasa 1.3× dłuższa od najszybszej”).
  **f1 może być < 1:** baseline to najszybsza trasa *KMK + pieszo*, a rower bywa od niej szybszy
  (w quick seed 1 profil `fast` ma ×0.70).
- **f2 = −średnie aktywne kcal** (`active_kcal`) przy wadze referencyjnej **70 kg**:
  `kcal = MET × 70 × t[h]` tylko dla odcinków `WALK` (MET 3.5) i `BICYCLE` (MET 7.0); odcinki KMK = 0.
  - **Dlaczego aktywne, a nie całkowite:** całkowite kcal (z MET 1.3 za siedzenie w tramwaju) nagradzałyby
    po prostu *dłuższe* trasy — 90 min w autobusie „spala” więcej niż 15 min spaceru. Liczymy tylko ruch.
  - **Dlaczego kcal, a nie kroki:** kroki ignorują rower (0 kroków), a rower to nasz wyróżnik. Kcal
    porównuje spacer i rower w jednej walucie. Kroki liczymy i zapisujemy (`steps`) do raportu.
  - Waga 70 kg jest stałą skali: profil dobiera się raz dla wszystkich, a kcal użytkownika (jego waga,
    lokalnie w przeglądarce) przelicza backend/frontend. Liniowość w wadze → ranking się nie zmienia.
- **Front jest zdominowany przez rower** — przy f2 = kcal rower (MET 7.0) wygrywa ze spacerem (MET 3.5)
  przy tym samym czasie. To zgodne z celem („Cel kaloryczny”). Karta **„Cel kroków”** nie pochodzi z GA —
  zostaje osobnym zapytaniem K5–K7 (`docs/OTP.md` §6); kroki jako 3. kryterium → §15.

## 4. Ograniczenie (constraint) — limit wydłużenia trasy

Problem z `docs/OTP.md` §11: samo `latestArrival` przepuszcza absurdy (110 min pieszo zamiast 42 min
tramwajem — „też zdąży”). GA bez ograniczenia ochoczo by je wybierał, bo dają dużo kcal.

Dla każdej pary: `limit = 1.9 · baseline` (trasa może trwać najwyżej **190% najszybszej**; stała
`evaluate.MAX_TIME_RATIO`, funkcja `evaluate.time_limit`),
`cv_pair = max(0, duration − limit)` [min], a **brak trasy** (pusta odpowiedź / błąd) → `cv_pair = 60`.
`cv` genomu = średnia `cv_pair` po parach (dla pary bez trasy f1 przyjmuje `duration = 2·baseline`, kcal = 0).
Limit jest czysto względny (decyzja zespołu): dla baseline 10 min pozwala na 19 min, dla 42 min na 79,8 min.
Wcześniej (GA v1) limit był addytywny (baseline plus 15 min lub 50% — co większe) — dawał więcej luzu na krótkich trasach i mniej na długich.

**Przykład (Nowa Huta → AGH):** baseline = 42 min (tramwaj).
`limit = 1.9 · 42 = 79,8 min`.
- wariant 110 min pieszo: `cv = max(0, 110 − 79,8) = 30,2` → **niedopuszczalny**, odrzucony przy selekcji;
- wariant 50 min (rower + tramwaj): `cv = 0` → dopuszczalny, konkuruje w f1/f2.

**Constraint-domination Deba** (zamiast kary dodawanej do f): `a` dominuje `b`, gdy
(1) `a` dopuszczalny, `b` nie; albo (2) oba niedopuszczalne i `cv_a < cv_b`; albo (3) oba dopuszczalne
i `a` dominuje `b` w sensie Pareto (f1, f2). Nie trzeba strojenia współczynnika kary, a niedopuszczalne
rozwiązania i tak są stopniowo „ciągnięte” w stronę limitu.

**Fallback pieszy (`WALKING_BETTER_THAN_TRANSIT`):** na krótkich parach genom z `direct = brak`
(`transitOnly`) dostaje od OTP błąd „spacer lepszy niż komunikacja” i zero tras. Kara 60 sztucznie
wypychałaby populację do genów z `direct`. Ponieważ aplikacja i tak pokaże wtedy spacer, wysyłamy
dodatkowe zapytanie `direct: [WALK], directOnly` i liczymy **metryki trasy pieszej** (f1, kcal, cv jak
dla każdej innej trasy). Kara 60 zostaje tylko dla prawdziwego braku trasy.

## 5. Wybór trasy z odpowiedzi OTP

Zapytanie: `dateTime.latestArrival = 2026-10-05T08:30+02:00` (poniedziałek, szczyt), `first: 3`.
OTP zwraca kilka tras; do oceny bierzemy **tę z najmniejszym `generalizedCost`**:
- **spójność z backendem** — oceniamy dokładnie to, co OTP uważa za najlepsze przy danych wagach, a więc
  to, co backend pokaże po wklejeniu profilu; wagi mają wpływ na wynik tylko przez koszt uogólniony;
- **kolejność odpowiedzi jest nieistotna** — OTP sortuje po czasie i wstawia trasy bez komunikacji
  (street-only) na górę, więc „pierwsza trasa” nie odzwierciedlałaby wag (`docs/OTP.md` §12).

## 6. NSGA-II

Klasyczny NSGA-II (Deb i in., 2002), `optimizer/nsga2.py`:
- **Elitaryzm μ+λ:** rodzice (μ = pop) + potomkowie (λ = pop) → połączona populacja 2·pop → wybór pop najlepszych.
  Najlepsze rozwiązanie nigdy nie ginie.
- **Szybkie sortowanie niezdominowane** (z constraint-domination z §4) → kolejne fronty F1, F2, …;
  wypełniamy populację całymi frontami, ostatni dzielimy wg crowding distance.
- **Crowding distance:** dla każdego frontu suma znormalizowanych odległości do sąsiadów w f1 i f2;
  punkty skrajne = ∞. Utrzymuje rozproszenie wzdłuż frontu (chcemy cały kompromis, nie jeden punkt).
- **Selekcja: turniej binarny** — lepszy rang, przy remisie większy crowding.
- **Krzyżowanie SBX** (η_c = 15, p_c = 0.9) i **mutacja wielomianowa** (η_m = 20, p_m = 1/D = 1/12),
  oba z obcięciem do [0,1]. Duże η → potomkowie blisko rodziców (lokalne doszlifowanie).
- **Populacja startowa z `X0`:** `nsga2(…, X0=…)` (k×dim, k ≤ pop) zastępuje pierwsze k osobników; run_ga
  wstrzykuje tam kotwicę K1 (§11). Wiersze są walidowane (`isfinite`, zakres [0,1]).
- **Selekcja przeżycia z dedupe w przestrzeni celów** (`survival_select`, `dedupe_decimals=6`): osobniki o tym
  samym `round(F, 6)` — różne `x`, te same trasy — trafiają **za wszystkie fronty**; zostaje kopia o najniższym
  ranku, przy remisie ta o mniejszym indeksie (gdy unikalnych za mało, duplikaty uzupełniają do `pop`).
  Bez tego kopie jednego punktu zapełniały populację i front się zapadał. `dedupe_decimals=None` = zachowanie
  GA v1; test porównuje wynik z zamrożoną kopią `tests/_nsga2_legacy.py`.
- **Determinizm:** jeden `numpy.random.Generator(seed)`; ten sam seed + cache OTP → identyczny front.
- Walidacja rdzenia bez OTP: ZDT1 (D=10, pop=40, gen=60) → hiperobjętość względem (1.1, 1.1) ≥ 0.6.
- **Postęp w przebiegu OTP:** HV dopuszczalnego frontu dla `F = [time_ratio, −kcal]` względem punktu
  odniesienia **(2.0, 0.0)** — trasa 2× wolniejsza od najszybszej, bez ruchu; logowana co generację.
- **Eksport:** `front.json` zawiera tylko dopuszczalne punkty niezdominowane, po deduplikacji
  identycznych zapytań (różne `x` → ten sam `query` po dekodowaniu kategorii/zaokrągleń).

## 7. Pary OD

`optimizer/od_pairs.json`: **10 par** w Krakowie (bbox 19.79–20.22 E, 49.97–50.13 N) o różnych długościach
(krótkie ~2 km, średnie ~5 km, długie ~9 km) i kierunkach (centrum, północ, południe, wschód–zachód,
peryferie–peryferie: Prokocim → Bronowice), m.in. scenariusze demo Nowa Huta → AGH, Czerwone Maki → Rynek.
**Podzbiór `quick` = 4 pary** (`rynek_agh`, `kurdwanow_kazimierz`, `czerwone_maki_rynek`, `nowa_huta_agh`:
krótka, dwie średnie z P+R, długa) do szybkiej iteracji.

Agregacja: **średnia** po parach (f1, f2, cv). Średnia stosunków (f1) nie faworyzuje długich par.

**Ryzyko przeuczenia** (wagi dopasowane do konkretnych relacji) ograniczamy: zróżnicowaniem par, względną miarą czasu,
ograniczeniem §4 per para i walidacją na odłożonych parach (`slider_eval`, §14) — która je potwierdziła (§14a).

## 8. Wydajność i cache

**Budżet:** liczba ewaluacji = `pop × (gens + 1)` (populacja startowa + `gens` pokoleń potomków);
zapytania = ewaluacje × pary, + 1 zapytanie baseline na parę.

| Tryb | pop | gens | pary | zapytania GA | + baseline | Czas na zimno | Na ciepło (cache) |
|---|---|---|---|---|---|---|---|
| quick | 12 | 4 | 4 | 12 × 5 × 4 = **240** | +4 | **~18–25 s** (zmierzone: bike 25.3 s, walk 18.0 s) | **~0.4 s** |
| full | 24 | 12 | 10 | 24 × 13 × 10 = **3120** | +10 | ~15 min (szacunek) | — |

**Trybu full nie uruchamiamy** — decyzja zespołu: produktem tej części jest projekt algorytmu;
przebieg quick służy jako dowód działania. Komenda i budżet full są gotowe (`run_ga --mode full`).

- **Zmierzona przepustowość OTP:** ~3.0 zapytań/s przy 6 wątkach, ~3.4–3.7 przy 8–12 wątkach —
  OTP nasyca CPU przy ~8 wątkach. Domyślnie `--workers 10`. (Wynika z tego ~2 s na zapytanie
  przy 6 wątkach — wyszukiwanie rowerowe po grafie ulic jest kosztowne.)
- **Deduplikacja w paczce:** `plan_many` liczy klucz każdego żądania i wysyła do OTP tylko unikalne
  (w generacji wiele genomów dekoduje się do tego samego zapytania — kategorie, zaokrąglenia).
- **Cache JSONL:** klucz = `sha1` znormalizowanego żądania (zapytanie + zmienne, `json.dumps(sort_keys=True)`),
  wartość = surowa odpowiedź; dopisywane linia po linii (bezpieczne przy przerwaniu). Zysk:
  powtórzone genomy między generacjami i ponowne uruchomienia (ten sam seed, zmiana raportu/profili)
  **nie kosztują zapytań**. Cache jest ważny dla konkretnego grafu i daty — po przebudowie grafu usuwamy plik.

## 9. Profile wyjściowe

Z dopuszczalnego (cv = 0) pierwszego frontu wybieramy 3 punkty (`profiles.build_profiles(front, slider)`;
gdy jest `slider.json`, profile **biorą się z ticków**: `fast` ≡ tick 0, `active` ≡ tick n−1, `balanced` = kolano):
- **`fast`** = min f1 (najbliżej najszybszej trasy),
- **`active`** = max aktywnych kcal (min f2),
- **`balanced`** = **punkt kolana** (liczony na tym samym froncie, co ząbki): po normalizacji f1 i f2 do [0,1] w obrębie frontu — punkt o największej
  odległości od prostej łączącej `fast` i `active` (największy „zysk kcal za minutę”). Gdy front ma < 3 punkty,
  `balanced` = jeden ze skrajnych (profile mogą się powtarzać).

Profile są więc skrajnymi i środkowym punktem suwaka (§12) — jedno źródło prawdy.
Wymagana monotonia: `fast` ma najmniejszy f1, `active` najwięcej kcal, `balanced` pomiędzy w obu.

Format `profiles.json`:
```json
{
  "fast":     {"modes": {...}, "preferences": {...}, "metrics": {"f_time_ratio": 1.02, "active_kcal": 48.0, "steps": 1900, "duration_min": 31.5}},
  "balanced": {"modes": {...}, "preferences": {...}, "metrics": {...}},
  "active":   {"modes": {...}, "preferences": {...}, "metrics": {...}}
}
```
(`modes` / `preferences` wklejamy 1:1 jako zmienne `planConnection`; `metrics` — do raportu i slajdu.)
Pełny front: `front.json` (format w `state.md`), wizualizacja: `front.svg` / `front.md` (`report.py`).

**Użycie w backendzie (profile):** profile to **3 dodatkowe zapytania** obok sztywnych kandydatów K1–K7
(`docs/OTP.md` §6) — wysyłane równolegle do wspólnej puli. **Wybór kart pozostaje w backendzie**:
odrzucenie tras, które nie zdążą (`end` > termin − 3 min), limit wydłużenia z §4, wybór Najszybsza /
Cel kaloryczny / Cel kroków i deduplikacja kart z tą samą trasą. GA tylko wzbogaca pulę o kandydatów,
których ręczne wagi by nie znalazły.

## 10. Tick [mam rower] — warianty `bike` / `walk`

Użytkownik deklaruje, czy ma rower; backend wybiera `slider.json` z `out/quick_bike/` albo `out/quick_walk/`
(osobne katalogi: `front.json`, `profiles.json`, `slider.json`, `front.svg`, `front.md`). Przełącznik: `run_ga --variant bike|walk`.

Co zmienia `decode(x, "walk")`:
- `modes.transit.access = [WALK]`, `egress` i `transfer` = `[WALK]`; gen `direct` ∈ {brak, `WALK`} przez `floor(x·2)`
  (nigdy `BICYCLE`); brak `preferences.street.bicycle` w zapytaniu.
- **Geny rowerowe są nieaktywne:** `active_mask("walk")` = False dla genów 1–4 (reluctance i triangle roweru) i 8 (`access`).
  `canonical(x, variant)` ustawia je na **0.5**, więc `x` różniące się tylko nieaktywnymi genami dają ten sam
  `canonical`, to samo zapytanie i jeden wpis w cache. run_ga dekoduje zawsze `canonical` + `decode`.
  Mutacja/SBX nadal działają na pełnym wektorze (stały wymiar), ale te geny nie zmieniają celów — dryf neutralny.
  W `walk` aktywnych jest 7 genów (0, 5, 6, 7, 9, 10, 11), w `bike` 10 (0–9; `meta.active_genes`).
- **Geny walk-only (runda 2): `walk.boardCost` (0–1800 s, kotwica 600) i `walk.safetyFactor` (0–1, kotwica 1.0).**
  Dopisane **na końcu** genomu (DIM 10 → 12), więc indeksy 0–9 się nie zmieniły. W `bike` są nieaktywne i **nie trafiają do zapytania**
  (decode `bike` bez zmian — test regresji na 500 losowych `x`); `canonical("bike")` ustawia je na 0.5.
  *Po co:* w rundzie 1 front `walk` miał 2 punkty — `walk.reluctance` nasyca się (≤ ~1.6 daje tę samą trasę), a z ≤ 3 tras
  w odpowiedzi wagi nie mają czym wybierać. **Sonda** (1200 kombinacji parametrów na 5 parach): żaden parametr osobno
  nie daje ≥ 4 różnych tras; **dźwignią jest interakcja `walk.boardCost` × `walk.reluctance`** (5–6 różnych tras na 4 z 5 par;
  `safetyFactor` dodaje 1–2). Wysoka kara za wejście do pojazdu + niska niechęć do chodzenia = „wysiądź wcześniej / idź dalej”.
- **f2 = kcal także dla `walk`** (bez zmiany kryterium): kcal z chodzenia = MET × waga × czas, a przy stałej
  prędkości (`FIXED_WALK_SPEED`) czas chodzenia ∝ dystans pieszy ∝ kroki. Czyli ranking po kcal ≡ ranking po
  krokach (waga to stała skali, §3). Jedno kryterium, jeden kod; kroki raportujemy obok (`steps` w tickach).

## 11. Kotwica K1 i różnorodność

- **Kotwica K1** = domyślne wagi OTP, czysta komunikacja: `ANCHOR_VALUES` (walk.reluctance 2.0,
  waitReluctance 1.0, transfer.cost 0, BUS 1.0, access WALK, direct brak). `encode_anchor(variant)` zwraca `x`,
  dla którego `decode` daje `transitOnly: True` i dokładnie te wartości. Zapytanie ≡ `BASELINE_TRANSIT`
  (sprawdzone na 3 parach), więc kotwica ma f1 ≈ 1 (w quick: 1.0069 — baseline to najkrótszy czas, a kotwica
  wybiera min `generalizedCost`).
- **Wstrzyknięcie przez `X0 = [encode_anchor(variant)]`** — GA startuje z punktem „dzisiejszej Mapy Google” i nie
  musi go przypadkiem odkrywać. Wynik trafia do `meta.anchor` (metryki, `per_pair`, **`in_front`**). Flaga `--no-anchor` wyłącza.
- **Wyniki:** `bike` — kotwica **dominowana** (`in_front: false`: f1 1.007 / 58 kcal vs ×0.70 / 69 kcal najszybszego
  punktu — rower bywa szybszy od KMK); `walk` — kotwica **jest na froncie** (`in_front: true`, 32.2 min, ~58 kcal,
  1450 kroków).
- **Różnorodność:** dedupe w przestrzeni celów przy przeżyciu (§6) + dedupe po `query` w `front.json`; dla `bike` quick daje 7 różnych punktów, dla `walk` tylko 2 (§14).

## 12. Suwak offline

`optimizer/slider.py`; wejście `front.json`, wyjście `slider.json`. Suwak `s ∈ [0,1]`: 0 = najszybciej, 1 = najwięcej ruchu.

**Pozycja po długości łuku, nie sumie ważonej.** Suma ważona `w·f1 + (1−w)·f2` osiąga tylko punkty z wypukłej
otoczki frontu — wklęsły fragment (a front czas↔kcal ma skoki: rower+KMK → rower całą trasę) jest przeskakiwany,
a mały ruch `w` potrafi przenieść wynik z jednego końca na drugi. Długość łuku:
1. `pareto_filter` (niezdominowane, w kolejności `sorted_front`: f1 rosnąco, przy remisie kcal malejąco);
2. f1 i `active_kcal` normalizowane do [0,1] w obrębie frontu (różne jednostki);
3. `arc_positions`: skumulowana odległość euklidesowa po punktach / długość całkowita → `u ∈ [0,1]`
   (pierwszy 0, ostatni 1; jeden punkt → [0.0]). Równy krok `s` = równy krok „wrażenia” wzdłuż krzywej.

**7 ząbków** (`sample_front(front, n=7)`): ząbek i ma cel `s_i = i/(n−1)` i dostaje punkt o najbliższym `u`
(remis → szybszy). Kolejne ząbki mają niemalejący czas i kcal; kilka ząbków może dzielić punkt (front < 7 punktów).
Tick = `{s, u, index, modes, preferences, metrics{f_time_ratio, active_kcal, steps, duration_min}}`.
**Kontrakt:** `tick.index` = indeks w `sorted_front(front)` (całego wejścia, przed filtrem) — ten sam porządek
stosuje `slider_select`, więc indeksy są spójne.

**Scalanie bliskich punktów** (`merge_close`, `DEFAULT_MERGE_EPS = (0.005, 2.0)` — czas ×, kcal): zachłannie od lewej,
grupa zaczyna się od najszybszego punktu (reprezentant) i zbiera następne, których f1 **i** kcal mieszczą się w ε od
reprezentanta (bez łańcuchowania); ostatnia grupa jest reprezentowana przez ostatni punkt, więc koniec suwaka to
nadal max kcal. `merge_eps=0/None` = bez scalania; CLI: `--merge-eps-time`, `--merge-eps-kcal`. **Scalanie działa** — `slider.meta`
ma `merged` (liczba usuniętych punktów) i `merge_eps`: quick `bike` 12 → 11 punktów (`merged: 1`), quick `walk` 6 → 2 (`merged: 4`);
run_ga używa domyślnego ε. Ząbki nie powtarzają już praktycznie tego samego punktu frontu (`bike`: 7 ząbków = 7 różnych punktów).

Schemat `slider.json`: `{"meta": {variant, n, f1, f2, distinct, merged, merge_eps, source, generated, feasible_front}, "ticks": [7 × tick]}`;
`meta.distinct` = liczba różnych punktów frontu **po scaleniu** (nie różnych tras OTP). CLI:
`python3 -m optimizer.slider <front.json> [--n 7] [--variant bike|walk] [--out PATH]`.
`report.py` rysuje ząbki na wykresie frontu i tabelę „Suwak” w `front.md`.

## 13. Dopasowanie online (`slider_select`)

Offline mamy 7 profili wag; dla **konkretnej trasy użytkownika** backend sprawdza, co OTP z nimi zwróci.
Punkt wejścia: `plan_route_slider(slider, origin, destination, deadline)` — sam ustawia
`arrive_by = deadline − bufor` (`query_arrive_by`) i używa `ROUTE_QUERY` (jak `QUERY` GA + geometria, linie,
przystanki dla UI; klucze cache GA bez zmian).

1. **9 zapytań** (`tick_requests`, każde z `tag`): 7 ząbków `tick:0..6`, `anchor` (`BASELINE_TRANSIT`, czysta
   komunikacja) i `walk` (`BASELINE_WALK`); jednakowe zapytania są deduplikowane przez `plan_many`.
   `walk_speed` / `bike_speed` użytkownika podmieniają prędkości tylko w kopii.
2. **Wybór trasy z odpowiedzi** (`build_route_slider`): ząbek → trasa o min `generalizedCost` (jak §5);
   `anchor`/`walk` → **najszybsza** (referencje czasowe, jak `compute_baselines`). `baseline_min` = najszybsza z `anchor`, a gdy brak — `walk`.
3. **Filtr:** zdąży (`end ≤ deadline − 3 min`; inaczej `late`) i limit wydłużenia z §4 (ten sam `cv`; inaczej `too_long`).
4. **Scalanie po sygnaturze** `(mode, round(duration/30), round(distance/50))` per odcinek → jedna pozycja, `sources` = lista tagów (`duplicate`).
5. **Mini-front:** sortowanie po czasie, filtr niezdominowanych (`dominated`), `arc_positions` → `s` pozycji.
   Wynik monotoniczny **z konstrukcji**, niezależnie od kolejności surowych ząbków.
6. Wynik: `positions[{s, route_key, sources, metrics{duration_min, active_kcal, steps, end, slack_min, modes}, itinerary, locked}]`,
   `default_index`, `lock_reason`, `baseline_min`, `warnings`, `dropped{late, too_long, no_route, error, duplicate, dominated}`
   (komplet liczników także, gdy `positions == []`).

**Smog / pogoda** (`lock_reason`, np. `smog`): pozycje z `s > lock_above_s = 0.5` mają `locked: true`; trasa
komunikacją (`anchor`) jest zawsze dostępna jako **fallback i `default_index`** — zgodnie z zasadą „zły smog →
nie promować roweru”. Bez `lock_reason` nic nie jest zablokowane. Demo (nowa_huta_agh, smog): domyślnie KMK
40.5 min, rower 35–38 min (2 pozycje dostępne, 2 zablokowane).
Backend powinien tworzyć `OTPClient(arrive_by=query_arrive_by(deadline))`. CLI:
`python3 -m optimizer.slider_select --slider PATH --pair ID | --from lat,lon --to lat,lon --deadline ISO [--no-cache] [--lock smog]`
(exit 2 przy niedostępnym OTP). Czas budowy 9 zapytań: §14.

## 14. Wyniki i ocena

**Quick (seed 1, pop 12 × 4 pokolenia, 4 pary): przed rundą 2 → po rundzie 2** (geny walk-only, scalanie ε, limit 190%).
Źródło „po”: `out/quick_{bike,walk}/front.json`, `slider.json`, `profiles.json`; „przed”: pierwszy przebieg (21:43), limit addytywny z GA v1.

| | `bike` przed | `bike` po | `walk` przed | `walk` po |
|---|---|---|---|---|
| zapytania / czas przebiegu | 244 / 32.7 s | 243 / 25.3 s | 242 / 14.3 s | 248 / 18.0 s |
| punkty frontu (`front.json`) | 10 | 12 | 2 | 6 |
| scalone ε (`merged`) | — | 1 | — | 4 |
| różne ząbki (`slider.distinct`) | 5 | **7** | 2 | **2** |
| `fast` | ×0.80, ~107 kcal, 26.3 min | ×0.70, ~69 kcal, 23.9 min | 32.2 min, ~58 kcal, 1450 kroków | 32.2 min, ~58 kcal, 1448 kroków |
| `active` | ×0.90, ~254 kcal, 31.1 min | ×0.99, ~257 kcal, 33.0 min | 33.2 min, ~76 kcal, 1923 kroki | 33.2 min, ~76 kcal, 1923 kroki |
| kotwica K1 | dominowana | dominowana (`in_front: false`) | na froncie | na froncie (`in_front: true`) |
| HV (ref 2.0, 0) gen 0 → 4 | 292.098 → 294.000 | 299.756 → 308.056 | 75.313 → 75.313 | 75.435 → 75.460 |

(Średnie z 4 par treningowych. `bike` „po” ma inne liczby częściowo przez nowy limit 190% i DIM 12, nie tylko przez scalanie.)
Quick to smoke test — wynik ma pokazać, że potok działa, nie że front jest zbieżny.

**Ocena suwaka na 6 parach spoza quick** (`slider_eval`, bez cache, OTP rozgrzany, 8 wątków; pary: m.in. kazimierz_dworzec, bronowice_agh, ruczaj_dworzec, prokocim_bronowice):

| Miara | `bike` przed | `bike` po | `walk` przed | `walk` po | Cel |
|---|---|---|---|---|---|
| `monotonic_rate` (surowe ząbki) | 0.00 | **0.00** | 1.00 | 1.00 | ≥ 0.8 |
| `mean_distinct` (różne trasy z 7 ząbków) | 3.67 | **5.33** | 1.67 | **1.17** | ≥ 4 |
| `mean_positions` (po `build_route_slider`) | 4.33 | 4.50 | 1.83 | 1.67 | — |
| `build_s` p50 / max | 0.67 / 0.90 s | 1.05 / 1.31 s | 0.18 / 0.22 s | 0.24 / 1.38 s | < 2 s |

Cele spełnione: `distinct` dla `bike` (5.33 ≥ 4), czas budowy (oba warianty), monotonia `walk`.
**Niespełnione:** monotonia `bike` (0.00) i `distinct` dla `walk` (1.17). Interpretacja (hipotezy, nie dowody):
- **(a) `bike` distinct ✓.** Scalanie ε usunęło pokrywające się ząbki (przed: ticki 2/3 i 4/5 w jednym punkcie), a geny i limit
  dały rozleglejszy front (12 punktów, ×0.70 → ×0.99 czasu, ~69 → ~257 kcal).
- **(b) `bike` monotonia 0.00 jest strukturalna.** Kolejność *surowych* ząbków nie uogólnia się poza 4 pary treningowe:
  tick 0 (rower + KMK) bywa **wolniejszy** niż rower bezpośredni z ticków 1–3. Wagi dobrane na 4 parach opisują ich rodzaj tras,
  nie każdą parę, a OTP z innym wyborem tras dla innych wag nie musi zachować porządku. **Użytkownik jest chroniony:**
  `build_route_slider` sortuje po **realnych** metrykach i filtruje zdominowane, więc suwak w aplikacji jest monotoniczny z konstrukcji.
  Miara 0.00 opisuje jakość *surowych* ząbków (a więc trafność offline), nie UX.
- **(c) `walk` distinct 1.17 — OTP ma mało sensownych wariantów pieszo + KMK na większości par.** Geny walk-only poprawiły
  front treningowy (2 → 6 punktów przed scaleniem), ale po scaleniu ε znów są 2, a na parach held-out OTP zwraca zwykle
  jedną sensowną trasę KMK + spacer (reszta to duplikat, `too_long` albo czysty spacer jako ząbek 1.0). Wagi dostają 1–3 trasy z OTP — nie
  mają z czego wybierać. Nowa dźwignia musi więc zmienić **zbiór kandydatów**, nie tylko wagi (§15).

## 15. Ograniczenia i dalsze kroki

- **Trening na większej liczbie par** (10 par / tryb full ~15 min — poza zakresem decyzją zespołu) lub rozszerzenie quick;
  główny lek na monotonię `bike` = 0.00 poza parami treningowymi (§14b); brak też pomiaru stabilności między seedami.
- **Mechanizm „wysiądź wcześniej” (via) dla `walk`** — spacer dodawany przez wysiadkę kilka przystanków wcześniej nie wynika z samych wag OTP;
  wymaga generowania kandydatów z punktem pośrednim (K5–K7, `docs/OTP.md` §6). To jedyna realna droga do `distinct` ≥ 4 dla `walk` (§14c).
- **Wybór trasy po krokach dla `walk`** — z zwróconych tras brać tę z najwięcej kroków mieszczącą się w limicie, nie min `generalizedCost`.
- **Model zastępczy (surrogate)** — mały model (np. las losowy) przewidujący f1/f2 z wag i cech pary pozwoliłby ocenić tysiące genomów
  bez OTP i trenować na wszystkich 10 parach przy niskim koszcie zapytań.
- **Jeden zestaw ticków dla wszystkich tras** — kubełkowanie po długości baseline (<20 / 20–40 / >40 min), osobny GA na kubełek.
- **Krótkie pary w `walk`** — gdy spacer jest najlepszy (np. `rynek_agh`, ~17 min pieszo), wszystkie ticki KMK odpadają (`no_route`) i suwak ma jedną pozycję.
- **Pora dnia** — liczymy dla poniedziałku 8:30; wieczorem i w weekend KMK jeździ inaczej.
- **Podjazdy** — kcal roweru nie uwzględniają `elevationGained`; dodać korektę MET za przewyższenie.
- **Prędkość użytkownika** — wagi liczone przy 1.33 / 4.5 m/s; backend nadpisuje prędkości (§13), ranking ząbków można przeliczyć dla 2–3 klas tempa.
- **Kroki jako 3. kryterium** — NSGA-II działa dla 3 celów; na razie kroki raportujemy (dla `walk` ≡ kcal, §10).
- **Porównanie z random search przy tym samym budżecie.** Quick (pop 12 × 5 pokoleń) to smoke test — front bywa znaleziony
  już w populacji startowej (HV rośnie: bike 299.756 → 308.056, walk 75.435 → 75.460). Przewagę GA nad losowaniem trzeba pokazać na budżecie full.
- **Pogoda i smog** nie są w GA — to bezpieczniki runtime (`lock_reason` w §13 blokuje s > 0.5).
