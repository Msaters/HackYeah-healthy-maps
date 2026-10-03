# Optymalizator wag OTP — skrót algorytmu

NSGA-II (algorytm genetyczny, wielokryterialny) liczony **offline**. Szuka wag zapytania OTP, które dają najlepsze kompromisy **czas ↔ ruch**, i zwraca je jako gotowe profile. Szczegóły: `DESIGN.md`.

## Problem
- OTP minimalizuje **koszt uogólniony**, nie czas: minuta chodzenia lub roweru „kosztuje” domyślnie 2× minutę w tramwaju, więc OTP unika ruchu.
- Wagi (`reluctance`, kary, tryby) przesuwają ten kompromis. GA szuka ich automatycznie.

## Genom (10 genów, x ∈ [0,1])
| # | Parametr OTP | Zakres |
|---|---|---|
| 0 | `walk.reluctance` | 0.5–5 (skala log) |
| 1 | `bicycle.reluctance` | 0.5–5 (skala log) |
| 2–4 | rower: `triangle {safety, flatness, time}` | suma = 1 |
| 5 | `waitReluctance` | 0.5–2 |
| 6 | `transfer.cost` | 0–600 s |
| 7 | waga autobusu (`BUS cost.reluctance`) | 0.8–3 |
| 8 | dojazd do przystanku (`access`) | WALK / BICYCLE / BICYCLE_PARKING |
| 9 | trasa bez KMK (`direct`) | brak / WALK / BICYCLE |

- Kategorie: `floor(x·3)`.
- Prędkości są **stałe** (1.33 / 4.5 m/s), nie są genami. Inaczej GA zwiększałby kalorie, ustawiając wolniejszą jazdę.

## Ocena osobnika
Dla 10 par skąd–dokąd w Krakowie (quick: 4) wysyłamy zapytanie OTP i bierzemy trasę z najmniejszym `generalizedCost`.

| Funkcja | Wzór | Kierunek |
|---|---|---|
| **f1 — czas** | średnia `czas / czas_najszybszej_trasy_KMK` | min |
| **f2 — ruch** | −średnie **aktywne kcal** @70 kg (pieszo MET 3.5, rower MET 7.0, KMK 0) | min (czyli max kcal) |
| **cv — ograniczenie** | średnia `max(0, czas − (baseline + max(15 min, 50%·baseline)))`; brak trasy = 60 | 0 = dopuszczalny |

- Jeśli pieszo jest lepiej niż komunikacją, liczymy trasę pieszą, bez kary.
- **Dominacja z ograniczeniem (Deb):**
  - dopuszczalny wygrywa z niedopuszczalnym;
  - z dwóch niedopuszczalnych wygrywa ten z mniejszym `cv`;
  - z dwóch dopuszczalnych rozstrzyga zwykła dominacja Pareto.

## Pętla NSGA-II
1. **Start:** losowa populacja (quick: 12, full: 24).
2. **Selekcja:** turniej binarny. Wygrywa osobnik z niższego frontu, a przy remisie ten z większym crowding distance (bardziej odosobniony).
3. **Krzyżowanie:** SBX, η = 15, p = 0.9.
4. **Mutacja:** wielomianowa, η = 20, p = 1/10 na gen; wynik obcięty do [0,1].
5. **Ocena** potomków przez OTP: jedna paczka na pokolenie, 10 wątków, cache na dysku.
6. **Przeżycie (μ+λ):** rodzice + dzieci → sortowanie niezdominowane → wybieramy całe fronty, a ostatni front obcinamy wg crowding distance.
7. Powtarzamy kroki 2–6 (quick: 4 pokolenia, full: 12). Postęp mierzy hiperobjętość (HV) względem punktu (2.0, 0).

## Wynik
- `front.json`: punkty niezdominowane i dopuszczalne, każdy z gotowymi `modes`/`preferences` do zapytania OTP.
- `profiles.json`: 3 profile:
  - **fast**: min czasu;
  - **active**: max kcal;
  - **balanced**: punkt kolana (najdalej od prostej łączącej skrajne punkty).
- `front.svg` / `front.md`: wykres i tabela.

## Koszt
- Liczba zapytań = pop × (pokolenia + 1) × pary.
- quick ≈ 240 zapytań, ok. 30–65 s.
- full ≈ 3120 zapytań, ok. 15 min. Nieuruchamiany.
- OTP przetwarza ok. 3.5 zapytania/s.

## Znane ograniczenia
- Przy f2 = kcal front jest rowerowy (MET roweru 2× większy niż chodzenia). Kroki obsługujemy osobnym zapytaniem.
- Na quick profile balanced i active są prawie identyczne, a front jest wąski (0.80–0.90×).
- OTP nie jest w 100% deterministyczny bez cache (ok. 1 na 150 zapytań). Powtarzalność daje dopiero cache.
- Profil to średnia z 10 par. Dla konkretnej trasy użytkownika wynik może odbiegać.
