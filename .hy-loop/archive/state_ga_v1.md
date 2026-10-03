# hy-loop — GA (NSGA-II) przybliżający front Pareto OTP: czas min, ruch max → profile wag OTP
Start: 2026-10-03 17:43 · Deadline: 2026-10-04 23:00 · Runda: 2
Decyzje użytkownika: kod od razu; tryb offline (profile wag liczone z góry).

## Ustalone interfejsy (wiążące dla wykonawców)
- Pakiet `optimizer/`, uruchamianie `python3 -m optimizer.<moduł>` z katalogu repo; tylko stdlib + numpy; testy `unittest`.
- Genom `x ∈ [0,1]^D` (D=10 od rundy 2; prędkości stałe 1.33/4.5 m/s): walk.reluctance [0.5,5] log · bicycle.reluctance [0.5,5] log · triangle safety/flatness/time (3 geny → suma 1) · transit.board.waitReluctance [0.5,2] · transit.transfer.cost [0,600] · BUS cost.reluctance [0.8,3] · access {WALK,BICYCLE,BICYCLE_PARKING} · direct {brak,WALK,BICYCLE}. egress/transfer = BICYCLE gdy access=BICYCLE, inaczej WALK. Bez BICYCLE_RENTAL.
- `genome.decode(x) -> {"modes":..., "preferences":...}` = zmienne GraphQL planConnection.
- f1 = śr. `duration/baseline_fastest[pair]`; f2 = −śr. aktywne kcal @70 kg (WALK MET 3.5, BICYCLE MET 7.0). Oba minimalizowane.
- cv = śr. `max(0, duration − (baseline + max(15 min, 0.5·baseline)))` [min] + 60 za brak trasy; constraint-domination Deba.
- Wybór trasy z odpowiedzi: min `generalizedCost`. Zapytania: latestArrival 2026-10-05T08:30+02:00, first 3.
- `front.json`: `{"meta":{...},"front":[{"x","query":{modes,preferences},"f_time_ratio","active_kcal","steps","duration_min","cv","per_pair":[...]}]}`
- `profiles.json`: `{"fast"|"balanced"|"active": {"modes","preferences","metrics":{...}}}`
- Budżety (ZMIENIONE po pomiarach: ~3.0 zapyt./s przy 6 wątkach, ~3.5 przy 8–12; domyślnie 10 wątków): quick pop=12 gen=4 4 pary (~240 zapytań, < 3 min); full pop=24 gen=12 10 par (~3120 zapytań, < 25 min).

## Zadania
| ID | Zadanie | Zależy od | Pliki | Status | Iteracje | Ostatni werdykt |
|---|---|---|---|---|---|---|
| T1 | Dokument projektowy | — | optimizer/DESIGN.md | DONE | 1 | PASS w recenzji całościowej |
| T2 | Genom | — | optimizer/__init__.py, optimizer/genome.py, optimizer/tests/__init__.py, optimizer/tests/test_genome.py | DONE | 2 | PASS (iter 1) + iter 2 zweryfikowana w recenzji całościowej |
| T3 | Rdzeń NSGA-II | — | optimizer/nsga2.py, optimizer/tests/test_nsga2.py | DONE | 1 | PASS 9/10 |
| T4 | Ocena przez OTP + pary OD | — | optimizer/evaluate.py, optimizer/od_pairs.json, optimizer/tests/test_evaluate.py, optimizer/tests/fixtures/otp_response.json | DONE | 2 | PASS w recenzji całościowej |
| T5 | CLI run_ga + profile | T2,T3,T4 | optimizer/run_ga.py, optimizer/profiles.py, optimizer/tests/test_profiles.py, optimizer/.gitignore | DONE | 2 | PASS w recenzji całościowej |
| T6 | Raport SVG + MD | — | optimizer/report.py, optimizer/tests/test_report.py, optimizer/tests/fixtures/front_sample.json | DONE | 3 | PASS 8.5/10 + szlif zweryfikowany |
| T7 | Test integracyjny (quick, opcjonalny skip) + README; BEZ pełnego przebiegu full | T5,T6 | optimizer/tests/test_integration_otp.py, optimizer/README.md | DONE | 1 | PASS w recenzji całościowej |

## Kryteria akceptacji
Pełna lista w planie orchestratora (skrót):
- T1: ≥8 sekcji `## ` (Genom, Kryteria, Ograniczenie, Wybór trasy, NSGA-II, Pary OD, Wydajność/cache, Profile); opis kary dla 110 vs 42 min z progami 15 min/50%; budżet zapytań quick/full; tabela genów zgodna z genome.py.
- T2: `python3 -m unittest optimizer.tests.test_genome -v` OK (1000 genomów, triangle=1, zakresy, brzegi 0/1, brak BICYCLE_RENTAL, access=BICYCLE → egress/transfer BICYCLE); decode → JSON z modes/preferences.
- T3: `python3 -m unittest optimizer.tests.test_nsga2 -v` OK (dominates z cv, sortowanie 6 pkt, crowding, SBX/mutacja w [0,1] i deterministyczne); ZDT1 D=10 pop=40 gen=60 seed=1 → HV(1.1,1.1) ≥ 0.6, < 20 s.
- T4: `python3 -m unittest optimizer.tests.test_evaluate -v` OK bez OTP (kcal ≈204.2±0.5, kroki ≈1102±2, tramwaj 0 kcal, pick po generalizedCost, cv 110 vs 42 > 0, 50 vs 42 = 0); od_pairs 10/4 w bbox; z OTP: drugi raz 100% cache < 0.2 s.
- T5: quick < 2 min exit 0, log per generacja; profiles fast/balanced/active z monotonią; profil active działa w zapytaniu; test_profiles OK (kolano); determinizm.
- T6: test_report OK (SVG parsowalne, ≥N circle, etykiety Szybki/Zbalansowany/Aktywny); CLI tworzy front.svg + front.md z 3 wierszami; wygląd nadaje się na slajd.
- T7: test integracyjny OK < 3 min lub skipped; discover OK; full < 20 min, active ≥ 1.5× kcal fast; README z komendami i przykładem.

## Decyzje dla zespołu (przyjęte domyślne, do potwierdzenia)
- f2 = aktywne kcal @70 kg; profile jako dodatkowe zapytania obok K1–K6; jeden zestaw profili; unittest.

## Dziennik
- 17:50 Plan orchestratora przyjęty. Start T1, T2, T3, T4, T6 równolegle.
- 17:53 T3 iter 1: wykonawca GOTOWE (16 testów, ZDT1 HV 0.847 w 4.9 s) → recenzja
- 17:53 T1 iter 1: wykonawca GOTOWE (10 sekcji, 192 linie) → recenzja po zakończeniu T4
- 17:54 T3: PASS 9/10. Sugestie dla T5: F zawsze skończone (nan_to_num), deduplikacja X/F przed eksportem front.json.
- 17:54 T2 iter 1: wykonawca GOTOWE (15 testów, 31/31 walidacji OTP) → recenzja
- 17:55 T6 iter 1: wykonawca GOTOWE (11 testów, render chrome) → recenzja
- 17:55 T2: PASS 9/10. Sugestia dla T5: nan_to_num przed decode.
- 17:57 T6: PASS 8.5/10; wysłany szlif (liczebniki, etykieta przy 2 punktach, legenda cv>0).
- 17:57 T4 iter 1: wykonawca GOTOWE; przepustowość 2.4 zapyt./s → budżety zmniejszone. Recenzja T4 + start T5 równolegle.
- 17:57 T1: do aktualizacji po T5 (szacunek 15–25 zapyt./s w DESIGN.md jest nieaktualny).
- 17:58 T4: PASS 8/10. Decyzja evaluatora: genom bez direct (transitOnly) na krótkiej parze dostaje WALKING_BETTER_THAN_TRANSIT → dziś kara 60 (cv), co sztucznie wypycha populację do direct. W aplikacji backend i tak pokaże trasę pieszą, więc w T4 iter 2 (PO zakończeniu T5, żeby nie psuć pomiarów determinizmu) taki przypadek liczymy jako trasę pieszą (baseline pieszy pary), bez kary. Też: deduplikacja zapytań w paczce, poprawka opisu dystansu rynek_agh w meta.
- 17:59 T6 szlif (iter 2): 17 testów OK (sprawdzone przez evaluatora), liczebniki/etykiety/legenda/odporność.
- 18:01 DECYZJA UŻYTKOWNIKA: cel to sam projekt algorytmu — NIE uruchamiamy trybu full (~3000 zapytań). T7 bez pełnego przebiegu i bez commitowania wynikowego profiles.json; tylko README + test integracyjny w trybie quick.
- 18:09 T5 iter 1: wykonawca GOTOWE — quick zimny 64 s (233 zapytania, ~3.7 q/s), ciepły 0.5 s, determinizm OK, 70 testów OK, front 12 pkt, profile fast 0.70×/75 kcal, balanced 0.82×/231, active 1.06×/300. Wątki 8–12 ≈ +10–15% vs 6; searchWindow bez zysku.
- 18:09 RUNDA 2 (decyzje evaluatora po przebiegu quick):
  - Prędkości walk/bicycle usunięte z genomu (GA „kupował” kcal wolniejszą jazdą; prędkość = cecha użytkownika) → T2 iter 2, stałe 1.33 / 4.5 m/s.
  - WALKING_BETTER_THAN_TRANSIT → metryki trasy pieszej zamiast kary → T4 iter 2.
  - Oś X: baseline = najszybsza trasa KMK (wartości < 1 możliwe) → T6 iter 3.
  - Front 100% rowerowy przy f2 = kcal jest zgodny z celem (rower MET 7 > pieszo 3.5); karta „Cel kroków” pozostaje osobnym zapytaniem K5–K7 — opisać w DESIGN.md (T1).
- 18:10 T4 iter 2: GOTOWE, 13 testów OK (sprawdzone przez evaluatora); fallback pieszy działa na żywo (rynek_agh cv 0). Recenzja w ramach oceny całościowej.
- 18:10 T6 iter 3: GOTOWE, 19 testów OK; oś „względem najszybszej trasy komunikacją”, linia 1,0×. Uwaga dla T5: front.json eksportować tylko niezdominowane punkty (report.py nie filtruje).
- 18:11 T2 iter 2: GOTOWE, DIM=10, stałe prędkości 1.33/4.5, 21/21 walidacji OTP. Start T5 iter 2 (ponowny quick na nowym modelu).
- 18:59 T1 iter 2: GOTOWE (220 linii, 10 sekcji, zgodne z kodem po rundzie 2). Interfejsy w state.md zaktualizowane do D=10; poprawiony nieaktualny docstring fallbacku w evaluate.py.
- 19:01 T5 iter 2: front tylko niezdominowane, meta.queries ze stats; profile fast 0.80×/107 kcal, balanced 0.83×/197, active 0.90×/254; front 100% rowerowy, fallback 0 par. OTP nie jest w 100% deterministyczny na zimno (1/150 odpowiedzi) — powtarzalność gwarantuje cache. Start T7.
- 19:07 T7: GOTOWE (85 testów, integracyjny quick 52 s, skip przy OTP_URL niedostępnym, przykład README wykonany). Poprawiony komentarz w optimizer/.gitignore. Start recenzji całościowej.
- 19:11 RECENZJA CAŁOŚCIOWA: PASS 8.5/10. 85 testów OK (80 + skip bez OTP), README wykonany krok po kroku, quick 32 s, profile monotoniczne także na 6 parach spoza quick (active 1.36× kcal fast, cv 0), wykres gotowy na slajd, repo czyste (21 plików, 212 KB).
- 19:11 Poprawione przez evaluatora: nieaktualne liczby w DESIGN.md (0.70× → ~0.80×, ~64 s → 30–65 s), doprecyzowanie „bez duplikatów” w README, punkt o random search / różnorodności w DESIGN §10.
- 19:11 KONIEC PĘTLI (2 rundy). Otwarte sugestie (nieblokujące): scalanie punktów o identycznych metrykach w raporcie, usuwanie duplikatów celów w selekcji, porównanie z random search na budżecie full, balanced ≈ active na quick.
