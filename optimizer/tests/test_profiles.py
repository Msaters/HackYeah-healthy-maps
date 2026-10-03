"""Tests for optimizer.profiles (and front export helpers in optimizer.run_ga). No OTP needed."""
import json
import unittest

import numpy as np

from optimizer import genome
from optimizer.profiles import METRIC_KEYS, build_profiles, dedupe_front, non_dominated
from optimizer.run_ga import front_points, safe_decode


def point(t, k, tag=None, cv=0.0):
    q = {"modes": {"tag": tag if tag is not None else f"{t}-{k}"}, "preferences": {"w": t}}
    return {"x": [0.0], "query": q, "f_time_ratio": t, "active_kcal": k,
            "steps": 10.0 * k, "duration_min": 30.0 * t, "cv": cv, "per_pair": []}


# Synthetic convex front; normalised to [0, 1]^2 the extremes are (0, 0) and (1, 1),
# distances to the diagonal: (0.1, 0.7) -> 0.42, (0.3, 0.8) -> 0.35, (0.5, 0.9) -> 0.28.
KNEE_FRONT = [point(1.0, 10), point(1.1, 80), point(1.3, 90), point(1.5, 100), point(2.0, 110)]


class TestBuildProfiles(unittest.TestCase):
    def test_keys_and_fields(self):
        p = build_profiles(KNEE_FRONT)
        self.assertEqual(sorted(p), ["active", "balanced", "fast"])
        for v in p.values():
            self.assertEqual(set(v), {"modes", "preferences", "metrics"})
            self.assertEqual(set(v["metrics"]), set(METRIC_KEYS))

    def test_knee(self):
        p = build_profiles(KNEE_FRONT)
        self.assertEqual(p["fast"]["metrics"]["f_time_ratio"], 1.0)
        self.assertEqual(p["balanced"]["metrics"]["f_time_ratio"], 1.1)
        self.assertEqual(p["balanced"]["metrics"]["active_kcal"], 80)
        self.assertEqual(p["active"]["metrics"]["active_kcal"], 110)
        self.assertEqual(p["balanced"]["modes"], KNEE_FRONT[1]["query"]["modes"])

    def test_monotone_on_random_fronts(self):
        rng = np.random.default_rng(0)
        for _ in range(200):
            n = int(rng.integers(1, 12))
            t = np.sort(1.0 + rng.random(n))
            k = np.sort(rng.random(n) * 200)  # non-dominated: slower <=> more kcal
            front = [point(float(a), float(b)) for a, b in zip(t, k)]
            p = build_profiles(front)
            m = {key: p[key]["metrics"] for key in p}
            for f in ("f_time_ratio", "active_kcal"):
                self.assertLessEqual(m["fast"][f], m["balanced"][f])
                self.assertLessEqual(m["balanced"][f], m["active"][f])

    def test_small_fronts(self):
        one = build_profiles([point(1.2, 50)])
        self.assertTrue(all(v["metrics"]["f_time_ratio"] == 1.2 for v in one.values()))
        two = build_profiles([point(1.0, 10), point(1.5, 60)])
        self.assertEqual(two["fast"]["metrics"]["active_kcal"], 10)
        self.assertEqual(two["active"]["metrics"]["active_kcal"], 60)
        same = build_profiles([point(1.0, 10, tag="a"), point(1.0, 10, tag="b")])
        self.assertEqual(sorted(same), ["active", "balanced", "fast"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            build_profiles([])

    def test_json_serialisable(self):
        json.dumps(build_profiles(KNEE_FRONT))


class TestDedupe(unittest.TestCase):
    def test_identical_query_dropped(self):
        pts = [point(1.3, 90, tag="same"), point(1.0, 10, tag="a"), point(1.3, 90, tag="same")]
        out = dedupe_front(pts)
        self.assertEqual(len(out), 2)
        self.assertEqual([p["f_time_ratio"] for p in out], [1.0, 1.3])

    def test_key_order_irrelevant(self):
        a = point(1.0, 10)
        b = dict(a, query={"preferences": {"w": 1.0}, "modes": {"tag": "1.0-10"}})
        self.assertEqual(len(dedupe_front([a, b])), 1)

    def test_sorted_by_time(self):
        out = dedupe_front(list(reversed(KNEE_FRONT)))
        self.assertEqual([p["f_time_ratio"] for p in out], [1.0, 1.1, 1.3, 1.5, 2.0])


class TestNonDominated(unittest.TestCase):
    def test_dominated_removed(self):
        pts = [point(1.0, 10), point(1.2, 5), point(1.1, 80), point(1.3, 80), point(1.5, 100)]
        out = non_dominated(pts)
        self.assertEqual([(p["f_time_ratio"], p["active_kcal"]) for p in out],
                         [(1.0, 10), (1.1, 80), (1.5, 100)])

    def test_equal_metrics_kept(self):
        pts = [point(1.0, 10, tag="a"), point(1.0, 10, tag="b")]
        self.assertEqual(len(non_dominated(pts)), 2)

    def test_random_result_is_non_dominated(self):
        rng = np.random.default_rng(1)
        for _ in range(100):
            pts = [point(float(1 + rng.random()), float(rng.random() * 100))
                   for _ in range(int(rng.integers(1, 15)))]
            out = non_dominated(pts)
            self.assertTrue(out)
            for a in out:
                for b in out:
                    self.assertFalse(a["f_time_ratio"] <= b["f_time_ratio"]
                                     and a["active_kcal"] >= b["active_kcal"]
                                     and (a["f_time_ratio"] < b["f_time_ratio"]
                                          or a["active_kcal"] > b["active_kcal"]))


class TestFrontPoints(unittest.TestCase):
    def _state(self, cvs, queries):
        n = len(cvs)
        details = [{"query": q, "f_time_ratio": 1.0 + 0.1 * i, "active_kcal": 10.0 * i,
                    "steps": 0.0, "duration_min": 20.0, "cv": c, "per_pair": []}
                   for i, (c, q) in enumerate(zip(cvs, queries))]
        return {"X": np.zeros((n, genome.DIM)), "F": np.zeros((n, 2)), "cv": np.array(cvs),
                "details": details, "rank": np.zeros(n, int), "front0": list(range(n))}

    def test_feasible_only_and_dedupe(self):
        qa, qb = {"modes": {"a": 1}}, {"modes": {"b": 1}}
        pts, feas = front_points(self._state([0.0, 0.0, 5.0, 0.0], [qa, qb, qa, qa]))
        self.assertTrue(feas)
        self.assertEqual(len(pts), 2)
        self.assertTrue(all(p["cv"] == 0 for p in pts))

    def test_export_drops_dominated(self):
        st = self._state([0.0, 0.0], [{"a": 1}, {"b": 1}])
        st["details"][1]["f_time_ratio"] = 5.0  # point 0: 1.0x, 0 kcal -> dominates this one
        st["details"][1]["active_kcal"] = 0.0
        pts, _ = front_points(st)
        self.assertEqual(len(pts), 1)

    def test_no_feasible_fallback(self):
        pts, feas = front_points(self._state([3.0, 4.0], [{"a": 1}, {"b": 2}]))
        self.assertFalse(feas)
        self.assertEqual(len(pts), 2)


class TestSafeDecode(unittest.TestCase):
    def test_nan_inf_out_of_range(self):
        x = np.full(genome.DIM, 0.5)
        x[0], x[1], x[2], x[3] = np.nan, np.inf, -np.inf, 7.0
        q = safe_decode(x)
        self.assertIn("modes", q)
        json.dumps(q, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
