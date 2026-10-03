# hy-loop — naprawa domyślnej trasy przy smogu + PDF ze stanem projektu
Start: 2026-10-03 22:34 · Deadline: 2026-10-04 23:00 · Runda: 1
Poprzednie pętle: `.hy-loop/archive/state_ga_v1.md`, `.hy-loop/archive/state_slider_v1.md`.
Decyzje użytkownika (z poprzednich pętli): kod od razu (przed 23:00), bez trybu full, subagenci na Sonnet, limit 190%. Testy: `unittest` (pytest NIE jest zainstalowany).
Decyzje evaluatora: fallback przy smogu bez trasy KMK = najkrótszy spacer (tag `walk`); skrypt PDF w repo `docs/build_state_pdf.py`, PDF w korzeniu repo `STAN_PROJEKTU.pdf`, venv poza repo; nie commitujemy.

## Zadania
| ID | Zadanie | Zależy od | Pliki | Status | Iteracje | Ostatni werdykt |
|---|---|---|---|---|---|---|
| T1 | Smog: domyślna trasa (anchor → walk → bez roweru → warning) | — | optimizer/slider_select.py, optimizer/tests/test_slider_select.py | DONE | 1 | PASS 9/10 |
| T2 | Demo live smog + akapit w README | T1 | optimizer/README.md, optimizer/out/smog_demo.txt | DONE | 1 | demo + README zweryfikowane przez evaluatora |
| T4 | Fakty + skrypt PDF + STAN_PROJEKTU.pdf (połączone T3+T4 — ten sam plik) | T1,T2 | docs/build_state_pdf.py, STAN_PROJEKTU.pdf | DONE | 1 | PASS 9/10 (recenzja całościowa) + poprawki tekstu evaluatora |

## Kryteria akceptacji
### T1
- `python3 -m unittest optimizer.tests.test_slider_select -v` OK, w tym nowe testy:
  - (b) anchor odrzucony, jest `walk` → domyślna pozycja ma `walk` w sources, `fallback` True, `locked` False, s = 0;
  - (c) brak anchor i walk → domyślna bez BICYCLE (jeśli istnieje), warning;
  - same pozycje rowerowe → najmniej aktywna niezablokowana + warning.
- Regresja: anchor istnieje → bez zmian; bez locka → bez zmian; niezmiennik `sum(len(sources)) + sum(dropped) == len(requests)`.
- `python3 -m unittest discover -s optimizer/tests -t .` OK.

### T2
- OTP żyje (`curl` → 200/400).
- `slider_select --lock smog`:
  - dla `rynek_agh` → domyślna = spacer lub anchor, nigdy BICYCLE;
  - dla `nowa_huta_agh` → domyślna = anchor, pozycje rowerowe z s > 0.5 `locked`.
- Wynik w `optimizer/out/smog_demo.txt`; w README akapit „Smog: co jest domyślne”.

### T4
- `docs/build_state_pdf.py` ze słownikiem faktów (każda liczba ze źródłem w komentarzu).
- Generowanie: venv poza repo + reportlab → exit 0.
- `pdfinfo` → 4–7 stron A4.
- Strony wyrenderowane do PNG i obejrzane: polskie znaki, strzałki, marginesy.
- Status ✓/⚠/✗ albo kolorowe znaczniki (≥ 15).
- Design: spójna paleta, diagram architektury, numeracja stron.
- Treść zgodna ze stanem kodu i git (smog po naprawie; brakujące elementy bez zaokrąglania w górę).

## Dziennik
- 22:40 Plan orchestratora przyjęty z poprawkami evaluatora: pytest → unittest; T3 połączone z T4 (ten sam plik); kolejność T1 → T2 → T4. Start T1.
- 22:39 T1: wykonawca GOTOWE (a/b/c + testy, niezmiennik). Evaluator: etykieta CLI „[fallback KMK]” → „[fallback pieszo]” gdy źródło walk. Start recenzji T1 i T2 równolegle.
- 22:39 T4 uruchomione równolegle (zbieranie faktów + szkic PDF; smog_demo.txt i README czyta na końcu).
- 22:39 T2: GOTOWE — smog_demo.txt (4 wywołania, exit 0): rynek_agh → spacer domyślny [fallback pieszo]; nowa_huta_agh → komunikacja domyślna, rower s>0.5 zablokowany; README §„Smog / zła pogoda”. Uwaga: pozycja rowerowa s≤0.5 dalej wybieralna ręcznie przy smogu (zgodne z regułą, opisać w PDF).
- 22:42 T1: PASS 9/10. 20 przypadków (10 par × bike/walk) z smog: domyślna z rowerem 0/20 (anchor 18, spacer 2). Nieblokujące: niezmiennik liczników nie zachodzi dosłownie przy duplikatach (źródła scalone liczone też w dropped.duplicate) — dotyczy kodu sprzed zmiany; do poprawy docstring/definicji w przyszłości.
- 22:47 RECENZJA CAŁOŚCIOWA: PASS 9/10 — PDF 4 strony A4, liczby zgodne z testami (270), git, out/*, smog_demo; opis smogu zgodny z kodem; skrypt odtwarzalny (FACTS ze źródłami).
- 22:47 Evaluator: poprawki tekstu w PDF (wiersz Rynek→AGH: „brak trasy samą komunikacją”; literówki w wierszu walk — błąd .replace na całym zdaniu), PDF wygenerowany ponownie i obejrzany.
- 22:47 KONIEC PĘTLI (1 runda). Otwarte (nieblokujące): liczby git w FACTS wpisane na sztywno (po commicie nieaktualne); decyzja produktowa: czy przy smogu blokować też rower s ≤ 0.5; niezmiennik dropped przy duplikatach.
