# optimizer/ — co jest w którym pliku

Algorytm genetyczny (NSGA-II), który dobiera wagi zapytań OpenTripPlannera pod kompromis **czas ↔ ruch** i buduje z nich suwak dla użytkownika. Opis algorytmu: `DESIGN.md`. Uruchamianie: `README.md`.

## Dokumentacja
| Plik | Zawartość |
|---|---|
| `README.md` | jak uruchomić: testy, przebieg quick/full (oba warianty), suwak offline/online, `slider_eval`, raport; przykład użycia przez backend (`plan_route_slider`), opis pól wyniku, wyniki quick, ograniczenia |
| `DESIGN.md` | dokument projektowy: genom (12 genów), funkcje celu, ograniczenie 190%, NSGA-II, pary OD, wydajność, profile, tick [mam rower], kotwica, suwak offline i online, wyniki przed/po rundzie 2, dalsze kroki |
| `PLIKI.md` | ten plik — mapa plików |

## Kod (offline: liczenie frontu i suwaka)
| Plik | Zawartość |
|---|---|
| `genome.py` | **Genom**: 12 genów x ∈ [0,1] (`DIM`) → zmienne zapytania OTP (`modes`, `preferences`). 10 genów wspólnych + 2 **geny tylko dla `walk`** na końcu (`walk.boardCost` 0–1800 s, `walk.safetyFactor` 0–1; w `bike` nieaktywne i nieobecne w zapytaniu). Warianty `bike` / `walk` (tick [mam rower]), `active_mask`, `canonical` (ujednolica nieaktywne geny), kotwica K1 = domyślne wagi OTP (`encode_anchor`), stałe prędkości |
| `nsga2.py` | **Rdzeń NSGA-II** niezależny od OTP: dominacja z ograniczeniem (Deb), sortowanie niezdominowane, crowding distance, turniej, krzyżowanie SBX, mutacja wielomianowa, selekcja przeżycia z usuwaniem duplikatów celów, wstrzyknięcie populacji startowej (`X0`), hiperobjętość |
| `evaluate.py` | **Funkcja celu przez OTP**: klient OTP (wątki, retry, cache JSONL), czas bazowy najszybszej komunikacji dla par, metryki trasy (czas, aktywne kcal, kroki), ograniczenie `cv`: limit wydłużenia = **190% najszybszej** (`MAX_TIME_RATIO = 1.9`, `time_limit`), fallback pieszy, `evaluate_batch` dla GA |
| `run_ga.py` | **CLI przebiegu**: `--mode quick|full`, `--variant bike|walk`, `--ticks`, `--no-anchor`; liczy baseline, uruchamia NSGA-II, zapisuje `front.json`, `profiles.json`, `slider.json`, checkpoint i raport |
| `profiles.py` | **Obróbka frontu**: deduplikacja, filtr niezdominowanych, sortowanie, 3 profile (fast / balanced = kolano / active) |
| `slider.py` | **Suwak offline**: pozycje po długości łuku frontu (`arc_positions`), **scalanie bliskich punktów** (`merge_close`, `DEFAULT_MERGE_EPS = (0.005×, 2 kcal)`, `meta.merged` / `meta.merge_eps`), próbkowanie n ząbków (`sample_front`), budowa `slider.json`; CLI (`--n`, `--variant`, `--merge-eps-time`, `--merge-eps-kcal`) |
| `report.py` | **Raport**: wykres frontu Pareto (SVG, z ząbkami suwaka i profilami) + tabele Markdown (profile, suwak, punkty frontu); CLI |
| `od_pairs.json` | 10 par skąd–dokąd w Krakowie użytych do oceny (+ podzbiór `quick` z 4 parami) |
| `__init__.py` | znacznik pakietu |
| `.gitignore` | wyklucza z repo `cache/`, `out/` i `__pycache__/` |

## Kod (online: biblioteka dla backendu)
| Plik | Zawartość |
|---|---|
| `slider_select.py` | **Suwak dla jednej trasy użytkownika**: `plan_route_slider` (jeden punkt wejścia dla backendu), `tick_requests` (zapytania dla ząbków + kotwicy + spaceru, prędkości użytkownika), `ROUTE_QUERY` (zapytanie z geometrią, liniami i przystankami dla UI), `query_arrive_by`, `build_route_slider` (wybór tras zdążających na czas i mieszczących się w limicie 190%, scalanie identycznych, lokalny mini-front, blokada przy smogu/pogodzie, fallback KMK); CLI demo (`--pair`/`--from --to --deadline`, `--lock`, `--json`) |
| `slider_eval.py` | **Ocena suwaka na żywym OTP** dla par spoza treningu (`--pairs held-out\|all`): `monotonic_rate` surowych ząbków, `mean_distinct`, `mean_positions`, czas budowy `build_s_p50` / `build_s_max` (bez cache), cele jakościowe; zapis `slider_eval.json` (`--out`) |

## Testy (`tests/`, unittest)
| Plik | Co testuje |
|---|---|
| `test_genome.py` | dekodowanie genomu, warianty bike/walk, geny walk-only (`boardCost`, `safetyFactor`), `canonical`, kotwica, zgodność z OTP-schematem, regresja `bike` |
| `test_nsga2.py` | dominacja, sortowanie, crowding, operatory, ZDT1 (HV), deduplikacja, `X0`, zgodność z wersją v1 |
| `_nsga2_legacy.py` | zamrożona kopia NSGA-II z GA v1 — tylko referencja do testu kompatybilności |
| `test_evaluate.py` | metryki trasy, wybór trasy, `cv` i limit 190% (`time_limit`), fallback pieszy, cache i deduplikacja zapytań (bez OTP) |
| `test_profiles.py` | deduplikacja, filtr niezdominowanych, punkt kolana, monotonia profili |
| `test_run_ga.py` | cały przebieg z fałszywym evaluatorem: warianty, kotwica, `slider.json`, spójność profili z ząbkami |
| `test_slider.py` | długość łuku, scalanie ε (`merge_close`), próbkowanie ząbków, schemat `slider.json`, CLI |
| `test_slider_eval.py` | metryki `slider_eval` (monotonia, distinct, agregacja, cele) na syntetycznych odpowiedziach OTP — bez OTP |
| `test_slider_select.py` | zapytania dla ząbków, odrzucanie spóźnionych/za długich, scalanie, mini-front, blokada (bez OTP) |
| `test_report.py` | SVG (parsowanie, etykiety, ząbki, kolizje), tabele Markdown, odporność na złe dane |
| `test_integration_otp.py` | przebieg quick end-to-end na żywym OTP (pomijany, gdy OTP nie działa) |

## Dane testowe (`tests/fixtures/`)
| Plik | Zawartość |
|---|---|
| `front_sample.json` | syntetyczny front Pareto (12 punktów) w schemacie `front.json` |
| `slider_sample.json` | suwak 7 ząbków zgodny z `front_sample.json` |
| `otp_response.json` | prawdziwa odpowiedź OTP (`planConnection`) do testów metryk |
| `route_ticks_sample.json` | prawdziwe odpowiedzi OTP dla ząbków jednej trasy + przypadki syntetyczne (spóźnienie, za długa, duplikat) |

## Katalogi generowane (w `.gitignore`)
| Katalog | Zawartość |
|---|---|
| `cache/` | cache odpowiedzi OTP (JSONL) — przyspiesza ponowne przebiegi |
| `out/` | wyniki przebiegów, np. `out/quick_bike/`, `out/quick_walk/`: `front.json`, `profiles.json`, `slider.json`, `slider_eval.json` (wynik `slider_eval`), `front.svg`, `front.md`, `checkpoint.json` |
