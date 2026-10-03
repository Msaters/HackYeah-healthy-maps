import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from optimizer import report

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "front_sample.json")
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


if __name__ == "__main__":
    unittest.main()
