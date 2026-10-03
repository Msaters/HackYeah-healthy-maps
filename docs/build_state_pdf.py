#!/usr/bin/env python3
"""Builds STAN_PROJEKTU.pdf (project status for the team and mentors).

Run from the repo root with a venv that has reportlab (kept outside the repo):
    <venv>/bin/python docs/build_state_pdf.py
Every number in the PDF comes from the FACTS dict below; the comment next to it names the source file.
"""
from datetime import datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Group, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "STAN_PROJEKTU.pdf"

# ---------------------------------------------------------------- facts (each with its source)
FACTS = {
    "tests": 270,            # `python3 -m unittest discover -s optimizer/tests -t .` -> Ran 270 tests, OK (3.10.2026 22:4x, OTP up)
    "tests_slider_select": 87,  # .hy-loop/state.md, T1 (wykonawca: 87 testow slider_select)
    "commits": 2,            # `git log --oneline` -> 08141b0, f4d6d4d
    "git_changed": 14,       # `git status --short`: 14 x " M"
    "git_deleted": 1,        # `git status --short`: 1 x "D " (optimizer/ALGORYTM_SKROT.md)
    "git_untracked": 12,     # `git status --short`: 12 x "??" (before adding this PDF and its script)
    "graph_build_min": 2,    # docs/OTP.md s.11: build ~2 min
    "stops": 3336,           # docs/OTP.md s.11
    "graph_mb": 182,         # docs/OTP.md s.11
    "bike_parkings": 4876,   # docs/OTP.md s.11 (staticBikeParkAndRide import)
    "genes": 12,             # optimizer/README.md, DESIGN.md s.2 (10 shared + 2 walk-only)
    "limit_pct": 190,        # optimizer/DESIGN.md s.4, evaluate.MAX_TIME_RATIO = 1.9
    "ticks": 7,              # optimizer/DESIGN.md s.12
    "pairs_all": 10,         # optimizer/DESIGN.md s.7
    "pairs_quick": 4,        # optimizer/DESIGN.md s.7
    "pairs_heldout": 6,      # optimizer/out/quick_*/slider_eval.json summary.n_pairs
    "pop": 12, "gens": 4,    # optimizer/out/quick_bike/front.json meta
    "requests_online": 9,    # optimizer/DESIGN.md s.13 (7 ticks + anchor + walk)
    "merge_eps": "0,005 x czasu, 2 kcal",  # optimizer/DESIGN.md s.12
    "bike": {  # optimizer/out/quick_bike/{front,slider,profiles,slider_eval}.json
        "front": 12, "distinct": 7, "merged": 1, "queries": 243, "elapsed_s": 25.3,
        "fast": (0.703, 69, 23.9), "balanced": (0.881, 249, 30.5), "active": (0.988, 257, 33.0),
        "mono": 0.00, "mean_distinct": 5.33, "mean_pos": 4.50, "p50": 1.05, "max": 1.31,
    },
    "walk": {  # optimizer/out/quick_walk/{front,slider,profiles,slider_eval}.json
        "front": 6, "distinct": 2, "merged": 4, "queries": 248, "elapsed_s": 18.0,
        "fast": (1.005, 58, 1448), "balanced": (1.026, 76, 1919), "active": (1.029, 76, 1923),
        "mono": 1.00, "mean_distinct": 1.17, "mean_pos": 1.67, "p50": 0.24, "max": 1.38,
    },
    "targets": {"mono": 0.8, "distinct": 4, "build_s": 2},  # optimizer/DESIGN.md s.14
    "smog_rynek": {  # optimizer/out/smog_demo.txt, 1st block (bike slider, --lock smog, rynek_agh)
        "baseline": 17.4, "default": "spacer (WALK), 17,4 min, ~71 kcal, 1819 kroków",
        "bike_s": 0.333, "bike_min": 7.4, "locked_min": 13.2, "locked_s": 1.0,
    },
    "smog_nh": {  # optimizer/out/smog_demo.txt, 2nd block (nowa_huta_agh, --lock smog) and 4th block (no lock)
        "default": "KMK 40,5 min (tramwaj+autobus), ~34 kcal", "free_default": "rower 46,4 min, ~379 kcal",
        "locked": "46,4 i 49,7 min (s 0,87 i 1,00)", "open_bike": "34,8 i 36,8 min (s 0,20 i 0,29)",
    },
}
STAMP = datetime.now().strftime("%d.%m.%Y, %H:%M")

# ---------------------------------------------------------------- palette & fonts
GREEN, BLUE, ORANGE = colors.HexColor("#0F7B6C"), colors.HexColor("#2F5DA8"), colors.HexColor("#C2410C")
RED, GREY, DARK = colors.HexColor("#B42318"), colors.HexColor("#667085"), colors.HexColor("#1D2939")
LGREEN, LBLUE, LORANGE, LRED, LGREY = (colors.HexColor(c) for c in
                                       ("#E3F4F0", "#E6EDF8", "#FDEBDD", "#FBE4E1", "#F2F4F7"))
FD = "/usr/share/fonts/truetype/noto/"
pdfmetrics.registerFont(TTFont("Noto", FD + "NotoSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Noto-B", FD + "NotoSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJ", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFontFamily("Noto", normal="Noto", bold="Noto-B", italic="Noto", boldItalic="Noto-B")

S = {
    "title": ParagraphStyle("title", fontName="Noto-B", fontSize=24, leading=28, textColor=GREEN),
    "tag": ParagraphStyle("tag", fontName="Noto", fontSize=11.5, leading=15, textColor=BLUE),
    "h1": ParagraphStyle("h1", fontName="Noto-B", fontSize=13.5, leading=17, textColor=GREEN, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Noto", fontSize=9.2, leading=12.6, textColor=DARK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Noto", fontSize=7.8, leading=10, textColor=GREY),
    "cell": ParagraphStyle("cell", fontName="Noto", fontSize=8.2, leading=10.4, textColor=DARK),
    "cellb": ParagraphStyle("cellb", fontName="Noto-B", fontSize=8.2, leading=10.4, textColor=DARK),
    "head": ParagraphStyle("head", fontName="Noto-B", fontSize=8.2, leading=10.4, textColor=colors.white),
    "stat": ParagraphStyle("stat", fontName="Noto", fontSize=8.2, leading=10.4, alignment=1),
}


def sym(kind):
    """Coloured status symbol: ok / warn / bad."""
    ch, col = {"ok": ("✓", GREEN), "warn": ("⚠", ORANGE), "bad": ("✗", RED)}[kind]
    return Paragraph(f'<font face="DJ" size="11" color="{col.hexval()}"><b>{ch}</b></font>', S["stat"])


def P(text, style="cell"):
    return Paragraph(text, S[style])


ARROW = '<font face="DJ">→</font>'
GE = "<font face='DJ'>≥</font>"
CHK, WRN, BAD = ('<font face="DJ" color="#0F7B6C">✓</font>', '<font face="DJ" color="#C2410C">⚠</font>',
                 '<font face="DJ" color="#B42318">✗</font>')
BG = {"ok": LGREEN, "warn": LORANGE, "bad": LRED}


def status_table(rows, widths, head, extra=()):
    """rows: (status, [cells...]); status goes to column 1."""
    data = [[P(h, "head") for h in head]]
    style = [("BACKGROUND", (0, 0), (-1, 0), GREEN), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D0D5DD")),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    for i, (st, cells) in enumerate(rows, start=1):
        first = [P(cells[0], "cellb")]
        data.append(first + [sym(st)] + [P(c) for c in cells[1:]])
        style.append(("BACKGROUND", (1, i), (1, i), BG[st]))
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(style + list(extra)))
    return t


# ---------------------------------------------------------------- architecture diagram
def box(g, x, y, w, h, title, sub, ready):
    fill, line = (LGREEN, GREEN) if ready else (colors.white, ORANGE)
    r = Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=line, strokeWidth=1.3)
    if not ready:
        r.strokeDashArray = [4, 3]
    g.add(r)
    lines = sub.split("\n")
    top = y + h / 2 + (len(lines) * 8.5 + 11) / 2 - 8
    g.add(String(x + w / 2, top, title, fontName="Noto-B", fontSize=7.8, fillColor=DARK, textAnchor="middle"))
    for i, ln in enumerate(lines):
        g.add(String(x + w / 2, top - 11 - 8.5 * i, ln, fontName="Noto", fontSize=6.6, fillColor=GREY, textAnchor="middle"))


def arrow(g, x1, y1, x2, y2, ready, label=None, lx=0, ly=0):
    col = GREEN if ready else ORANGE
    ln = Line(x1, y1, x2, y2, strokeColor=col, strokeWidth=1.3)
    if not ready:
        ln.strokeDashArray = [4, 3]
    g.add(ln)
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    d = 5
    pts = [x2, y2, x2 - d * math.cos(a - 0.4), y2 - d * math.sin(a - 0.4), x2 - d * math.cos(a + 0.4), y2 - d * math.sin(a + 0.4)]
    g.add(Polygon(pts, fillColor=col, strokeColor=col, strokeWidth=0.5))
    if label:
        g.add(String(lx, ly, label, fontName="Noto", fontSize=6.3, fillColor=col, textAnchor="middle"))


def architecture():
    d = Drawing(515, 320)
    g = Group()
    g.translate(0, 26)
    d.add(g)
    # sources
    src = [("OSM Małopolska", "krakow.osm.pbf", 250, True),
           ("GTFS KMK (A+T, ZTP)", "+ patch bikes_allowed", 208, True),
           ("GTFS-RT (ZTP)", "TripUpdates, Positions, Alerts", 166, True),
           ("DEM (4 kafle .tif)", "wysokości dla roweru", 124, True),
           ("GIOŚ, Open-Meteo", "smog, pogoda (planowane)", 80, False),
           ("Warstwy ZTP GIS, GBFS", "Park-e-Bike (planowane)", 36, False)]
    for t, s, y, r in src:
        box(g, 0, y, 118, 36, t, s, r)
    # OTP
    box(g, 152, 124, 92, 162, "OTP 2.10 (Docker)", "graf Krakowa\n(OSM + GTFS + DEM)\nGraphQL planConnection\nlocalhost:8080\ntryby: bike&ride,\nrower w tramwaju", True)
    for t, s, y, r in src[:4]:
        arrow(g, 118, y + 18, 152, y + 18, True)
    # optimizer
    box(g, 280, 218, 118, 68, "optimizer offline", "NSGA-II (12 genów)\n" + ARROW.replace('<font face="DJ">', '').replace('</font>', '') + " front.json\n" + "→ slider.json", True)
    box(g, 280, 112, 118, 70, "slider_select online", "plan_route_slider:\n9 zapytań do OTP, filtry,\nmini-front, blokada smogu", True)
    arrow(g, 244, 252, 280, 252, True, "zapytania", 262, 256)
    arrow(g, 280, 147, 244, 147, True)
    arrow(g, 339, 218, 339, 182, True, "slider.json", 363, 197)
    # backend / frontend
    box(g, 430, 40, 85, 100, "Backend (FastAPI)", "planowany\nproxy, cache ZTP,\nGBFS, GIOŚ/Open-\nMeteo → lock_reason", False)
    box(g, 430, 196, 85, 90, "Frontend", "planowany\nReact + MapLibre\nmapa, suwak,\n3 karty tras", False)
    arrow(g, 398, 138, 430, 112, False)
    arrow(g, 472, 140, 472, 196, False)
    arrow(g, 118, 98, 430, 84, False)
    arrow(g, 118, 54, 430, 62, False)
    # legend
    g.add(Rect(0, -22, 14, 9, rx=2, ry=2, fillColor=LGREEN, strokeColor=GREEN, strokeWidth=1.3))
    g.add(String(19, -20, "zrobione (działa, przetestowane)", fontName="Noto", fontSize=7, fillColor=DARK))
    r = Rect(185, -22, 14, 9, rx=2, ry=2, fillColor=colors.white, strokeColor=ORANGE, strokeWidth=1.3)
    r.strokeDashArray = [3, 2]
    g.add(r)
    g.add(String(204, -20, "planowane (brak w kodzie)", fontName="Noto", fontSize=7, fillColor=DARK))
    g.add(Line(340, -17.5, 360, -17.5, strokeColor=GREEN, strokeWidth=1.3))
    g.add(String(365, -20, "przepływ działa", fontName="Noto", fontSize=7, fillColor=DARK))
    l2 = Line(430, -17.5, 450, -17.5, strokeColor=ORANGE, strokeWidth=1.3)
    l2.strokeDashArray = [4, 3]
    g.add(l2)
    g.add(String(455, -20, "planowany", fontName="Noto", fontSize=7, fillColor=DARK))
    return d


# ---------------------------------------------------------------- page chrome
def chrome(c, doc):
    w, h = A4
    c.saveState()
    c.setFillColor(GREEN)
    c.rect(0, h - 8, w, 8, stroke=0, fill=1)
    c.setFont("Noto", 7.5)
    c.setFillColor(GREY)
    c.drawString(40, 22, "Aktywny Kraków — stan projektu · HackYeah 2026, Smart City")
    c.drawRightString(w - 40, 22, f"strona {doc.page}")
    c.setStrokeColor(colors.HexColor("#D0D5DD"))
    c.line(40, 32, w - 40, 32)
    c.restoreState()


def stat_strip(items):
    cells = []
    for big, small, col in items:
        cells.append([Paragraph(f'<font name="Noto-B" size="15" color="{col.hexval()}">{big}</font>', S["stat"]),
                      Paragraph(small, S["small"])])
    t = Table([[c[0] for c in cells], [c[1] for c in cells]], colWidths=[515 / len(items)] * len(items))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LGREY), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.white),
                           ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 5)]))
    return t


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=40, rightMargin=40, topMargin=34, bottomMargin=42,
                          title="Aktywny Kraków — stan projektu", author="Zespół HackYeah 2026")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(40, 42, 515, A4[1] - 76, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=chrome)])
    f = []
    B, W = FACTS["bike"], FACTS["walk"]

    # 1. title
    f += [Spacer(1, 6), Paragraph("Aktywny Kraków — stan projektu", S["title"]),
          Paragraph(f"Stan na {STAMP} · zespół 4 osób, HackYeah 2026 (Smart City, Kraków)", S["small"]), Spacer(1, 6),
          Paragraph("„Dojedziesz na czas, a po drodze zrobisz swój dzienny trening.”", S["tag"]), Spacer(1, 6),
          Paragraph("<b>Cel produktu.</b> Aplikacja w stylu Google Maps dla Krakowa, która wlicza rower do planowania tras: "
                    "rower + KMK (bike&amp;ride, rower w tramwaju), preferowanie infrastruktury rowerowej i porównanie wariantów. "
                    "Użytkownik podaje cel i godzinę przyjazdu, a <b>suwak „czas "
                    '<font face="DJ">↔</font> ruch”</b> przesuwa wybór od najszybszej trasy komunikacją do trasy z największą liczbą '
                    "spalonych kcal, która wciąż zdąży przed terminem (limit: trasa najwyżej "
                    f"{FACTS['limit_pct']}% najszybszej). Bezpieczniki z danych miejskich (smog, pogoda) mają blokować promowanie roweru "
                    "w złych warunkach. Dane o zdrowiu zostają tylko na urządzeniu.", S["body"]), Spacer(1, 6),
          Paragraph("<b>Uczciwie:</b> gotowy jest silnik routingu i optymalizator wag (biblioteka w Pythonie, CLI, "
                    f"{FACTS['tests']} testów). <b>Nie ma jeszcze backendu, frontendu ani integracji z GIOŚ/Open-Meteo</b> — "
                    "demo end-to-end dla jury dziś nie istnieje.", S["body"]), Spacer(1, 8),
          stat_strip([(str(FACTS["tests"]), "testów unittest (OK)", GREEN), (str(FACTS["commits"]), "commity w repo", BLUE),
                      (f"{FACTS['git_changed'] + FACTS['git_deleted'] + FACTS['git_untracked']}", "wpisów w git status (poza commitem)", ORANGE),
                      (f"{FACTS['graph_build_min']} min", "budowa grafu OTP", BLUE)]),
          Paragraph("Architektura i przepływ danych", S["h1"]), architecture(), Spacer(1, 6),
          Paragraph("Jak to płynie", S["h1"]),
          Paragraph("<b>1. Offline (raz):</b> NSGA-II odpytuje OTP różnymi wagami zapytania i buduje front Pareto czas ↔ kcal; z frontu powstaje suwak z 7 ząbkami (osobno dla „mam rower” i „bez roweru”).".replace("↔", '<font face="DJ">↔</font>'), S["body"]),
          Paragraph("<b>2. Online (na zapytanie):</b> <i>plan_route_slider</i> wysyła 9 zapytań do OTP z godziną przyjazdu, odrzuca trasy, które nie zdążą lub przekraczają limit, scala duplikaty i zwraca pozycje suwaka z geometrią do narysowania.", S["body"]),
          Paragraph("<b>3. Bezpieczniki:</b> przy smogu lub złej pogodzie wywołujący podaje <i>lock_reason</i> — pozycje z dużą ilością ruchu są blokowane, a domyślna jest trasa bez roweru. Dziś nikt tego nie robi automatycznie (brak backendu i integracji).", S["body"]),
          Paragraph("<b>4. Dalej (planowane):</b> backend wystawia to po HTTP i dokłada dane miejskie, frontend rysuje mapę, suwak i 3 karty tras.", S["body"])]

    # 3. table of what exists
    f += [PageBreak(), Paragraph("Co jest i jak to działa", S["h1"])]
    ok, wr, bd = "ok", "warn", "bad"
    rows = [
        (ok, ["OTP 2.10 + graf Krakowa", f"Docker, OSM + GTFS A+T + 4 kafle DEM; graf ~{FACTS['graph_build_min']} min, {FACTS['stops']} przystanków, {FACTS['graph_mb']} MB; API GraphQL <i>planConnection</i> (docs/OTP.md §11, OTP_QUICKSTART)."]),
        (ok, ["GTFS-RT", "7 updaterów w router-config.json (TripUpdates, Positions, Alerts × A/T, plus GBFS). Trasy mają <i>realTime</i>. Uwaga: w danych ZTP są błędy (NEGATIVE_DWELL_TIME) — ignorowane."]),
        (ok, ["Rower w tramwaju (patch <i>bikes_allowed</i>)", "ZTP nie publikuje kolumny, więc <i>otp/patch_gtfs_bikes.py</i> (z download.sh) dopisuje bikes_allowed=1 do wszystkich kursów. Założenie z regulaminu KMK, nie z danych."]),
        (ok, ["Bike&amp;ride", f"<i>staticBikeParkAndRide: true</i> importuje {FACTS['bike_parkings']} stojaków z OSM; tryb BICYCLE_PARKING działa. Stojaki ZTP (GIS) nie są jeszcze użyte."]),
        (ok, ["NSGA-II (offline)", f"Genom {FACTS['genes']} genów <font face='DJ'>→</font> zmienne <i>planConnection</i>; cele f1 = czas względem najszybszej (min), f2 = aktywne kcal (max); limit {FACTS['limit_pct']}% najszybszej jako constraint-domination (Deb); kotwica = domyślne wagi OTP w populacji startowej; dedupe w przestrzeni celów."]),
        (ok, ["Warianty bike / walk", "Przełącznik „mam rower” = osobny front i suwak (out/quick_bike, out/quick_walk). Wariant walk nie używa roweru; 2 dodatkowe geny (boardCost, safetyFactor)."]),
        (ok, ["Suwak offline", f"Długość łuku frontu zamiast sumy ważonej (nie gubi wklęsłych fragmentów); {FACTS['ticks']} ząbków; scalanie bliskich punktów ε ({FACTS['merge_eps']}). Wyjście: slider.json."]),
        (ok, ["slider_select (online)", f"<i>plan_route_slider</i>: {FACTS['requests_online']} zapytań (7 ząbków + czysta komunikacja + spacer), filtr „zdąży” (bufor 3 min) i limit {FACTS['limit_pct']}%, scalanie duplikatów, mini-front, <i>ROUTE_QUERY</i> z geometrią dla UI. Wynik monotoniczny z konstrukcji."]),
        (ok, ["Blokada przy smogu (po naprawie)", "<i>lock_reason</i>: domyślna = czysta komunikacja <font face='DJ'>→</font> najkrótszy spacer <font face='DJ'>→</font> trasa bez roweru + ostrzeżenie. Pozycje s &gt; 0,5 zablokowane. Przykład poniżej."]),
        (ok, ["Raport SVG / MD", "report.py: wykres frontu z ząbkami i profilami (front.svg) oraz tabele (front.md) — gotowe na slajd."]),
        (ok, ["Testy", f"{FACTS['tests']} testów unittest, OK ({FACTS['tests_slider_select']} dla slider_select); test integracyjny uruchamia się tylko z żywym OTP. Pokrycie logiki, nie UI (UI nie ma)."]),
        (wr, ["Dokumentacja", "docs/OTP.md, OTP_QUICKSTART, optimizer/{README,DESIGN,PLIKI}.md. Uwaga: część liczb w dokumentach pochodzi z jednego przebiegu quick — to nie wyniki docelowe."]),
    ]
    f.append(status_table(rows, [118, 28, 369], ["Komponent", "", "W skrócie jak zrealizowane"]))

    smog = [
        P("<b>Przykład blokady smogu</b> (<i>optimizer/out/smog_demo.txt</i>, OTP żywy, termin pn 8:30, wariant bike):", "body"),
        Spacer(1, 3),
        status_table([
            (ok, ["Rynek <font face='DJ'>→</font> AGH (krótka)", f"Domyślnie: <b>{FACTS['smog_rynek']['default']}</b> — brak trasy samą komunikacją (OTP: spacer lepszy). Rower s = {str(FACTS['smog_rynek']['bike_s']).replace('.', ',')} ({FACTS['smog_rynek']['bike_min']} min) pozostaje <b>niezablokowany</b> (s <font face='DJ'>≤</font> 0,5); zablokowany jest rower + KMK ({FACTS['smog_rynek']['locked_min']} min, s = 1,0)."]),
            (ok, ["Nowa Huta <font face='DJ'>→</font> AGH (długa)", f"Domyślnie: <b>{FACTS['smog_nh']['default']}</b>; bez blokady domyślny byłby {FACTS['smog_nh']['free_default']}. Zablokowane: {FACTS['smog_nh']['locked']}; dostępne rower + tramwaj {FACTS['smog_nh']['open_bike']}."]),
        ], [118, 28, 369], ["Trasa", "", "Wynik"]),
        P("Uwaga: blokada obejmuje tylko s &gt; 0,5 — szybkie pozycje rowerowe (s <font face='DJ'>≤</font> 0,5) zostają dostępne. Czy tak ma być przy złym powietrzu, to decyzja produktowa do podjęcia (CLAUDE.md: „nie promować roweru”; domyślna pozycja jest bezpieczna).", "small"),
    ]
    f += [Spacer(1, 6), KeepTogether(smog)]

    # 4. results
    def row(label, a, b, good_a, good_b, target):
        mk = lambda ok_, v: f'{v} {CHK if ok_ else BAD}'
        return [P(label, "cellb"), P(mk(good_a, a)), P(mk(good_b, b)), P(target)]

    t = FACTS["targets"]
    f += [PageBreak(), Paragraph("Wyniki pomiarów (przebieg quick, seed 1)", S["h1"]),
          P(f"To smoke test, nie wynik docelowy: pop {FACTS['pop']} × {FACTS['gens']} pokolenia, {FACTS['pairs_quick']} pary treningowe z {FACTS['pairs_all']}, "
            f"{B['queries']} / {W['queries']} zapytań do OTP, {B['elapsed_s']} s / {W['elapsed_s']} s na zimno. Źródło: <i>optimizer/out/quick_{{bike,walk}}/</i>. "
            "Tryb full nie był uruchamiany (decyzja zespołu).", "body"), Spacer(1, 5)]
    hdr = [P(h, "head") for h in ("Front i profile", "bike (z rowerem)", "walk (bez roweru)")]
    d1 = [hdr,
          [P("punkty frontu / różne ząbki (distinct) / scalone", "cellb"), P(f"{B['front']} / {B['distinct']} / {B['merged']}"), P(f"{W['front']} / {W['distinct']} / {W['merged']}")],
          [P("profil <b>fast</b>: czas × baseline, kcal", "cell"), P(f"×{B['fast'][0]:.2f} · ~{B['fast'][1]} kcal · {B['fast'][2]} min".replace(".", ",")), P(f"×{W['fast'][0]:.3f} · ~{W['fast'][1]} kcal · {W['fast'][2]} kroków".replace(".", ","))],
          [P("profil <b>balanced</b> (kolano frontu)", "cell"), P(f"×{B['balanced'][0]:.2f} · ~{B['balanced'][1]} kcal · {B['balanced'][2]} min".replace(".", ",")), P(f"×{W['balanced'][0]:.3f} · ~{W['balanced'][1]} kcal · {W['balanced'][2]} kroków".replace(".", ","))],
          [P("profil <b>active</b>", "cell"), P(f"×{B['active'][0]:.2f} · ~{B['active'][1]} kcal · {B['active'][2]} min".replace(".", ",")), P(f"×{W['active'][0]:.3f} · ~{W['active'][1]} kcal · {W['active'][2]} kroków".replace(".", ","))]]
    tb = Table(d1, colWidths=[190, 165, 160])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D0D5DD")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    f += [tb, P("Wartość „× 0,70” = o 30% szybciej niż najszybsza trasa komunikacją (rower skraca dojścia). Profile bike mają 0 kroków — rower ich nie daje, kroki obsługuje wariant walk.", "small"), Spacer(1, 8),
          Paragraph(f"Ocena suwaka na {FACTS['pairs_heldout']} parach spoza treningu (slider_eval, bez cache)", S["h1"])]
    hdr = [P(h, "head") for h in ("Miara", "bike", "walk", "Cel")]
    d2 = [hdr,
          row("monotonia surowych ząbków", f"{B['mono']:.2f}".replace(".", ","), f"{W['mono']:.2f}".replace(".", ","), B["mono"] >= t["mono"], W["mono"] >= t["mono"], f"{GE} {t['mono']}".replace(".", ",")),
          row("różne trasy z 7 ząbków (średnio)", f"{B['mean_distinct']:.2f}".replace(".", ","), f"{W['mean_distinct']:.2f}".replace(".", ","), B["mean_distinct"] >= t["distinct"], W["mean_distinct"] >= t["distinct"], f"{GE} {t['distinct']}"),
          [P("pozycje suwaka po buildzie (średnio)", "cellb"), P(f"{B['mean_pos']:.2f}".replace(".", ",")), P(f"{W['mean_pos']:.2f}".replace(".", ",")), P("bez celu")],
          row("czas budowy max [s] (p50)", f"{B['max']:.2f} ({B['p50']:.2f})".replace(".", ","), f"{W['max']:.2f} ({W['p50']:.2f})".replace(".", ","), B["max"] < t["build_s"], W["max"] < t["build_s"], f"&lt; {t['build_s']} s")]
    tb2 = Table(d2, colWidths=[190, 115, 115, 95])
    tb2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), BLUE), ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D0D5DD")),
                             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    f += [tb2, Spacer(1, 4),
          P("<b>Jak to czytać:</b> monotonia bike = 0,00 dotyczy <i>surowych</i> ząbków poza parami treningowymi (ząbek 0, rower + KMK, bywa wolniejszy od roweru bezpośrednio). "
            "Użytkownik jest chroniony, bo <i>build_route_slider</i> sortuje po realnych metrykach i usuwa trasy zdominowane — ale to znaczy, że wagi nie uogólniają się dobrze i front na 4 parach nie jest dowodem jakości. "
            "Wariant walk ma ~1–2 pozycje, bo OTP nie generuje tras „wysiądź wcześniej” (wagi nie mają z czego wybierać).", "body")]

    # 5. missing
    f += [Paragraph("Co nie działa / czego brakuje", S["h1"])]
    miss = [
        (bd, ["Backend (FastAPI)", "Nie istnieje. Nic nie serwuje <i>plan_route_slider</i> po HTTP, nie cache'uje warstw ZTP."]),
        (bd, ["Frontend (React + MapLibre)", "Nie istnieje: brak mapy, wyszukiwarki (Photon), suwaka i profilu (waga, wzrost w localStorage). To największa luka względem kryteriów Design i Usability (po 20%)."]),
        (bd, ["GIOŚ i Open-Meteo w kodzie", "Brak integracji. Blokadę dostaje <i>lock_reason</i> od wywołującego (tekst „smog”/„weather”); nikt go dziś nie ustawia z danych."]),
        (bd, ["Warstwy ZTP na mapie", "Drogi rowerowe, stojaki, P+R, heatmapa metaCCAZE — nie pobrane do data/, nie użyte w wagach ani na mapie."]),
        (bd, ["Feed GBFS Park-e-Bike", "router-config.json wskazuje updater na host.docker.internal:8000, ale feedu nikt nie serwuje (brak Park-e-Bike, godzin 5–20, poligonu)."]),
        (bd, ["3 karty + cel dzienny", "Karty „Najszybsza / Cel kaloryczny / Cel kroków” z deduplikacją nie są zaimplementowane; jest suwak z pozycjami. Cel dzienny (kcal/kroki) nie istnieje. Kroki dla trasy z rowerem to zawsze 0."]),
        (bd, ["Slajdy i zgłoszenie", "Brak PDF z prezentacją (max 10 slajdów), opisu projektu i scenariuszy demo na HackTribe."]),
        (wr, ["walk: 1–2 pozycje suwaka", f"Średnio {W['mean_pos']:.2f}".replace(".", ",") + " pozycji na parach spoza treningu. Rozwiązanie („wysiądź wcześniej” przez punkt pośredni, K5–K7) jest opisane w DESIGN §15, ale niezrobione."]),
        (wr, ["Monotonia surowych ząbków bike = 0,00", "Na parach spoza treningu; ukryta przez budowę mini-frontu online, ale niewyleczona."]),
        (wr, [f"Trening na {FACTS['pairs_quick']} parach", f"Tryb full ({FACTS['pairs_all']} par) nie był uruchamiany; jeden zestaw ząbków dla wszystkich tras, pora dnia pn 8:30, kcal roweru bez korekty za podjazdy; brak porównania z random search."]),
        (wr, ["Założenia na danych", "Rower w tramwaju = bikes_allowed=1 dla wszystkich kursów (założenie). Kalorie to szacunek MET."]),
        (wr, ["Brak commita", f"Repo ma {FACTS['commits']} commity; praca optymalizatora nie jest scommitowana: {FACTS['git_changed']} zmienionych, {FACTS['git_deleted']} usunięty i {FACTS['git_untracked']} nieśledzonych wpisów w <i>git status</i> (bez tego PDF). Katalog optimizer/out/ jest w .gitignore, więc wyniki quick nie trafią do repo."]),
    ]
    f.append(status_table(miss, [128, 28, 359], ["Element", "", "Stan"]))

    # 6 + 7
    f += [KeepTogether([Paragraph("Uwaga regulaminowa", S["h1"]),
          P("Start pracy <b>nie wcześniej niż 3.10 23:00</b>, oddanie <b>najpóźniej 4.10 23:00</b> na HackTribe. Zgłoszenie = tytuł, nazwa zespołu, lista członków, opis oraz "
            "<b>osobny PDF z prezentacją (max 10 slajdów)</b> — ten dokument jest wewnętrzny i nim nie jest. Ocena: Idea 30%, Relation to Category 20%, Usability 20%, Design 20%, Completeness 10%. "
            "<b>Zwróć uwagę:</b> w repo są commity z 3.10 17:32 i 19:48, a przebiegi i pętla agentów z 22:09–22:40, czyli przed 23:00. "
            "Zespół powinien ocenić, czy to dopuszczalne prace przygotowawcze (OTP, dane, dokumentacja), i uzgodnić to z organizatorem.", "body")])]

    steps = [
        ("1", "Backend FastAPI", "endpoint trasy <font face='DJ'>→</font> <i>plan_route_slider</i> + <i>lock_reason</i>; cache GeoJSON ZTP do data/; to odblokowuje frontend.", BLUE),
        ("2", "Frontend (mobile-first)", "mapa MapLibre, wyszukiwarka Photon, godzina przyjazdu, suwak, profil w localStorage — demo end-to-end.", BLUE),
        ("3", "Smog i pogoda", "GIOŚ (najbliższa stacja) + Open-Meteo w godzinie przejazdu <font face='DJ'>→</font> <i>lock_reason</i>; decyzja, czy blokować też s <font face='DJ'>≤</font> 0,5.", GREEN),
        ("4", "3 karty tras + dedupe", "karty z pozycji suwaka i zapytań K5–K7; cel dzienny jako nice-to-have.", GREEN),
        ("5", "Warstwy ZTP i feed GBFS", "drogi rowerowe, stojaki, P+R na mapie; własny feed Park-e-Bike (dostępność symulowana i opisana jawnie).", GREEN),
        ("6", "Slajdy i opis zgłoszenia", "max 10 slajdów (zrzuty, repo, demo), scenariusze: Nowa Huta <font face='DJ'>→</font> AGH, Czerwone Maki <font face='DJ'>→</font> Rynek; pitch o prywatności.", ORANGE),
        ("7", "Jeśli zostanie czas", "„wysiądź wcześniej” dla walk, tryb full / więcej par, korekta kcal za podjazdy, commit repo.", GREY),
    ]
    rows = [[Paragraph(f'<font name="Noto-B" size="12" color="#FFFFFF">{n}</font>', S["stat"]), P(f"<b>{t}</b><br/>{d}")] for n, t, d, c in steps]
    nt = Table(rows, colWidths=[26, 489])
    nt.setStyle(TableStyle([("BACKGROUND", (0, i), (0, i), steps[i][3]) for i in range(len(steps))] +
                           [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 2, colors.white),
                            ("BACKGROUND", (1, 0), (1, -1), LGREY), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    f += [KeepTogether([Paragraph("Proponowane następne kroki (kolejność)", S["h1"]), nt])]
    doc.build(f)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
