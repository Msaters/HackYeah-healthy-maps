# hy-loop — optimizer: suwak „czas ↔ ruch” + tick [mam rower]
Start: 2026-10-03 19:48 · Deadline: 2026-10-04 23:00 · Runda: 2
Poprzednia pętla (GA v1): `.hy-loop/archive/state_ga_v1.md`.
Decyzje użytkownika: bez trybu full (projekt algorytmu); quick dozwolony. stdlib + numpy, unittest. Bez backendu/frontendu — to, czego użyje backend, jest biblioteką w `optimizer/`.
Decyzje przyjęte domyślnie (do potwierdzenia przez zespół): f2 dla walk = kcal (ranking ≡ kroki); kotwica K1 w populacji startowej + zawsze kandydat online; `slider.json` = `{meta, ticks}` w katalogu wariantu; blokada smog/pogoda `lock_above_s = 0.5`; online 9 zapytań (7 ząbków + K1 + spacer).

## Ustalone interfejsy (wiążące)
**genome.py**
- `VARIANTS = ("bike","walk")`; `decode(x, variant="bike")`. Wariant walk:
  - `access=[WALK]`, `egress`/`transfer` = WALK;
  - gen `direct` ∈ [None, "WALK"] przez `floor(x·2)`;
  - bez `preferences.street.bicycle`.
- `active_mask(variant)`: dla walk geny 1–4 i 8 mają False.
- `canonical(x, variant)`: nieaktywne geny ustawia na 0.5.
- `ANCHOR_VALUES` (K1): walk.reluctance 2.0, waitReluctance 1.0, transfer.cost 0, BUS 1.0, access WALK, direct None.
- `encode_anchor(variant) -> x`: `decode(encode_anchor(v), v)` ma `transitOnly: True` i wartości z `ANCHOR_VALUES`.

**nsga2.py**
- `nsga2(evaluate_batch, dim, pop, gens, rng, callback=None, X0=None, dedupe_decimals=6)`.
- `X0` (k×dim, k ≤ pop) zastępuje pierwsze k osobników populacji startowej.
- Przeżycie: duplikaty `round(F, dedupe_decimals)` idą za wszystkie fronty. Zostaje kopia o najniższym ranku, przy remisie ta o mniejszym indeksie.
- `dedupe_decimals=None` = zachowanie jak dotąd.
- Helper `survival_select(F, cv, pop, dedupe_decimals) -> list[int]`.

**slider.py** (offline)
- `arc_positions(points)`:
  - punkty sortowane po `f_time_ratio` rosnąco;
  - f1 i `active_kcal` normalizowane do [0,1] w obrębie frontu;
  - skumulowana odległość euklidesowa podzielona przez całkowitą długość;
  - pierwszy punkt 0, ostatni 1, jeden punkt → [0.0].
- `sample_front(front, n=7)`: ząbek i ma cel `s_i = i/(n−1)` i dostaje punkt o najbliższym u; przy remisie mniejszy czas.
- Tick = `{"s","u","index","modes","preferences","metrics":{f_time_ratio,active_kcal,steps,duration_min}}`.
- `build_slider(front_doc, n=7) -> dict`.
- Schemat `slider.json`: `{"meta":{"variant","n","f1":"f_time_ratio","f2":"active_kcal","distinct","source":"front.json","generated"},"ticks":[...]}`.
- CLI: `python3 -m optimizer.slider <front.json> [--n 7] [--variant bike|walk] [--out PATH]`.

**Wyniki:** `optimizer/out/quick_bike/` i `optimizer/out/quick_walk/`, w każdym: `front.json`, `profiles.json`, `slider.json`, `front.svg`, `front.md`.

**run_ga**
- Flagi: `--variant bike|walk` (domyślnie bike), `--ticks N` (domyślnie 7), `--no-anchor`.
- decode = `canonical` + `decode(·, variant)`.
- `X0 = [encode_anchor(variant)]`, `dedupe_decimals = 6`.
- `meta.variant`, `meta.anchor` = metryki K1 + `in_front`.
- `profiles.json` bez zmian; fast ≡ tick 0, active ≡ tick n−1.

**slider_select.py** (online, dla backendu)
- `tick_requests(slider, origin, destination, include_anchor=True, include_walk=True, walk_speed=None, bike_speed=None)`:
  - żądania dla `OTPClient.plan_many`: n ząbków, potem `"anchor"` (`BASELINE_TRANSIT`), potem `"walk"` (`BASELINE_WALK`);
  - każde żądanie ma pole `tag`: `tick:i` / `anchor` / `walk`.
- `build_route_slider(results, requests, deadline, baseline_min=None, *, weight=70.0, height=1.75, buffer_min=3.0, lock_reason=None, lock_above_s=0.5) -> dict`, kolejne kroki:
  1. `baseline_min` = najszybsza trasa z `anchor`, a gdy jej brak, z `walk`;
  2. z każdej odpowiedzi trasa o min `generalizedCost`;
  3. odrzucenie tras z `end > deadline − buffer` (licznik `late`) i z `cv > 0` (licznik `too_long`; limit = 190% baseline);
  4. scalanie po sygnaturze `(mode, round(duration/30), round(distance/50))` per odcinek (licznik `duplicate`);
  5. sortowanie po czasie, filtr niezdominowanych, `arc_positions`.
- Wynik: `{"positions":[{"s","route_key","sources","metrics":{duration_min,active_kcal,steps,end,slack_min,modes},"itinerary","locked"}],"default_index","lock_reason","dropped":{late,too_long,no_route,duplicate,dominated},"baseline_min"}`.
- `locked = lock_reason is not None and s > lock_above_s`.
- CLI: `python3 -m optimizer.slider_select --slider PATH --pair ID | --from lat,lon --to lat,lon --deadline ISO [--no-cache] [--lock smog]`.

**slider_eval.py**
- CLI: `python3 -m optimizer.slider_eval --slider PATH [--pairs held-out|all] [--out PATH.json]`.
- Pary held-out: 6 par spoza quick.
- `monotonic_rate`: surowe ząbki mają niemalejący czas i kcal (tolerancja 0.5 min / 1 kcal).
- `mean_distinct`, `mean_positions`.
- `build_s_p50` / `build_s_max`: bez cache, OTP rozgrzany, workers=8.

## Zadania
| ID | Zadanie | Zależy od | Pliki | Status | Iteracje | Ostatni werdykt |
|---|---|---|---|---|---|---|
| T1 | Warianty genomu, active_mask, canonical, kotwica K1 | — | optimizer/genome.py, optimizer/tests/test_genome.py | DONE | 1 | PASS 9/10 |
| T2 | NSGA-II: dedupe w przestrzeni celów, X0 | — | optimizer/nsga2.py, optimizer/tests/test_nsga2.py | DONE | 2 | PASS 8.5/10 + iter 2 zweryfikowana (legacy w tym samym procesie) |
| T3 | slider.py (arc-length, sample_front, CLI) | — | optimizer/slider.py, optimizer/tests/test_slider.py | DONE | 1 | PASS 9/10 |
| T4 | slider_select.py (online, blokada, CLI) | — | optimizer/slider_select.py, optimizer/tests/test_slider_select.py, optimizer/tests/fixtures/route_ticks_sample.json | DONE | 3 | PASS (iter 1) + iter 2–3 zweryfikowane w recenzji całościowej |
| T5 | Raport: ząbki na wykresie + tabela „Suwak” | — | optimizer/report.py, optimizer/tests/test_report.py, optimizer/tests/fixtures/slider_sample.json | DONE | 2 | PASS 9/10 + szlif obejrzany przez evaluatora |
| T6 | run_ga --variant/--ticks/--no-anchor, kotwica, slider.json; quick bike + walk | T1,T2,T3,(T5) | optimizer/run_ga.py, optimizer/profiles.py, optimizer/tests/test_profiles.py, optimizer/tests/test_run_ga.py, optimizer/tests/test_integration_otp.py | DONE | 1 | PASS 8.5/10 |
| T7 | slider_eval.py + demo live slider_select | T4,T6 | optimizer/slider_eval.py, optimizer/tests/test_slider_eval.py | DONE | 1 | pomiary gotowe (cele jakościowe częściowo niespełnione — runda 2) |
| T9 | Walk: dźwignia chodzenia (sonda + gen aktywny tylko w walk) | T1 | optimizer/genome.py, optimizer/tests/test_genome.py | DONE | 1 | zweryfikowane w recenzji całościowej |
| T10 | Scalanie punktów frontu bliższych niż ε (slider) | T3 | optimizer/slider.py, optimizer/tests/test_slider.py | DONE | 1 | zweryfikowane w recenzji całościowej |
| T11 | Ponowne quick bike+walk + slider_eval po T9/T10 | T9,T10 | optimizer/out/* (wyniki) | DONE | 1 | przeliczone: bike distinct 5.33 ✓, monotonia 0.00 ✗; walk distinct 1.17 ✗; build ≤1.4 s ✓ |
| T8 | Dokumentacja (DESIGN, SKRÓT, README) | T6,T7 | optimizer/DESIGN.md, optimizer/PLIKI.md, optimizer/README.md | DONE | 1 | 15 sekcji DESIGN, README przepisany (komendy + przykład backendu uruchomione), PLIKI kompletne |

## Kryteria akceptacji
### T1
- `python3 -m unittest optimizer.tests.test_genome -v` OK; stare testy dla `bike` przechodzą bez zmian.
- Wariant walk, 1000 losowych x:
  - `access == ["WALK"]`;
  - `direct` ∈ {transitOnly, ["WALK"]};
  - nigdy BICYCLE;
  - brak `street.bicycle`.
- `decode(canonical(x,"walk"),"walk") == decode(x,"walk")`; x różniące się tylko genami 1–4 i 8 → identyczne po `canonical`.
- `decode(encode_anchor(v), v)` dla obu wariantów: `transitOnly: True`, walk.reluctance 2.0, waitReluctance 1.0, transfer.cost 0, BUS 1.0.
- Na żywym OTP: kotwica walk dla nowa_huta_agh daje ≥ 1 trasę bez BICYCLE.

### T2
- `python3 -m unittest optimizer.tests.test_nsga2 -v` OK, w tym ZDT1 HV ≥ 0.6 w < 20 s.
- `survival_select`: 10 punktów z 4 kopiami, pop=6 → 6 unikalnych; gdy unikalnych jest za mało, duplikaty uzupełniają do pop.
- `X0`: wiersz 0 po generacji 0 równa się `x_anchor`; przebieg deterministyczny.
- `dedupe_decimals=None` daje wynik identyczny jak przed zmianą.

### T3
- `python3 -m unittest optimizer.tests.test_slider -v` OK.
- `arc_positions`: 3 punkty współliniowe → [0, .5, 1]; wartości niemalejące; jeden punkt → [0.0].
- `sample_front(..., 7)`:
  - 7 ticków, s = i/6;
  - tick 0 = min czasu, tick 6 = max kcal;
  - kolejne ticki mają niemalejący czas i kcal.
- Front 2-punktowy → 7 ticków, `distinct == 2`.
- CLI na `optimizer/tests/fixtures/front_sample.json` kończy się exit 0 i zapisuje plik zgodny ze schematem.

### T4
- `python3 -m unittest optimizer.tests.test_slider_select -v` OK bez OTP.
- `tick_requests`:
  - 9 żądań z tagami `tick:0..6`, `anchor`, `walk`;
  - `walk_speed` zmienia tylko kopię, slider wejściowy bez zmian.
- `build_route_slider`:
  - trasa kończąca się 2 min przed terminem przy buforze 3 → `late`;
  - 110 min vs baseline 42 → `too_long`;
  - 3 ticki z tą samą trasą → 1 pozycja z 3 źródłami;
  - pozycje posortowane, kcal niemalejące, s od 0 do 1.
- Blokada:
  - `smog` → `locked == (s > 0.5)`, `default_index` wskazuje pozycję niezablokowaną;
  - bez `lock_reason` nic nie jest zablokowane.
- Same odrzucenia → `positions == []` i komplet liczników, bez wyjątku.
- (po T6) CLI live dla nowa_huta_agh wypisuje ≥ 1 pozycję i czas budowy.

### T5
- `python3 -m unittest optimizer.tests.test_report -v` OK, łącznie ze starymi 19 testami.
- SVG z `slider_sample.json`: parsowalny, zawiera n elementów `class="tick"` z etykietami; bez slidera elementów `tick` nie ma.
- `front.md` zawiera tabelę „Suwak” z n wierszami.
- Render obejrzany: ząbki czytelne, nie zasłaniają etykiet profili, wykres nadaje się na slajd.

### T6
- Testy `test_run_ga` (z fałszywym evaluatorem) i `test_profiles` OK bez OTP:
  - walk → brak BICYCLE w żadnym punkcie;
  - `slider.meta.variant == "walk"`;
  - `profiles.fast` ≡ tick 0, `profiles.active` ≡ tick n−1.
- quick bike → `out/quick_bike`: exit 0 w < 3 min; powstają front, profiles, slider (7 ticków) i svg z ząbkami; `meta.anchor` obecne.
- quick walk → `out/quick_walk`: exit 0; brak BICYCLE w `per_pair.modes`; `steps` ticku 6 > `steps` ticku 0.
- Na froncie żadne dwa punkty nie mają identycznego (f1, f2) po zaokrągleniu do 4 miejsc.
- `python3 -m unittest discover -s optimizer/tests -t .` OK; test integracyjny sprawdza `slider.json`.

### T7
- `test_slider_eval` OK bez OTP.
- `slider_eval` dla bike i walk → JSON z metrykami dla 6 par held-out.
- Wyniki raportowane bez naginania. Cele: monotonia ≥ 0.8, distinct ≥ 4, build < 2 s; każdy niespełniony cel opisany z hipotezą przyczyny.
- Demo live `slider_select` dla 2 tras × 2 warianty.

### T8
- DESIGN.md:
  - ≥ 12 sekcji `## `;
  - nowe sekcje: Suwak, Tick [mam rower] (z uzasadnieniem f2 = kcal dla walk), Kotwica i różnorodność, Dopasowanie online.
- Wszystkie komendy z README wykonane kopiuj-wklej kończą się exit 0.
- Przykład backendu w README (`tick_requests` → `plan_many` → `build_route_slider`) uruchomiony.
- Liczby spójne z `slider_eval.json` i `meta`; `PLIKI.md` aktualny (każdy plik w optimizer/ opisany, w tym slider_eval.py).

## Dziennik
- 19:55 Plan przyjęty (decyzje zespołowe przyjęte domyślnie, patrz wyżej). Start T1–T5 równolegle.
- 19:56 T1: wykonawca GOTOWE (27 testów; decode bike identyczny ze starym; encode_anchor kanoniczny) → recenzja.
- 19:56 T3: wykonawca GOTOWE (20 testów). KONTRAKT dla T6/T4: tick.index = indeks w `sorted_front(front)`, nie w oryginalnym front; sample_front robi pareto_filter; NIE filtruje cv>0 → T6 filtruje przed build_slider. → recenzja.
- 19:56 T2: wykonawca GOTOWE (26 testów; dedupe domyślnie, None = legacy wg hashy) → recenzja (ryzyko: kruchy test hashy).
- 19:57 T3: PASS 9/10 (arc-length sprawdzony na froncie wklęsłym i z kolanem). Sugestia dla T6: przepisać meta.feasible_front do slider.meta / ostrzeżenie; meta.distinct = różne punkty frontu, nie różne trasy OTP.
- 21:40 T1: PASS 9/10 (kotwica ≡ BASELINE_TRANSIT na 3 parach; walk 1000 x bez naruszeń).
- 21:40 T2: PASS 8.5/10; wykonawca dostaje iter 2: test legacy przez zamrożoną kopię `optimizer/tests/_nsga2_legacy.py` zamiast hashy (kruche na innych maszynach zespołu).
- 21:40 T4/T5: wykonawcy GOTOWE → recenzje. T4: backend musi używać `OTPClient(arrive_by=query_arrive_by(deadline))` (do README w T8).
- 21:40 Start T6 (T1–T3 DONE). Do T6: jawne dedupe_decimals w meta; filtr cv>0 przed build_slider + meta.feasible_front w slider; fallback pieszy także dla kotwicy w meta.anchor.
- 21:41 T2 iter 2: test legacy przez optimizer/tests/_nsga2_legacy.py (assert_array_equal), hashe usunięte, walidacja isfinite X0; 26 testów OK (sprawdzone przez evaluatora).
- 21:42 T5: PASS 9/10 (bez slidera bajt w bajt jak HEAD; rendery a–d obejrzane). Iter 2 szlif pod slajd. Uwaga dla T6: zawsze zapisywać slider.json razem z front.json (report auto-ładuje slider obok).
- 21:43 T4: PASS 8.5/10. Decyzje evaluatora (zgodne z CLAUDE.md „smog → nie promować roweru”): przy lock_reason trasa anchor (czysta komunikacja) zawsze dostępna jako fallback i domyślna. Iter 2: + plan_route_slider (jeden punkt wejścia, sam ustawia query_arrive_by), ROUTE_QUERY z geometrią/linią/przystankami dla UI (OTPClient(query=...) opcjonalnie — klucze cache GA bez zmian), licznik error + warnings.
- 21:45 T5 iter 2: 32 testy OK; render with.png obejrzany przez evaluatora — „lepiej” poza linią 1,0×, ząbki 0–6 czytelne, pasek suwaka w rogu, nadaje się na slajd.
- 21:46 DECYZJA UŻYTKOWNIKA: usunięto `optimizer/ALGORYTM_SKROT.md`; zamiast niego `optimizer/PLIKI.md` (co jest w którym pliku). T8 aktualizuje PLIKI.md zamiast skrótu.
- 21:49 T4 iter 2: fallback KMK przy smogu (s=0, domyślny), plan_route_slider, ROUTE_QUERY (geometria, linie), dropped.error + warnings, CLI exit 2 przy niedostępnym OTP; CLI domyślnie bez cache. Iter 3: anchor/walk wybierają min duration (fallback dawał 48 min zamiast 40.5).
- 21:49 T4 iter 3: anchor/walk = najszybsza trasa; demo smog: fallback KMK 40.5 min domyślny, rower 35–38 min (2 dostępne, 2 zablokowane).
- 21:49 DECYZJA UŻYTKOWNIKA: subagenci (orchestrator/worker/reviewer) na Sonnet, evaluator (główna sesja) na Opus — ustawione w .claude/agents/hy-*.md i SKILL.md. Dotyczy nowo uruchamianych subagentów; wznawiani (SendMessage) zachowują swój model.
- 21:51 T6: wykonawca GOTOWE. bike: 10 pkt, distinct 5 (ticki 2/3, 4/5 pokrywają się), kotwica dominowana (x1.007/58 kcal vs x0.80/107). walk: tylko 2 punkty — OTP nasyca się (walk.reluctance ≤1.6 daje to samo; wybór min generalizedCost z ≤3 tras). Hipoteza do rundy 2: brak dźwigni dla chodzenia w genomie walk (np. walk.boardCost, safetyFactor). Najpierw pomiar T7. Start T7 + recenzja T6.
- 21:52 T6: PASS 8.5/10 (deterministyczny przebieg odtworzony; meta.anchor ≡ K1; profiles ≡ ticki). Kandydaci do rundy 2: walk — dźwignia chodzenia (walk.boardCost / wybór trasy spośród zwróconych); bike — scalanie punktów bliższych niż ε (punkty 4–9 to ~ta sama trasa); meta.anchor + modes/preferences.
- 21:55 T7 (held-out, 6 par): bike monotonic 0.00 / distinct 3.67 / poz 4.33 / build 0.67–0.90 s; walk monotonic 1.00 / distinct 1.67 / poz 1.83 / build ≤0.22 s.
  - Wniosek 1: surowe ząbki bike nie są monotoniczne poza parami treningowymi (tick 0 = rower+KMK bywa wolniejszy od roweru bezpośredniego). UX chroni build_route_slider (sortuje po realnych metrykach i filtruje) — mini-front jest monotoniczny z konstrukcji. Pełny przebieg na 10 parach poprawiłby uogólnienie, ale użytkownik nie chce full → opisujemy uczciwie w DESIGN (T8).
  - Wniosek 2: walk bez dźwigni chodzenia (1.67 różnych tras) → T9.
  - Wniosek 3: bike ząbki pokrywają się (punkty frontu ~identyczne) → T10.
- 21:55 RUNDA 2: T9 + T10 równolegle, potem T11 (quick ×2 + slider_eval ×2), potem T8 i recenzja całościowa.
- 21:56 T10: merge_eps domyślnie (0.005×, 2 kcal), zachłannie od najszybszego, ostatnia grupa = punkt max kcal; meta.merged/merge_eps. quick_bike: 10→6 punktów, distinct nadal 5 (realna dziura w froncie). run_ga używa domyślnego scalania.
- 21:58 DESIGN.md zaktualizowany na prośbę użytkownika (15 sekcji, 357 linii; nowe §10–§15: tick, kotwica, suwak offline, online, wyniki, dalsze kroki). Do odświeżenia po T9/T11 w T8.
- 22:08 DECYZJA UŻYTKOWNIKA: ograniczenie cv = max(0, czas − 1.9·baseline) (trasa ≤ 190% najszybszej) zamiast baseline + max(15 min, 50%). Wprowadzone przez evaluatora: evaluate.MAX_TIME_RATIO=1.9, time_limit(), test_evaluate zaktualizowany, slider_select docstring, DESIGN §4. 253 testy OK. Wyniki w out/ (sprzed zmiany) do przeliczenia w T11.
- 22:08 T9: sonda (1200 kombinacji) — żaden parametr osobno nie daje ≥4 tras; dźwignią jest interakcja walk.boardCost × walk.reluctance (5–6 tras na 4/5 par), safetyFactor +1–2. Dodane geny walk-only: walk.boardCost (0–1800, kotwica 600) i walk.safetyFactor (0–1, kotwica 1.0); bike decode bez zmian (500 x). DIM 12 → stare front/slider do przeliczenia (T11).
- 22:13 T11 (po rundzie 2, held-out 6 par): bike front 12, distinct 7, eval distinct 5.33 (cel ✓), monotonia surowych ząbków 0.00 (✗, strukturalne — chroni build_route_slider), build 1.05/1.31 s ✓; walk front 6 → po ε 2, eval distinct 1.17 (✗), build ≤1.38 s ✓. Profile bike: fast ×0.70/69 kcal → active ×0.99/257 kcal. Wniosek evaluatora: dalsze rundy nic nie dadzą bez treningu na większej liczbie par (full — decyzja użytkownika: nie) albo nowego mechanizmu (via „wysiądź wcześniej” dla walk). Zamykamy rundę 2 → T8 + recenzja całościowa.
- 22:18 T8: GOTOWE — wszystkie komendy README exit 0, przykłady backendu uruchomione, 253 testy OK.
- 22:18 Pytanie użytkownika „czemu dla pieszych tylko 2 opcje?” — evaluator sprawdził na żywym OTP (LIST_ALL): kurdwanow_kazimierz → 5 wariantów KMK z dojściem 0.7–1.3 km + spacer 82 min (> limit 62.8); krowodrza_rynek → spacer 46.1 > limit 42.0. OTP (RAPTOR + pareto czas/koszt/przesiadki) NIE generuje tras „dalszy przystanek / wysiądź wcześniej” niezależnie od wag. Propozycja (czeka na decyzję): jawne generowanie kandydatów mieszanych przez `via` w slider_select (wysiądź k przystanków wcześniej, dojdź do dalszego przystanku).
- 22:18 Start recenzji całościowej rundy 2.
- 22:21 RECENZJA CAŁOŚCIOWA (runda 2): PASS 8/10. 253 testy OK; README wykonany dosłownie (quick bike/walk odtwarzają identyczny front, slider_select z/bez smog, slider_eval, przykład plan_route_slider — wyniki = README); dokumentacja zgodna z wynikami; blokada smog: fallback KMK domyślny na 10 parach; mini-front monotoniczny na 10 parach; walk bez BICYCLE; profile ≡ ticki; plan_route_slider ma wszystko dla UI; repo czyste (out/cache ignorowane).
- 22:21 KONIEC PĘTLI (2 rundy). Otwarte (nieblokujące): (1) smog na bardzo krótkiej trasie (rynek_agh) — anchor odrzucony, domyślna pozycja rowerowa (jest warning) → lepiej domyślnie spacer; (2) walk 1–2 pozycje → propozycja „via: wysiądź wcześniej / dalszy przystanek” czeka na decyzję użytkownika; (3) nowe pliki niezacommitowane, ALGORYTM_SKROT.md w stanie D.
