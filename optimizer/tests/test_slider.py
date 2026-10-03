import contextlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from optimizer import slider

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "front_sample.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
META_KEYS = {"variant", "n", "f1", "f2", "distinct", "merged", "merge_eps", "source", "generated"}
TICK_KEYS = {"s", "u", "index", "modes", "preferences", "metrics"}
METRIC_KEYS = {"f_time_ratio", "active_kcal", "steps", "duration_min"}


def pt(t, k, steps=0, dur=30.0, tag=None):
    return {"f_time_ratio": t, "active_kcal": k, "steps": steps, "duration_min": dur,
            "query": {"modes": {"tag": tag}, "preferences": {"tag": tag}}}


def load_doc():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class ArcPositionsTest(unittest.TestCase):
    def test_collinear_three(self):
        u = slider.arc_positions([pt(1.0, 0), pt(1.2, 50), pt(1.4, 100)])
        self.assertEqual(len(u), 3)
        for a, b in zip(u, [0.0, 0.5, 1.0]):
            self.assertAlmostEqual(a, b)

    def test_aligned_with_sorted_front(self):
        pts = [pt(1.4, 100, tag="c"), pt(1.0, 0, tag="a"), pt(1.2, 50, tag="b")]
        u = slider.arc_positions(pts)
        tags = [p["query"]["modes"]["tag"] for p in slider.sorted_front(pts)]
        self.assertEqual(tags, ["a", "b", "c"])
        self.assertAlmostEqual(u[1], 0.5)

    def test_monotone_first_last(self):
        u = slider.arc_positions(load_doc()["front"])
        self.assertEqual(u[0], 0.0)
        self.assertEqual(u[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(u, u[1:])))
        rng = random.Random(3)
        for _ in range(50):
            pts = [pt(rng.uniform(1, 2), rng.uniform(0, 300)) for _ in range(rng.randint(2, 15))]
            u = slider.arc_positions(pts)
            self.assertEqual((u[0], u[-1]), (0.0, 1.0))
            self.assertTrue(all(0.0 <= a <= b <= 1.0 for a, b in zip(u, u[1:])))

    def test_one_point_and_empty(self):
        self.assertEqual(slider.arc_positions([pt(1.1, 40)]), [0.0])
        self.assertEqual(slider.arc_positions([]), [])

    def test_identical_points_even_spacing(self):
        u = slider.arc_positions([pt(1.1, 40)] * 3)
        self.assertEqual(u, [0.0, 0.5, 1.0])

    def test_zero_range_axis_skipped(self):
        # same time, kcal 0/30/90 -> only kcal axis counts
        u = slider.arc_positions([pt(1.0, 0), pt(1.0, 30), pt(1.0, 90)])
        # sorted by kcal desc on time ties: 90, 30, 0
        for a, b in zip(u, [0.0, 60 / 90, 1.0]):
            self.assertAlmostEqual(a, b)

    def test_normalisation_scale_free(self):
        # kcal in hundreds vs time ratio in tenths must not dominate distance
        u = slider.arc_positions([pt(1.0, 0), pt(1.5, 1), pt(2.0, 1000)])
        d1 = (0.5 ** 2 + 0.001 ** 2) ** 0.5
        d2 = (0.5 ** 2 + 0.999 ** 2) ** 0.5
        self.assertAlmostEqual(u[1], d1 / (d1 + d2))


class SampleFrontTest(unittest.TestCase):
    def setUp(self):
        self.front = load_doc()["front"]

    def check_monotone(self, ticks):
        for a, b in zip(ticks, ticks[1:]):
            self.assertLessEqual(a["metrics"]["f_time_ratio"], b["metrics"]["f_time_ratio"])
            self.assertLessEqual(a["metrics"]["active_kcal"], b["metrics"]["active_kcal"])

    def test_seven_ticks_on_fixture(self):
        ticks = slider.sample_front(self.front, 7)
        self.assertEqual(len(ticks), 7)
        for i, t in enumerate(ticks):
            self.assertEqual(set(t), TICK_KEYS)
            self.assertEqual(set(t["metrics"]), METRIC_KEYS)
            self.assertAlmostEqual(t["s"], i / 6)
        times = [p["f_time_ratio"] for p in self.front]
        kcal = [p["active_kcal"] for p in self.front]
        self.assertEqual(ticks[0]["metrics"]["f_time_ratio"], min(times))
        self.assertEqual(ticks[-1]["metrics"]["active_kcal"], max(kcal))
        self.check_monotone(ticks)

    def test_index_points_into_sorted_front(self):
        srt = slider.sorted_front(self.front)
        for t in slider.sample_front(self.front, 7):
            p = srt[t["index"]]
            self.assertEqual(p["f_time_ratio"], t["metrics"]["f_time_ratio"])
            self.assertEqual(p["query"]["modes"], t["modes"])
            self.assertEqual(p["query"]["preferences"], t["preferences"])

    def test_two_points(self):
        ticks = slider.sample_front([pt(1.5, 200, tag="slow"), pt(1.0, 10, tag="fast")], 7)
        self.assertEqual(len(ticks), 7)
        self.assertEqual(len({t["index"] for t in ticks}), 2)
        self.assertEqual(ticks[0]["modes"]["tag"], "fast")
        self.assertEqual(ticks[-1]["modes"]["tag"], "slow")
        # s = 0.5 is a tie (u 0 vs 1) -> faster point
        self.assertEqual(ticks[3]["modes"]["tag"], "fast")
        self.check_monotone(ticks)

    def test_single_point(self):
        ticks = slider.sample_front([pt(1.0, 10)], 7)
        self.assertEqual(len(ticks), 7)
        self.assertEqual({t["index"] for t in ticks}, {0})

    def test_dominated_points_filtered(self):
        pts = [pt(1.0, 10), pt(1.2, 5, tag="dom"), pt(1.3, 100), pt(1.3, 50, tag="dom"),
               pt(1.6, 100, tag="dom"), pt(1.5, 150)]
        ticks = slider.sample_front(pts, 7)
        self.assertNotIn("dom", [t["modes"]["tag"] for t in ticks])
        self.check_monotone(ticks)
        self.assertEqual(len(slider.pareto_filter(pts)), 3)

    def test_random_fronts_monotone(self):
        rng = random.Random(7)
        for _ in range(100):
            pts = [pt(round(rng.uniform(1, 2), 2), round(rng.uniform(0, 300))) for _ in range(rng.randint(1, 20))]
            n = rng.randint(2, 11)
            ticks = slider.sample_front(pts, n)
            self.assertEqual(len(ticks), n)
            self.check_monotone(ticks)
            self.assertEqual(ticks[0]["metrics"]["f_time_ratio"], min(p["f_time_ratio"] for p in pts))
            self.assertEqual(ticks[-1]["metrics"]["active_kcal"], max(p["active_kcal"] for p in pts))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            slider.sample_front([], 7)
        with self.assertRaises(ValueError):
            slider.sample_front(self.front, 1)


class BuildSliderTest(unittest.TestCase):
    def test_schema(self):
        doc = load_doc()
        s = slider.build_slider(doc, 7)
        self.assertEqual(set(s), {"meta", "ticks"})
        self.assertEqual(set(s["meta"]), META_KEYS)
        m = s["meta"]
        self.assertEqual((m["variant"], m["n"], m["f1"], m["f2"], m["source"]),
                         ("bike", 7, "f_time_ratio", "active_kcal", "front.json"))
        self.assertEqual(m["distinct"], len({t["index"] for t in s["ticks"]}))
        self.assertEqual(len(s["ticks"]), 7)

    def test_variant(self):
        doc = load_doc()
        self.assertEqual(slider.build_slider(doc, variant="walk")["meta"]["variant"], "walk")
        doc["meta"]["variant"] = "walk"
        self.assertEqual(slider.build_slider(doc)["meta"]["variant"], "walk")
        self.assertEqual(slider.build_slider(doc, variant="bike")["meta"]["variant"], "bike")

    def test_two_point_distinct(self):
        s = slider.build_slider({"meta": {}, "front": [pt(1.0, 10), pt(1.5, 200)]}, 7)
        self.assertEqual(len(s["ticks"]), 7)
        self.assertEqual(s["meta"]["distinct"], 2)


class MergeTest(unittest.TestCase):
    CLOSE = [pt(1.000, 10, tag="a"), pt(1.002, 10.5, tag="b"), pt(1.004, 11.5, tag="c"),
             pt(1.3, 100, tag="d"), pt(1.6, 200, tag="e")]

    def test_close_points_merged_fastest_represents(self):
        reps, merged = slider.merge_close(slider.sorted_front(self.CLOSE))
        self.assertEqual([p["query"]["modes"]["tag"] for p in reps], ["a", "d", "e"])
        self.assertEqual(merged, 2)

    def test_far_points_not_merged(self):
        far = [pt(1.0, 10), pt(1.02, 10.5), pt(1.5, 14), pt(1.5001, 30)]  # time-only / kcal-only close
        reps, merged = slider.merge_close(far)
        self.assertEqual((len(reps), merged), (4, 0))

    def test_no_chaining(self):
        # 0.004 steps: groups {0,1} and {2,3}; the last group is pinned to its last point
        pts = [pt(1.0 + 0.004 * i, 10 + 0.1 * i, tag=str(i)) for i in range(4)]
        reps, merged = slider.merge_close(pts)
        self.assertEqual([p["query"]["modes"]["tag"] for p in reps], ["0", "3"])
        self.assertEqual(merged, 2)

    def test_last_point_pinned_to_max_kcal(self):
        pts = [pt(1.0, 10), pt(1.5, 100, tag="x"), pt(1.502, 101, tag="max")]
        reps, _ = slider.merge_close(pts)
        self.assertEqual(reps[-1]["query"]["modes"]["tag"], "max")
        ticks = slider.sample_front(pts, 7)
        self.assertEqual(ticks[-1]["metrics"]["active_kcal"], 101)

    def test_eps_zero_equals_unmerged(self):
        for eps in (0, None, (0, 0)):
            self.assertEqual(slider.merge_close(slider.sorted_front(self.CLOSE), eps)[1], 0)
        old = slider.sample_front(self.CLOSE, 25, merge_eps=0)  # dense ticks: unmerged "c" is reachable
        self.assertIn("c", {t["modes"]["tag"] for t in old})
        doc = {"meta": {}, "front": self.CLOSE}
        s0 = slider.build_slider(doc, 7, merge_eps=0)
        self.assertEqual((s0["meta"]["merged"], s0["meta"]["merge_eps"]), (0, None))
        # identical to the pre-merge algorithm on the fixture-free random fronts
        rng = random.Random(11)
        for _ in range(50):
            pts = [pt(round(rng.uniform(1, 2), 3), round(rng.uniform(0, 300), 1)) for _ in range(rng.randint(1, 15))]
            nd = slider.pareto_filter(pts)
            u = slider.arc_positions(nd)
            full = slider.sorted_front(pts)
            for i, t in enumerate(slider.sample_front(pts, 5, merge_eps=0)):
                s = i / 4
                best = min(range(len(nd)), key=lambda j: (abs(u[j] - s), j))
                self.assertIs(full[t["index"]], nd[best])

    def test_ticks_and_meta_after_merge(self):
        doc = {"meta": {}, "front": self.CLOSE}
        s = slider.build_slider(doc, 7)
        self.assertEqual(s["meta"]["merged"], 2)
        self.assertEqual(s["meta"]["merge_eps"], {"time": 0.005, "kcal": 2.0})
        self.assertEqual(s["meta"]["distinct"], 3)
        srt = slider.sorted_front(self.CLOSE)
        for t in s["ticks"]:
            self.assertEqual(srt[t["index"]]["f_time_ratio"], t["metrics"]["f_time_ratio"])
            self.assertNotIn(t["modes"]["tag"], ("b", "c"))
        for a, b in zip(s["ticks"], s["ticks"][1:]):
            self.assertLessEqual(a["metrics"]["active_kcal"], b["metrics"]["active_kcal"])
            self.assertLessEqual(a["u"], b["u"])
        # arc is no longer distorted: 3 points at ~equal normalised spacing
        self.assertEqual({t["modes"]["tag"] for t in s["ticks"]}, {"a", "d", "e"})

    def test_random_fronts_monotone_with_merge(self):
        rng = random.Random(5)
        for _ in range(100):
            pts = [pt(round(rng.uniform(1, 1.05), 4), round(rng.uniform(0, 8), 1)) for _ in range(rng.randint(1, 20))]
            ticks = slider.sample_front(pts, rng.randint(2, 9))
            for a, b in zip(ticks, ticks[1:]):
                self.assertLessEqual(a["metrics"]["f_time_ratio"], b["metrics"]["f_time_ratio"])
                self.assertLessEqual(a["metrics"]["active_kcal"], b["metrics"]["active_kcal"])
            self.assertEqual(ticks[-1]["metrics"]["active_kcal"], max(p["active_kcal"] for p in pts))

    def test_cli_merge_flags(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        front = os.path.join(d, "front.json")
        with open(front, "w") as f:
            json.dump({"meta": {}, "front": self.CLOSE}, f)
        for args, merged in (([], 2), (["--merge-eps-time", "0", "--merge-eps-kcal", "0"], 0)):
            out = os.path.join(d, "s.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(slider.main([front, "--out", out] + args), 0)
            with open(out) as f:
                self.assertEqual(json.load(f)["meta"]["merged"], merged)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_cli_default_out_next_to_front(self):
        front = os.path.join(self.tmp, "front.json")
        shutil.copy(FIXTURE, front)
        r = subprocess.run([sys.executable, "-m", "optimizer.slider", front],
                           cwd=REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.tmp, "slider.json"), encoding="utf-8") as f:
            s = json.load(f)
        self.assertEqual(set(s), {"meta", "ticks"})
        self.assertEqual(set(s["meta"]), META_KEYS)
        self.assertEqual(s["meta"]["n"], 7)
        self.assertEqual(len(s["ticks"]), 7)
        for t in s["ticks"]:
            self.assertEqual(set(t), TICK_KEYS)
            self.assertEqual(set(t["metrics"]), METRIC_KEYS)

    def test_cli_options(self):
        out = os.path.join(self.tmp, "sub", "my.json")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = slider.main([FIXTURE, "--n", "5", "--variant", "walk", "--out", out])
        self.assertEqual(rc, 0)
        with open(out, encoding="utf-8") as f:
            s = json.load(f)
        self.assertEqual((s["meta"]["n"], s["meta"]["variant"], len(s["ticks"])), (5, "walk", 5))

    def test_cli_bad_files(self):
        bad_json = os.path.join(self.tmp, "bad.json")
        with open(bad_json, "w") as f:
            f.write("{not json")
        no_front = os.path.join(self.tmp, "nofront.json")
        with open(no_front, "w") as f:
            json.dump({"meta": {}}, f)
        for path in (bad_json, no_front, os.path.join(self.tmp, "missing.json")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = slider.main([path])
            self.assertEqual(rc, 2)
            self.assertIn("ERROR", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
