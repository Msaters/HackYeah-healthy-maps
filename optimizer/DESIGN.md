# Optymalizator wag OTP (NSGA-II) — dokument projektowy

Offline'owy algorytm genetyczny NSGA-II, który przybliża **front Pareto** OpenTripPlannera dla dwóch celów
— **czas przejazdu → min** i **ruch (aktywne kcal) → max** — i zwraca 3 gotowe profile wag OTP
(`fast` / `balanced` / `active`), które backend wkleja do zapytań `planConnection`.
Interfejsy wiążące: `.hy-loop/state.md` („Ustalone interfejsy”). Kontekst OTP: `docs/OTP.md` §2, §6, §11, §12.

## 1. Cel i motywacja

- **OTP nie minimalizuje czasu, tylko koszt uogólniony** (`generalizedCost`, `docs/OTP.md` §2): sekunda w KMK ≈ 1,
  sekunda chodzenia × `walk.reluctance`, sekunda roweru × `bicycle.reluctance`, plus kary za wejście,
  przesiadkę i czekanie. Domyślne `reluctance = 2.0` sprawia, że OTP z natury **unika ruchu**.
- Wagi to więc **pokrętło kompromisu czas/ruch**: obniżenie `walk.reluctance` sprawia, że minuta spaceru
  „kosztuje” mniej niż minuta w tramwaju, i OTP sam znajdzie trasę z większą liczbą kroków.
- **Dlaczego nie ręczne strojenie:** 10 parametrów oddziałuje na siebie nieliniowo (np. niska niechęć do roweru
  nic nie daje, gdy `access = WALK`), a efekt zależy od pary skąd–dokąd. Ręcznie dostroimy jeden punkt;
  GA daje cały front i wybiera z niego punkty w sposób powtarzalny i uzasadniony („to nie są magiczne liczby”).
- **Dlaczego offline:** jedna ocena genomu = kilka–kilkanaście zapytań do OTP (po jednym na parę OD).
  Pełny przebieg to ~3 tys. zapytań, ~15 min (§8) — za drogo na żądanie użytkownika. Liczymy raz,
  zapisujemy `profiles.json`, backend w runtime wysyła tylko 3 dodatkowe zapytania.

## 2. Genom

Genom `x ∈ [0,1]^10`; `genome.decode(x)` → `{"modes": …, "preferences": …}` = zmienne GraphQL `planConnection`.
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

## 3. Kryteria

Oba kryteria są **minimalizowane**:

- **f1 = średnia po parach `duration / baseline_fastest[pair]`** (`f_time_ratio`).
  `baseline_fastest` = najkrótszy `duration` z zapytania z domyślnymi wagami OTP (KMK + WALK, jak K1),
  liczony raz na parę; gdy KMK nie zwróci trasy — najkrótszy spacer. **Dlaczego względny, a nie minuty:** średnia w minutach byłaby zdominowana przez
  najdłuższe pary (+10 min na trasie 60-min przeważa +5 min na 15-min, choć ta druga to +33%).
  Stosunek waży każdą parę jednakowo i jest interpretowalny („trasa 1.3× dłuższa od najszybszej”).
  **f1 może być < 1:** baseline to najszybsza trasa *KMK + pieszo*, a rower bywa od niej szybszy
  (w quick seed 1 profil `fast` ma ~0.80×).
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
  zostaje osobnym zapytaniem K5–K7 (`docs/OTP.md` §6); kroki jako 3. kryterium → §10.

## 4. Ograniczenie (constraint) — limit wydłużenia trasy

Problem z `docs/OTP.md` §11: samo `latestArrival` przepuszcza absurdy (110 min pieszo zamiast 42 min
tramwajem — „też zdąży”). GA bez ograniczenia ochoczo by je wybierał, bo dają dużo kcal.

Dla każdej pary: `limit = baseline + max(15 min, 0.5 · baseline)`,
`cv_pair = max(0, duration − limit)` [min], a **brak trasy** (pusta odpowiedź / błąd) → `cv_pair = 60`.
`cv` genomu = średnia `cv_pair` po parach (dla pary bez trasy f1 przyjmuje `duration = 2·baseline`, kcal = 0). Próg 15 min chroni krótkie trasy (dla baseline 10 min
pozwala na 25 min, a nie 15), a 50% skaluje się dla długich.

**Przykład (Nowa Huta → AGH):** baseline = 42 min (tramwaj).
`limit = 42 + max(15, 0.5·42) = 42 + max(15, 21) = 63 min`.
- wariant 110 min pieszo: `cv = max(0, 110 − 63) = 47` → **niedopuszczalny**, odrzucony przy selekcji;
- wariant 50 min (rower + tramwaj): `cv = max(0, 50 − 63) = 0` → dopuszczalny, konkuruje w f1/f2.

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
- **Krzyżowanie SBX** (η_c = 15, p_c = 0.9) i **mutacja wielomianowa** (η_m = 20, p_m = 1/D = 1/10),
  oba z obcięciem do [0,1]. Duże η → potomkowie blisko rodziców (lokalne doszlifowanie).
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

**Ryzyko przeuczenia** — wagi dopasowane do 10 konkretnych relacji (np. jedna linia tramwajowa
dominuje wynik). Ograniczamy je przez: zróżnicowanie długości i kierunków; względną miarę czasu;
ograniczenie §4 liczone per para (profil nie może poświęcić jednej pary dla średniej);
docelowo walidację na odłożonych parach (§10).

## 8. Wydajność i cache

**Budżet:** liczba ewaluacji = `pop × (gens + 1)` (populacja startowa + `gens` pokoleń potomków);
zapytania = ewaluacje × pary, + 1 zapytanie baseline na parę.

| Tryb | pop | gens | pary | zapytania GA | + baseline | Czas na zimno | Na ciepło (cache) |
|---|---|---|---|---|---|---|---|
| quick | 12 | 4 | 4 | 12 × 5 × 4 = **240** | +4 | **~30–65 s** (zmierzone) | **0.5 s** |
| full | 24 | 12 | 10 | 24 × 13 × 10 = **3120** | +10 | ~15 min (szacunek) | — |

**Trybu full nie uruchamiamy** — decyzja zespołu: produktem tej części jest projekt algorytmu;
przebieg quick służy jako dowód działania. Komenda i budżet full są gotowe (`run_ga --mode full`).

- **Zmierzona przepustowość OTP:** ~3.0 zapytań/s przy 6 wątkach, ~3.4–3.7 przy 8–12 wątkach —
  OTP nasyca CPU przy ~8 wątkach. Domyślnie `--workers 10`. (Wynika z tego ~2 s na zapytanie
  przy 6 wątkach — wyszukiwanie rowerowe po grafie ulic jest kosztowne.)
- **`searchWindow` bez zysku:** skrócenie okna (np. `PT30M`) nie przyspiesza wyraźnie, a zmienia zestaw
  zwracanych tras, a więc wynik oceny — zostajemy przy domyślnym.
- **Deduplikacja w paczce:** `plan_many` liczy klucz każdego żądania i wysyła do OTP tylko unikalne
  (w generacji wiele genomów dekoduje się do tego samego zapytania — kategorie, zaokrąglenia).
- **Cache JSONL:** klucz = `sha1` znormalizowanego żądania (zapytanie + zmienne, `json.dumps(sort_keys=True)`),
  wartość = surowa odpowiedź; dopisywane linia po linii (bezpieczne przy przerwaniu). Zysk:
  powtórzone genomy między generacjami i ponowne uruchomienia (ten sam seed, zmiana raportu/profili)
  **nie kosztują zapytań**. Cache jest ważny dla konkretnego grafu i daty — po przebudowie grafu usuwamy plik.

## 9. Profile wyjściowe

Z dopuszczalnego (cv = 0) pierwszego frontu wybieramy 3 punkty:
- **`fast`** = min f1 (najbliżej najszybszej trasy),
- **`active`** = max aktywnych kcal (min f2),
- **`balanced`** = **punkt kolana**: po normalizacji f1 i f2 do [0,1] w obrębie frontu — punkt o największej
  odległości od prostej łączącej `fast` i `active` (największy „zysk kcal za minutę”). Gdy front ma < 3 punkty,
  `balanced` = jeden ze skrajnych (profile mogą się powtarzać).

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

**Użycie w backendzie:** profile to **3 dodatkowe zapytania** obok sztywnych kandydatów K1–K7
(`docs/OTP.md` §6) — wysyłane równolegle do wspólnej puli. **Wybór kart pozostaje w backendzie**:
odrzucenie tras, które nie zdążą (`end` > termin − 3 min), limit wydłużenia z §4, wybór Najszybsza /
Cel kaloryczny / Cel kroków i deduplikacja kart z tą samą trasą. GA tylko wzbogaca pulę o kandydatów,
których ręczne wagi by nie znalazły.

## 10. Ograniczenia i dalsze kroki

- **Jeden zestaw profili dla wszystkich tras** — dla krótkich relacji optymalne wagi mogą być inne niż dla
  długich. Krok dalej: kubełkowanie po długości baseline (np. <20 / 20–40 / >40 min), osobny GA na kubełek.
- **Pora dnia / szczyt** — liczymy dla poniedziałku 8:30; wieczorem i w weekend częstotliwość KMK jest
  inna. Możliwe: kilka dat w zestawie ocen albo profile per pora dnia.
- **Podjazdy** — kcal roweru nie uwzględniają `elevationGained`; dodać korektę MET za przewyższenie.
- **Prędkość użytkownika** — profile liczone przy 1.33 / 4.5 m/s; przy innej prędkości użytkownika
  można przeliczyć GA dla 2–3 klas tempa.
- **Pełny przebieg (full)** i pomiar stabilności profili między seedami — po hackathonie.
- **Kroki jako 3. kryterium** — NSGA-II działa dla 3 celów (czas, kcal, kroki); front staje się powierzchnią,
  wybór profili trudniejszy. Dałoby to profil „kroki” z GA zamiast sztywnych K5–K7; na razie kroki raportujemy.
- **Walidacja na odłożonych parach** — 10 par treningowych + np. 5 testowych, raport f1/f2 profili
  na parach, których GA nie widział (miara przeuczenia).
- **Pogoda i smog** nie są w GA — to bezpieczniki runtime w backendzie (wyłączają promowanie `active`).
- **Porównanie z random search przy tym samym budżecie.** Quick (pop 12 × 5 pokoleń) to smoke test — front bywa znaleziony już w populacji startowej (HV rośnie minimalnie). Przewagę GA nad losowaniem trzeba pokazać na budżecie full; dodatkowo: usuwanie duplikatów w przestrzeni celów przy selekcji przeżycia (różnorodność) i scalanie punktów o identycznych (f1, f2) w raporcie.
