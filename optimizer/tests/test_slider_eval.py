"""Offline tests for optimizer.slider_eval (no OTP server needed)."""
import io
import unittest
from contextlib import redirect_stdout

from optimizer import slider_eval as se
from optimizer import slider_select as ss

DEADLINE = "2026-10-05T08:30:00+02:00"
O = {"lat": 50.07, "lon": 20.03}
D = {"lat": 50.06, "lon": 19.92}


def itin(legs, end="2026-10-05T08:10:00+02:00"):
    return {"duration": sum(l[1] for l in legs), "end": end, "generalizedCost": 100,
            "legs": [{"mode": m, "duration": d, "distance": dist} for m, d, dist in legs]}


def plan(it):
    return {"edges": [{"node": it}], "routingErrors": []}


class FakeClient:
    def __init__(self, answers):
        self.answers = answers  # tag -> plan result
        self.stats = {"hits": 0, "misses": 0, "errors": 0}

    def plan_many(self, reqs):
        return [self.answers.get(r["tag"], {"edges": [], "routingErrors": []}) for r in reqs]


class Metrics(unittest.TestCase):
    def test_monotonic_with_tolerance(self):
        ok = [{"duration_min": 20, "active_kcal": 10}, {"duration_min": 19.6, "active_kcal": 9.5},
              {"duration_min": 25, "active_kcal": 40}]
        self.assertTrue(se.is_monotonic(ok))
        self.assertFalse(se.is_monotonic([{"duration_min": 20, "active_kcal": 10},
                                          {"duration_min": 19.0, "active_kcal": 10}]))
        self.assertFalse(se.is_monotonic([{"duration_min": 20, "active_kcal": 10},
                                          {"duration_min": 21, "active_kcal": 8.5}]))
        self.assertTrue(se.is_monotonic([]))
        self.assertTrue(se.is_monotonic([{"duration_min": 5, "active_kcal": 1}]))

    def test_distinct_ignores_none(self):
        self.assertEqual(se.count_distinct([("a",), ("a",), ("b",), None]), 2)
        self.assertEqual(se.count_distinct([]), 0)

    def test_percentile(self):
        self.assertEqual(se.percentile([3, 1, 2], 50), 2)
        self.assertEqual(se.percentile([5], 99), 5)

    def test_aggregate(self):
        pp = [{"monotonic": True, "distinct": 5, "n_positions": 4},
              {"monotonic": False, "distinct": 3, "n_positions": 2}]
        a = se.aggregate(pp, [0.5, 1.5, 0.7])
        self.assertAlmostEqual(a["monotonic_rate"], 0.5)
        self.assertAlmostEqual(a["mean_distinct"], 4.0)
        self.assertAlmostEqual(a["mean_positions"], 3.0)
        self.assertAlmostEqual(a["build_s_p50"], 0.7)
        self.assertAlmostEqual(a["build_s_max"], 1.5)
        self.assertEqual(a["targets_met"], {"monotonic_rate": False, "mean_distinct": True,
                                            "build_s_max": True})

    def test_aggregate_empty(self):
        a = se.aggregate([], [])
        self.assertIsNone(a["monotonic_rate"])
        self.assertFalse(any(a["targets_met"].values()))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.slider = {"meta": {}, "ticks": [{"modes": {"direct": ["WALK"]}, "preferences": {}}
                                             for _ in range(3)]}
        walk = itin([("WALK", 1500, 2000)])
        bike = itin([("BICYCLE", 900, 3000)])
        self.answers = {"tick:0": plan(walk), "tick:1": plan(walk), "tick:2": plan(bike),
                        "anchor": plan(walk), "walk": plan(walk)}

    def test_raw_ticks_and_pair(self):
        reqs = ss.tick_requests(self.slider, O, D)
        results = FakeClient(self.answers).plan_many(reqs)
        raw = se.raw_ticks(results, reqs)
        self.assertEqual([r["tick"] for r in raw], [0, 1, 2])
        self.assertEqual(se.count_distinct(r["signature"] for r in raw), 2)
        rs = ss.build_route_slider(results, reqs, DEADLINE)
        m = se.pair_metrics(raw, rs)
        self.assertEqual(m["distinct"], 2)
        self.assertEqual(m["n_positions"], len(rs["positions"]))
        self.assertIn("late", m["dropped"])
        # bike is faster but burns more: walk 25 min / bike 15 min -> time decreases at tick 2
        self.assertFalse(m["monotonic"])

    def test_missing_route_is_none(self):
        reqs = ss.tick_requests(self.slider, O, D)
        results = FakeClient({"tick:1": plan(itin([("WALK", 600, 800)]))}).plan_many(reqs)
        raw = se.raw_ticks(results, reqs)
        self.assertIsNone(raw[0]["signature"])
        self.assertEqual(se.pair_metrics(raw, ss.build_route_slider(results, reqs, DEADLINE))
                         ["distinct"], 1)

    def test_evaluate_pair_and_table(self):
        pair = {"id": "x", "from": O, "to": D}
        m, dt = se.evaluate_pair(self.slider, pair, DEADLINE, FakeClient(self.answers))
        self.assertEqual(m["id"], "x")
        self.assertGreaterEqual(dt, 0.0)
        result = {"summary": se.aggregate([m], [dt]), "per_pair": [m]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            se.print_table(result)
        self.assertIn("monotonic_rate", buf.getvalue())
        self.assertIn("x", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
