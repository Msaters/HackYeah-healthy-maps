import contextlib
import io
import json
import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from optimizer import report

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "front_sample.json")
SLIDER_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "slider_sample.json")
SVG_NS = "{http://www.w3.org/2000/svg}"


def load_front():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class PickProfilesTest(unittest.TestCase):
    def setUp(self):
        self.front = load_front()["front"]

    def test_extremes(self):
        idx = report.pick_profiles(self.front)
        times = [p["f_time_ratio"] for p in self.front]
        kcal = [p["active_kcal"] for p in self.front]
        self.assertEqual(self.front[idx["fast"]]["f_time_ratio"], min(times))
        self.assertEqual(self.front[idx["active"]]["active_kcal"], max(kcal))

    def test_knee_in_middle(self):
        idx = report.pick_profiles(self.front)
        b = self.front[idx["balanced"]]
        self.assertNotIn(idx["balanced"], (idx["fast"], idx["active"]))
        self.assertGreater(b["f_time_ratio"], min(p["f_time_ratio"] for p in self.front))
        self.assertLess(b["f_time_ratio"], max(p["f_time_ratio"] for p in self.front))
        # Knee of the fixture (concave front) is the 1.24x point.
        self.assertAlmostEqual(b["f_time_ratio"], 1.24)

    def test_small_fronts(self):
        one = [{"f_time_ratio": 1.0, "active_kcal": 10, "cv": 0}]
        self.assertEqual(report.pick_profiles(one), {"fast": 0, "balanced": 0, "active": 0})
        two = one + [{"f_time_ratio": 1.5, "active_kcal": 90, "cv": 0}]
        idx = report.pick_profiles(two)
        self.assertEqual((idx["fast"], idx["active"]), (0, 1))

    def test_prefers_feasible(self):
        front = [{"f_time_ratio": 0.9, "active_kcal": 5, "cv": 3.0},
                 {"f_time_ratio": 1.0, "active_kcal": 10, "cv": 0},
                 {"f_time_ratio": 1.2, "active_kcal": 80, "cv": 0},
                 {"f_time_ratio": 1.5, "active_kcal": 100, "cv": 0}]
        self.assertEqual(report.pick_profiles(front)["fast"], 1)


class PluralTest(unittest.TestCase):
    def test_points(self):
        forms = ("punkt", "punkty", "punktów")
        got = {n: report.plural(n, *forms) for n in (1, 2, 4, 5, 12, 22)}
        self.assertEqual(got, {1: "punkt", 2: "punkty", 4: "punkty", 5: "punktów",
                               12: "punktów", 22: "punkty"})

    def test_pairs(self):
        forms = ("para", "pary", "par")
        got = {n: report.plural(n, *forms) for n in (1, 2, 4, 5, 12, 22)}
        self.assertEqual(got, {1: "para", 2: "pary", 4: "pary", 5: "par", 12: "par", 22: "pary"})


def _pt(t, k, cv=0.0, steps=500):
    return {"f_time_ratio": t, "active_kcal": k, "steps": steps, "duration_min": 40, "cv": cv,
            "query": {"modes": {"transitOnly": True, "transit": {"access": ["WALK"]}}, "preferences": {}}}


def _label_boxes(svg_text):
    root = ET.fromstring(svg_text)
    g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "labels"][0]
    out = []
    for r in g.findall(f"{SVG_NS}rect"):
        x, y = float(r.get("x")), float(r.get("y"))
        out.append((x, y, x + float(r.get("width")), y + float(r.get("height"))))
    return root, out


class EdgeCasesTest(unittest.TestCase):
    def _render(self, front, meta=None):
        prof = report.resolve_profiles(front)
        return report.render_svg(front, prof, meta or {}), report.render_md(front, prof, meta or {})

    def test_two_point_front_labels_off_markers(self):
        front = [_pt(1.0, 20), _pt(1.5, 200)]
        svg, _ = self._render(front)
        root, boxes = _label_boxes(svg)
        texts = " ".join("".join(t.itertext()) for t in root.iter(f"{SVG_NS}text"))
        for label in ("Szybki", "Zbalansowany", "Aktywny"):
            self.assertIn(label, texts)
        markers = [(float(c.get("cx")), float(c.get("cy"))) for c in root.iter(f"{SVG_NS}circle")
                   if c.get("r") == "9"]
        self.assertEqual(len(markers), 2)  # balanced == active -> merged marker
        for bx0, by0, bx1, by1 in boxes:
            for cx, cy in markers:
                inside = bx0 - 9 < cx < bx1 + 9 and by0 - 9 < cy < by1 + 9
                self.assertFalse(inside, f"label box {(bx0, by0, bx1, by1)} covers marker {(cx, cy)}")

    def test_plural_in_outputs(self):
        front = [_pt(1.0, 20), _pt(1.5, 200)]
        svg, md = self._render(front, {"pairs": ["a", "b"]})
        self.assertIn("2 punkty frontu", svg)
        self.assertIn("2 pary", svg)
        self.assertIn("2 punkty", md)
        svg, md = self._render([_pt(1.0, 20)], {"pairs": ["a"]})
        self.assertIn("1 punkt frontu", svg)
        self.assertIn("1 para", md)

    def test_infeasible_legend(self):
        front = [_pt(1.0, 20), _pt(1.2, 120), _pt(1.6, 220, cv=4.0)]
        svg, _ = self._render(front)
        self.assertIn("przekracza limit czasu", svg)
        svg, _ = self._render([_pt(1.0, 20), _pt(1.2, 120)])
        self.assertNotIn("przekracza limit czasu", svg)

    def test_string_and_none_metrics(self):
        front = [_pt("1.0", "22"), _pt(1.2, None), _pt(1.3, "abc", cv=None), _pt(1.5, 210)]
        front[0]["steps"] = None
        front[3]["duration_min"] = "n/a"
        idx = report.pick_profiles(front)
        self.assertEqual((idx["fast"], idx["active"]), (0, 3))
        svg, md = self._render(front)
        ET.fromstring(svg)
        self.assertIn("—", md)
        self.assertIn("| Szybki | 1,00 |", md)
        # No numeric metric at all: still no exception.
        bad = [_pt(None, None), _pt("x", "y")]
        svg, md = self._render(bad)
        ET.fromstring(svg)


class ReferenceLineTest(unittest.TestCase):
    def _svg(self, front):
        return report.render_svg(front, report.resolve_profiles(front), {})

    def _ref_x_and_ticks(self, svg):
        root = ET.fromstring(svg)
        dashed = [l for l in root.iter(f"{SVG_NS}line") if l.get("stroke-dasharray")]
        ticks = {}
        for t in root.find(f"{SVG_NS}g[@class='grid']").iter(f"{SVG_NS}text"):
            if t.text and t.text.endswith("×"):
                ticks[float(t.text[:-1].replace(",", "."))] = float(t.get("x"))
        return dashed, ticks

    def test_values_below_one(self):
        front = [_pt(0.7, 180), _pt(1.0, 20), _pt(1.2, 120), _pt(1.5, 220)]
        svg = self._svg(front)
        self.assertIn("= czas KMK", svg)
        dashed, ticks = self._ref_x_and_ticks(svg)
        self.assertEqual(len(dashed), 1)
        self.assertLess(min(ticks), 1.0)
        # Every point (incl. 0.7x) lies inside the plot area, left of the 1.0x line.
        root = ET.fromstring(svg)
        cxs = [float(c.get("cx")) for c in root.find(f"{SVG_NS}g[@class='front']").iter(f"{SVG_NS}circle")]
        self.assertTrue(all(report.M_LEFT < x < report.W - report.M_RIGHT for x in cxs))
        self.assertLess(min(cxs), float(dashed[0].get("x1")))
        self.assertAlmostEqual(float(dashed[0].get("x1")), ticks[1.0], delta=0.2)
        self.assertEqual(report.pick_profiles(front)["fast"], 0)

    def test_axis_always_includes_one(self):
        front = [_pt(1.2, 20), _pt(1.3, 120), _pt(1.5, 220)]
        svg = self._svg(front)
        dashed, ticks = self._ref_x_and_ticks(svg)
        self.assertEqual(len(dashed), 1)
        self.assertIn(1.0, ticks)


class WeightsTest(unittest.TestCase):
    def test_transit_only_direct(self):
        q = {"modes": {"transitOnly": True, "transit": {"access": ["BICYCLE_PARKING"]}},
             "preferences": {"street": {"walk": {"reluctance": 2.0}, "bicycle": {"reluctance": 1.5}}}}
        w = report.main_weights(q)
        self.assertEqual(w, {"walk.reluctance": 2.0, "bicycle.reluctance": 1.5,
                             "access": "BICYCLE_PARKING", "direct": "brak"})

    def test_direct(self):
        q = {"modes": {"direct": ["BICYCLE"], "transit": {"access": ["BICYCLE"]}}, "preferences": {}}
        w = report.main_weights(q)
        self.assertEqual((w["access"], w["direct"]), ("BICYCLE", "BICYCLE"))


class ReportOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.svg_path, cls.md_path = report.build_report(FIXTURE, out_dir=cls.tmp.name)
        cls.n = len(load_front()["front"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_files_in_out_dir(self):
        self.assertEqual(os.path.dirname(self.svg_path), self.tmp.name)
        self.assertTrue(os.path.exists(self.svg_path))
        self.assertTrue(os.path.exists(self.md_path))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(FIXTURE), "front.svg")))

    def test_svg_parses_and_has_points_and_labels(self):
        root = ET.parse(self.svg_path).getroot()
        circles = root.findall(f".//{SVG_NS}circle")
        self.assertGreaterEqual(len(circles), self.n)
        texts = " ".join("".join(t.itertext()) for t in root.iter(f"{SVG_NS}text"))
        for label in ("Szybki", "Zbalansowany", "Aktywny", "Front Pareto: czas vs ruch",
                      "Czas przejazdu względem najszybszej trasy komunikacją (×)", "= czas KMK",
                      "Aktywne kalorie na trasę (kcal, 70 kg)"):
            self.assertIn(label, texts)

    def test_profile_labels_do_not_overlap(self):
        root = ET.parse(self.svg_path).getroot()
        g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "labels"][0]
        boxes = []
        for r in g.findall(f"{SVG_NS}rect"):
            x, y = float(r.get("x")), float(r.get("y"))
            boxes.append((x, y, x + float(r.get("width")), y + float(r.get("height"))))
        self.assertEqual(len(boxes), 3)
        for i in range(3):
            for j in range(i + 1, 3):
                a, b = boxes[i], boxes[j]
                overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
                self.assertFalse(overlap, f"label boxes {i} and {j} overlap")

    def test_markdown_profile_table(self):
        with open(self.md_path, encoding="utf-8") as f:
            md = f.read()
        rows = [l for l in md.splitlines()
                if l.startswith("| Szybki") or l.startswith("| Zbalansowany") or l.startswith("| Aktywny")]
        self.assertEqual(len(rows), 3)
        self.assertIn("walk.reluctance", md)
        self.assertIn("bicycle.reluctance", md)
        # Szybki row: access WALK, transitOnly -> direct "brak".
        self.assertTrue(rows[0].rstrip().endswith("| WALK | brak |"))

    def test_profiles_json_next_to_front(self):
        data = load_front()
        idx = report.pick_profiles(data["front"])
        prof = {}
        for key, i in idx.items():
            p = data["front"][i]
            prof[key] = dict(p["query"], metrics={"f_time_ratio": p["f_time_ratio"],
                                                  "active_kcal": p["active_kcal"], "steps": p["steps"]})
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "front.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            with open(os.path.join(d, "profiles.json"), "w", encoding="utf-8") as f:
                json.dump(prof, f)
            report.main([fp])
            with open(os.path.join(d, "front.md"), encoding="utf-8") as f:
                md = f.read()
            self.assertIn("profiles.json", md)
            ET.parse(os.path.join(d, "front.svg"))


def load_slider():
    with open(SLIDER_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _tick_elements(svg_text):
    root = ET.fromstring(svg_text)
    return root, [e for e in root.iter() if e.get("class") == "tick"]


def _suwak_rows(md):
    lines = md.splitlines()
    start = lines.index("## Suwak")
    rows = []
    for l in lines[start + 1:]:
        if l.startswith("## "):
            break
        if l.startswith("| ") and not l.startswith("| Ząbek"):
            rows.append(l)
    return rows


class SliderFixtureTest(unittest.TestCase):
    def test_fixture_consistent_with_front(self):
        front = load_front()["front"]
        sl = load_slider()
        meta = sl["meta"]
        self.assertEqual(set(meta), {"variant", "n", "f1", "f2", "distinct", "source", "generated"})
        self.assertEqual((meta["n"], len(sl["ticks"])), (7, 7))
        self.assertEqual(meta["distinct"], len({t["index"] for t in sl["ticks"]}))
        for i, t in enumerate(sl["ticks"]):
            self.assertEqual(set(t), {"s", "u", "index", "modes", "preferences", "metrics"})
            self.assertAlmostEqual(t["s"], i / 6, places=5)
            p = front[t["index"]]
            self.assertEqual(t["modes"], p["query"]["modes"])
            self.assertEqual(t["preferences"], p["query"]["preferences"])
            for f in ("f_time_ratio", "active_kcal", "steps", "duration_min"):
                self.assertEqual(t["metrics"][f], p[f])
        # Tick 0 = fastest, last tick = most kcal; both non-decreasing.
        times = [t["metrics"]["f_time_ratio"] for t in sl["ticks"]]
        kcal = [t["metrics"]["active_kcal"] for t in sl["ticks"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(kcal, sorted(kcal))
        self.assertEqual(times[0], min(p["f_time_ratio"] for p in front))
        self.assertEqual(kcal[-1], max(p["active_kcal"] for p in front))


class SliderReportTest(unittest.TestCase):
    def setUp(self):
        self.front = load_front()["front"]
        self.slider = load_slider()
        self.prof = report.resolve_profiles(self.front)

    def test_ticks_on_svg(self):
        svg = report.render_svg(self.front, self.prof, {}, self.slider)
        root, ticks = _tick_elements(svg)
        n = len(self.slider["ticks"])
        self.assertEqual(len(ticks), n)
        labels = sorted(int("".join(t.find(f"{SVG_NS}text").itertext())) for t in ticks)
        self.assertEqual(labels, list(range(n)))
        texts = " ".join("".join(t.itertext()) for t in root.iter(f"{SVG_NS}text"))
        for label in ("ząbek suwaka", "wariant: rower", "Suwak: czas ↔ ruch",
                      "Szybki", "Zbalansowany", "Aktywny", "= czas KMK"):
            self.assertIn(label, texts)

    def test_no_ticks_without_slider(self):
        svg = report.render_svg(self.front, self.prof, {})
        _, ticks = _tick_elements(svg)
        self.assertEqual(ticks, [])
        self.assertNotIn("ząbek suwaka", svg)
        self.assertNotIn("Suwak", svg)
        md = report.render_md(self.front, self.prof, {})
        self.assertNotIn("## Suwak", md)
        # Malformed slider docs are ignored, not fatal.
        for bad in ({}, {"ticks": None}, {"ticks": ["x", {"s": 0.5}]}):
            _, ticks = _tick_elements(report.render_svg(self.front, self.prof, {}, bad))
            self.assertEqual(ticks, [])

    def test_markdown_suwak_table(self):
        md = report.render_md(self.front, self.prof, {}, None, self.slider)
        rows = _suwak_rows(md)
        self.assertEqual(len(rows), len(self.slider["ticks"]))
        # Tick 3 = 1.24x knee point, Polish decimal comma.
        self.assertTrue(rows[3].startswith("| 3 | 0,50 | 1,24 | 40,8 | 171 | 731 |"), rows[3])
        self.assertIn("wariant: rower", md)

    def test_labels_avoid_tick_labels_and_profiles(self):
        svg = report.render_svg(self.front, self.prof, {}, self.slider)
        root, boxes = _label_boxes(svg)
        self.assertEqual(len(boxes), 3)
        g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "tick-labels"][0]
        for t in g.findall(f"{SVG_NS}text"):
            x, y = float(t.get("x")), float(t.get("y"))
            tb = (x, y - 11, x + report._text_w(t.text, 12, True), y)
            for b in boxes:
                self.assertFalse(report._overlap(tb, b), f"tick label {t.text} overlaps profile label {b}")
        # Slider widget does not cover profile labels nor the 1.0x reference label.
        sg = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "slider"][0]
        r = sg.find(f"{SVG_NS}rect")
        wb = (float(r.get("x")), float(r.get("y")),
              float(r.get("x")) + float(r.get("width")), float(r.get("y")) + float(r.get("height")))
        for b in boxes:
            self.assertFalse(report._overlap(wb, b))
        dashed = [l for l in root.iter(f"{SVG_NS}line") if l.get("stroke-dasharray")][0]
        self.assertFalse(wb[0] <= float(dashed.get("x1")) <= wb[2])

    def test_distinct_less_than_n(self):
        # Three-point front, 7 ticks: 0 -> fast, 1-3 -> middle, 4-6 -> active.
        front = [_pt(1.0, 20), _pt(1.2, 120), _pt(1.6, 220)]
        idx = [0, 1, 1, 1, 2, 2, 2]
        slider = {"meta": {"variant": "walk", "n": 7, "f1": "f_time_ratio", "f2": "active_kcal",
                           "distinct": 3, "source": "front.json", "generated": "2026-10-03T21:00"},
                  "ticks": [{"s": i / 6, "u": i / 6, "index": j, "modes": {}, "preferences": {},
                             "metrics": {k: front[j][k] for k in ("f_time_ratio", "active_kcal",
                                                                   "steps", "duration_min")}}
                            for i, j in enumerate(idx)]}
        prof = report.resolve_profiles(front)
        svg = report.render_svg(front, prof, {}, slider)
        root, ticks = _tick_elements(svg)
        self.assertEqual(len(ticks), 7)
        g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "tick-labels"][0]
        self.assertEqual(sorted(t.text for t in g.findall(f"{SVG_NS}text")), ["0", "1–3", "4–6"])
        self.assertIn("wariant: bez roweru", svg)
        md = report.render_md(front, prof, {}, None, slider)
        self.assertEqual(len(_suwak_rows(md)), 7)
        self.assertIn("3 różne punkty", md)

    def test_tick_range_label(self):
        self.assertEqual(report._tick_range_label([2, 3, 4]), "2–4")
        self.assertEqual(report._tick_range_label([1, 3]), "1, 3")
        self.assertEqual(report._tick_range_label([0, 1]), "0, 1")
        self.assertEqual(report._tick_range_label([5]), "5")


class SliderBuildReportTest(unittest.TestCase):
    def _run(self, with_slider, cli_flag=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = tmp.name
        fp = os.path.join(d, "front.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(load_front(), f)
        argv = [fp]
        if with_slider and not cli_flag:
            with open(os.path.join(d, "slider.json"), "w", encoding="utf-8") as f:
                json.dump(load_slider(), f)
        if cli_flag:
            argv += ["--slider", SLIDER_FIXTURE, "--out", os.path.join(d, "out")]
            d = os.path.join(d, "out")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main(argv), 0)
        with open(os.path.join(d, "front.svg"), encoding="utf-8") as f:
            svg = f.read()
        with open(os.path.join(d, "front.md"), encoding="utf-8") as f:
            md = f.read()
        return svg, md

    def test_auto_loads_slider_next_to_front(self):
        svg, md = self._run(True)
        self.assertEqual(len(_tick_elements(svg)[1]), 7)
        self.assertEqual(len(_suwak_rows(md)), 7)

    def test_cli_slider_flag(self):
        svg, md = self._run(True, cli_flag=True)
        self.assertEqual(len(_tick_elements(svg)[1]), 7)
        self.assertEqual(len(_suwak_rows(md)), 7)

    def test_no_slider_output_unchanged(self):
        svg, md = self._run(False)
        prof = report.resolve_profiles(load_front()["front"])
        self.assertEqual(svg, report.render_svg(load_front()["front"], prof, load_front()["meta"]))
        self.assertEqual(_tick_elements(svg)[1], [])
        self.assertNotIn("Suwak", md)


def _tick_diamonds(root):
    """(cx, cy, h) of the front diamond in each class="tick" group."""
    out = []
    for g in root.iter():
        if g.get("class") != "tick":
            continue
        d = g.find(f"{SVG_NS}path").get("d").replace("M", "").replace("L", "").replace("Z", "").split()
        (x0, y0), (x1, y1) = (map(float, d[0].split(",")), map(float, d[1].split(",")))
        out.append((x0, y1, x1 - x0))
    return out


def _assert_labels_near_or_led(test, svg):
    """Every tick label is within ~1.5 text heights of a diamond, or has a leader line ending at it."""
    root = ET.fromstring(svg)
    diamonds = _tick_diamonds(root)
    g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "tick-labels"][0]
    leader_ends = [(float(l.get("x2")), float(l.get("y2"))) for l in g.findall(f"{SVG_NS}line")]
    for t in g.findall(f"{SVG_NS}text"):
        x, y = float(t.get("x")) - 1, float(t.get("y")) + 2
        box = (x, y - 13, x + report._text_w(t.text, 12, True) + 2, y)
        gap = min(math.hypot(min(max(cx, box[0]), box[2]) - cx, min(max(cy, box[1]), box[3]) - cy) - h / math.sqrt(2)
                  for cx, cy, h in diamonds)
        led = any(box[0] - 1 <= lx <= box[2] + 1 and box[1] - 1 <= ly <= box[3] + 1 for lx, ly in leader_ends)
        test.assertTrue(gap <= 1.5 * 13 + 0.5 or led, f"label {t.text!r} is {gap:.1f}px away without a leader")


class SlidePolishTest(unittest.TestCase):
    def test_hint_clear_of_reference_line(self):
        for front in (load_front()["front"], [_pt(1.2, 20), _pt(1.3, 120), _pt(1.5, 220)],
                      [_pt(0.7, 180), _pt(1.0, 20), _pt(1.5, 220)]):
            svg = report.render_svg(front, report.resolve_profiles(front), {})
            root = ET.fromstring(svg)
            hint = [t for t in root.iter(f"{SVG_NS}text") if t.text == report.HINT][0]
            hx = float(hint.get("x"))
            hw = report._text_w(report.HINT, 12)
            rx = float([l for l in root.iter(f"{SVG_NS}line") if l.get("stroke-dasharray")][0].get("x1"))
            crosses = hx - 2 <= rx <= hx + hw + 2
            self.assertTrue(not crosses or hint.get("paint-order") == "stroke",
                            f"reference line x={rx} cuts the hint at x={hx}")

    def test_dense_cluster_merged_with_leader(self):
        # 1.00x .. 1.06x squeezed next to a far 1.6x point: middle ticks are a few px apart.
        front = [_pt(1.0 + 0.01 * i, 20 + 8 * i) for i in range(7)] + [_pt(1.6, 260)]
        slider = {"meta": {"variant": "bike", "n": 7}, "ticks": [
            {"s": i / 6, "u": i / 6, "index": i, "modes": {}, "preferences": {}, "metrics": {}}
            for i in range(7)]}
        prof = report.resolve_profiles(front)
        svg = report.render_svg(front, prof, {}, slider)
        root, ticks = _tick_elements(svg)
        self.assertEqual(len(ticks), 7)
        g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "tick-labels"][0]
        labels = [t.text for t in g.findall(f"{SVG_NS}text")]
        # Every tick number is shown exactly once, and a range label merges the cluster.
        shown = []
        for lab in labels:
            for part in lab.split(", "):
                a_, _, b_ = part.partition("–")
                shown += list(range(int(a_), int(b_ or a_) + 1))
        self.assertEqual(sorted(shown), list(range(7)))
        self.assertLess(len(labels), 7)
        self.assertTrue(any("–" in lab for lab in labels), labels)
        _assert_labels_near_or_led(self, svg)

    def test_tick_labels_near_or_with_leader(self):
        svg = report.render_svg(load_front()["front"], report.resolve_profiles(load_front()["front"]),
                                {}, load_slider())
        root = ET.fromstring(svg)
        g = [e for e in root.iter(f"{SVG_NS}g") if e.get("class") == "tick-labels"][0]
        leaders = g.findall(f"{SVG_NS}line")
        for ln in leaders:
            self.assertEqual(ln.get("class"), "tick-leader")
            self.assertGreater(math.hypot(float(ln.get("x2")) - float(ln.get("x1")),
                                          float(ln.get("y2")) - float(ln.get("y1"))), 5)
        _assert_labels_near_or_led(self, svg)
        front = [_pt(1.0, 20), _pt(1.2, 120), _pt(1.6, 220)]
        three = {"ticks": [{"s": i / 6, "index": j, "metrics": {}} for i, j in enumerate([0, 1, 1, 1, 2, 2, 2])]}
        _assert_labels_near_or_led(self, report.render_svg(front, report.resolve_profiles(front), {}, three))


if __name__ == "__main__":
    unittest.main()
