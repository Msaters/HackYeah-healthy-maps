"""Offline tests for optimizer.evaluate (no OTP server needed)."""
import json
import os
import tempfile
import unittest

import numpy as np

from optimizer.evaluate import (OTPClient, build_payload, cache_key, constraint_violation,
                                itinerary_metrics, make_evaluator, pick_itinerary,
                                MAX_TIME_RATIO, time_limit)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "otp_response.json")
OD_PAIRS = os.path.join(HERE, "..", "od_pairs.json")


def load_plan():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)["response"]["data"]["planConnection"]


class StubClient:
    """Fake OTPClient: every plan() returns the fixture; records request count."""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def plan_many(self, requests):
        self.calls += len(requests)
        return [self.result for _ in requests]


def decode_stub(x):
    return {"modes": {"transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}},
            "preferences": {"street": {"walk": {"reluctance": float(0.5 + 4.5 * x[0])}}}}


class TestMetrics(unittest.TestCase):
    ITIN = {"duration": 2700, "generalizedCost": 1000, "legs": [
        {"mode": "WALK", "duration": 600, "distance": 800},
        {"mode": "TRAM", "duration": 900, "distance": 5000},
        {"mode": "BICYCLE", "duration": 1200, "distance": 4000},
    ]}

    def test_kcal_and_steps(self):
        m = itinerary_metrics(self.ITIN, weight=70.0, height=1.75)
        self.assertAlmostEqual(m["active_kcal"], 204.2, delta=0.5)
        self.assertAlmostEqual(m["steps"], 1102, delta=2)
        self.assertAlmostEqual(m["duration_min"], 45.0)
        self.assertAlmostEqual(m["active_min"], 30.0)
        self.assertEqual(m["generalized_cost"], 1000)
        self.assertEqual(m["modes"], ["WALK", "TRAM", "BICYCLE"])

    def test_tram_adds_no_kcal(self):
        tram_only = {"duration": 900, "legs": [{"mode": "TRAM", "duration": 900, "distance": 5000}]}
        m = itinerary_metrics(tram_only)
        self.assertEqual(m["active_kcal"], 0.0)
        self.assertEqual(m["steps"], 0.0)
        bus = {"duration": 900, "legs": [{"mode": "BUS", "duration": 900, "distance": 5000}]}
        self.assertEqual(itinerary_metrics(bus)["active_kcal"], 0.0)

    def test_real_fixture_metrics(self):
        it = load_plan()["edges"][0]["node"]
        m = itinerary_metrics(it)
        self.assertGreater(m["active_kcal"], 0)
        self.assertIn("TRAM", m["modes"])


class TestPick(unittest.TestCase):
    def test_pick_min_generalized_cost(self):
        plan = load_plan()
        self.assertGreaterEqual(len(plan["edges"]), 2)
        best = min(e["node"]["generalizedCost"] for e in plan["edges"])
        # Reverse order so the best one is not simply the first.
        rev = dict(plan, edges=list(reversed(plan["edges"])))
        self.assertEqual(pick_itinerary(rev)["generalizedCost"], best)
        synthetic = {"edges": [{"node": {"generalizedCost": 900, "duration": 100}},
                               {"node": {"generalizedCost": 500, "duration": 999}},
                               {"node": {"generalizedCost": 700, "duration": 50}}]}
        self.assertEqual(pick_itinerary(synthetic)["generalizedCost"], 500)

    def test_pick_none(self):
        self.assertIsNone(pick_itinerary({"edges": [], "routingErrors": [{"code": "X"}]}))
        self.assertIsNone(pick_itinerary({"error": "timeout"}))
        self.assertIsNone(pick_itinerary(None))


class TestConstraint(unittest.TestCase):
    def test_cv(self):
        # baseline 42 -> allowed 1.9 * 42 = 79.8
        self.assertAlmostEqual(constraint_violation(110, 42), 110 - 79.8)
        self.assertGreater(constraint_violation(110, 42), 0)
        self.assertEqual(constraint_violation(50, 42), 0)
        self.assertEqual(constraint_violation(79.8, 42), 0)
        # short baseline: 190% applies without a fixed floor
        self.assertEqual(constraint_violation(19, 10), 0)
        self.assertAlmostEqual(constraint_violation(24, 10), 5.0)
        self.assertEqual(constraint_violation(None, 42), 60.0)

    def test_time_limit(self):
        self.assertEqual(MAX_TIME_RATIO, 1.9)
        self.assertAlmostEqual(time_limit(42), 79.8)


class TestEvaluator(unittest.TestCase):
    def setUp(self):
        with open(OD_PAIRS, encoding="utf-8") as f:
            self.pairs = json.load(f)["pairs"][:3]
        self.baselines = {p["id"]: 40.0 for p in self.pairs}

    def test_shapes_and_values(self):
        plan = load_plan()
        stub = StubClient(plan)
        ev = make_evaluator(self.pairs, self.baselines, stub, decode_stub)
        X = np.random.default_rng(0).random((5, 12))
        F, cv, details = ev(X)
        self.assertEqual(F.shape, (5, 2))
        self.assertEqual(cv.shape, (5,))
        self.assertEqual(len(details), 5)
        self.assertEqual(stub.calls, 5 * 3)  # one batch, all queries at once
        best = pick_itinerary(plan)
        m = itinerary_metrics(best)
        self.assertAlmostEqual(F[0, 0], m["duration_min"] / 40.0)
        self.assertAlmostEqual(F[0, 1], -m["active_kcal"])
        self.assertAlmostEqual(cv[0], constraint_violation(m["duration_min"], 40.0))
        d = details[0]
        for key in ("query", "f_time_ratio", "active_kcal", "steps", "duration_min", "cv", "per_pair"):
            self.assertIn(key, d)
        self.assertEqual(len(d["per_pair"]), 3)
        self.assertEqual(set(d["per_pair"][0]) >= {"pair_id", "duration_min", "active_kcal",
                                                   "steps", "modes"}, True)
        self.assertEqual(d["query"], decode_stub(X[0]))

    def test_no_route_penalty(self):
        ev = make_evaluator(self.pairs, self.baselines, StubClient({"edges": [], "routingErrors": []}),
                            decode_stub)
        F, cv, _ = ev(np.zeros((2, 12)))
        np.testing.assert_allclose(F[:, 0], 2.0)
        np.testing.assert_allclose(F[:, 1], 0.0)
        np.testing.assert_allclose(cv, 60.0)

    def test_missing_baseline_raises(self):
        with self.assertRaises(ValueError):
            make_evaluator(self.pairs, {}, StubClient({}), decode_stub)


class RoutingStub:
    """Fake client: callable decides the result per request; counts requests."""

    def __init__(self, fn):
        self.fn = fn
        self.requests = []

    def plan_many(self, requests):
        self.requests.extend(requests)
        return [self.fn(r) for r in requests]


WALK_ITIN = {"duration": 1080, "generalizedCost": 2000, "legs": [
    {"mode": "WALK", "duration": 1080, "distance": 1400}]}


class TestWalkFallback(unittest.TestCase):
    def setUp(self):
        with open(OD_PAIRS, encoding="utf-8") as f:
            self.pairs = json.load(f)["pairs"][:2]
        self.baselines = {p["id"]: 17.0 for p in self.pairs}
        self.short_id = self.pairs[0]["id"]

    def route(self, req):
        if req["modes"].get("directOnly"):
            return {"edges": [{"node": WALK_ITIN}], "routingErrors": []}
        if req["origin"] == self.pairs[0]["from"]:
            return {"edges": [], "routingErrors": [{"code": "WALKING_BETTER_THAN_TRANSIT"}]}
        return load_plan()

    def decode(self, x):
        return {"modes": {"transitOnly": True,
                          "transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}},
                "preferences": {"street": {"walk": {"speed": 1.4, "reluctance": 3.0}}}}

    def test_fallback_uses_walk_route(self):
        stub = RoutingStub(self.route)
        F, cv, details = make_evaluator(self.pairs, self.baselines, stub, self.decode)(np.zeros((1, 12)))
        pp = details[0]["per_pair"][0]
        self.assertEqual(pp["pair_id"], self.short_id)
        self.assertEqual(pp["fallback"], "walk")
        self.assertTrue(pp["found"])
        self.assertAlmostEqual(pp["duration_min"], 18.0)
        m = itinerary_metrics(WALK_ITIN)
        self.assertAlmostEqual(pp["active_kcal"], round(m["active_kcal"], 2))
        self.assertEqual(pp["steps"], round(m["steps"]))
        self.assertEqual(constraint_violation(18.0, 17.0), 0)
        self.assertIsNone(details[0]["per_pair"][1]["fallback"])
        # walk fallback keeps only the genome's walk speed
        fb_reqs = [r for r in stub.requests if r["modes"].get("directOnly")]
        self.assertEqual(len(fb_reqs), 1)
        self.assertEqual(fb_reqs[0]["preferences"], {"street": {"walk": {"speed": 1.4}}})
        # cv of the fallback pair is 0; the other pair is evaluated normally
        other = itinerary_metrics(pick_itinerary(load_plan()))
        self.assertAlmostEqual(cv[0], constraint_violation(other["duration_min"], 17.0) / 2)

    def test_other_errors_still_penalized(self):
        stub = RoutingStub(lambda r: {"edges": [], "routingErrors": [{"code": "NO_TRANSIT_CONNECTION"}]})
        F, cv, details = make_evaluator(self.pairs, self.baselines, stub, self.decode)(np.zeros((1, 12)))
        np.testing.assert_allclose(cv, 60.0)
        self.assertEqual(len(stub.requests), 2)  # no fallback queries


class TestClientDedupe(unittest.TestCase):
    def test_identical_requests_sent_once(self):
        plan = load_plan()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.jsonl")
            client = OTPClient(url="http://127.0.0.1:9/none", cache_path=path, workers=4)
            sent = []
            client._post = lambda payload: (sent.append(payload), {"data": {"planConnection": plan}})[1]
            with open(OD_PAIRS, encoding="utf-8") as f:
                pairs = json.load(f)["pairs"][:3]
            ev = make_evaluator(pairs, {p["id"]: 40.0 for p in pairs}, client, decode_stub)
            X = np.array([[0.3] * 12, [0.3] * 12, [0.9] * 12])  # two identical genomes
            F, cv, _ = ev(X)
            self.assertEqual(len(sent), 2 * 3)  # one call per unique query
            np.testing.assert_allclose(F[0], F[1])
            self.assertEqual(client.stats["misses"], 6)
            with open(path, encoding="utf-8") as f:
                lines = [json.loads(l)["key"] for l in f if l.strip()]
            self.assertEqual(len(lines), len(set(lines)))
            self.assertEqual(len(lines), 6)


class TestClientCache(unittest.TestCase):
    """Cache behaviour without network: pre-seeded JSONL is served as hits."""

    def test_cache_hit_from_disk(self):
        plan = load_plan()
        o = {"lat": 50.07, "lon": 20.03, "label": "A"}
        d = {"lat": 50.06, "lon": 19.92, "label": "B"}
        modes = {"direct": ["WALK"], "directOnly": True}
        payload = build_payload(o, d, modes, None)
        key = cache_key(payload)
        # key is order-independent
        reordered = {"variables": dict(reversed(list(payload["variables"].items()))),
                     "query": payload["query"]}
        self.assertEqual(key, cache_key(reordered))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "result": plan}) + "\n")
            client = OTPClient(url="http://127.0.0.1:9/none", cache_path=path, workers=2)
            res = client.plan_many([(o, d, modes, None), {"origin": o, "destination": d,
                                                         "modes": modes, "preferences": None}])
            self.assertEqual(res, [plan, plan])
            # identical requests are deduplicated -> a single cache lookup
            self.assertEqual(client.stats, {"hits": 1, "misses": 0, "errors": 0})


if __name__ == "__main__":
    unittest.main()
