"""Offline tests of the run_ga pipeline (variant, ticks, anchor, slider.json, profiles.json).

A fake OTP client is injected through run_ga.main(argv, client=...), so no OTP is needed.
The fake routes trade time for activity through walk.reluctance (lower reluctance -> longer
walk legs), add a bicycle leg when the query allows a bicycle, and answer
WALKING_BETTER_THAN_TRANSIT for the short pair, so the walking fallback is exercised.

Run:
    python3 -m unittest optimizer.tests.test_run_ga -v
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from optimizer import genome, run_ga, slider
from optimizer.evaluate import NO_ROUTE_PENALTY

PAIRS = {
    "meta": {"description": "fake pairs for test_run_ga"},
    "pairs": [
        {"id": "short", "from": {"lat": 50.0617, "lon": 19.9373, "label": "A"},
         "to": {"lat": 50.0663, "lon": 19.9232, "label": "B"}},
        {"id": "long", "from": {"lat": 50.0717, "lon": 20.0373, "label": "C"},
         "to": {"lat": 50.0663, "lon": 19.9232, "label": "B"}},
    ],
    "quick": ["short", "long"],
}
SHORT = PAIRS["pairs"][0]["from"]


def _itin(legs):
    dur = sum(l["duration"] for l in legs)
    return {"start": "2026-10-05T08:00:00+02:00", "end": "2026-10-05T08:30:00+02:00",
            "duration": dur, "generalizedCost": dur, "walkDistance": 0, "elevationGained": 0,
            "legs": legs}


def _ok(legs):
    return {"edges": [{"node": _itin(legs)}], "routingErrors": []}


class FakeClient:
    """OTPClient look-alike: plan_many, stats, arrive_by; records every request."""

    def __init__(self, no_routes=False):
        self.stats = {"hits": 0, "misses": 0, "errors": 0}
        self.arrive_by = "2026-10-05T08:30:00+02:00"
        self.requests = []
        self.no_routes = no_routes

    def plan_many(self, requests):
        self.requests.extend(requests)
        self.stats["misses"] += len(requests)
        return [self._plan(r) for r in requests]

    def _plan(self, r):
        modes = r.get("modes") or {}
        prefs = r.get("preferences") or {}
        if modes.get("directOnly"):  # BASELINE_WALK / walking fallback
            return _ok([{"mode": "WALK", "duration": 900, "distance": 1200}])
        short = r["origin"] == SHORT
        if short and modes.get("transitOnly"):
            return {"edges": [], "routingErrors": [{"code": "WALKING_BETTER_THAN_TRANSIT"}]}
        is_baseline = r.get("preferences") is None
        if self.no_routes and not is_baseline:
            return {"edges": [], "routingErrors": [{"code": "NO_TRANSIT_CONNECTION"}]}
        rel = ((prefs.get("street") or {}).get("walk") or {}).get("reluctance", 2.0)
        walk_s = round(1200.0 / rel)
        legs = [{"mode": "WALK", "duration": walk_s, "distance": walk_s * 1.33},
                {"mode": "TRAM", "duration": 900, "distance": 6000}]
        text = json.dumps(r.get("modes"))
        if "BICYCLE" in text:
            bike_rel = ((prefs.get("street") or {}).get("bicycle") or {}).get("reluctance", 2.0)
            legs.append({"mode": "BICYCLE", "duration": round(300 * bike_rel), "distance": 1500})
        if short:
            legs = legs[:1]  # direct WALK itinerary for the short pair
        return _ok(legs)


def _run(argv, client):
    log = io.StringIO()
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        rc = run_ga.main(argv, client=client)
    return rc, log.getvalue()


class _Base(unittest.TestCase):
    variant = "bike"
    extra = []
    no_routes = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="run_ga_test_")
        cls.out = os.path.join(cls.tmp, "out")
        pairs_path = os.path.join(cls.tmp, "pairs.json")
        with open(pairs_path, "w", encoding="utf-8") as f:
            json.dump(PAIRS, f)
        cls.client = FakeClient(no_routes=cls.no_routes)
        argv = ["--mode", "quick", "--seed", "3", "--pop", "10", "--gens", "3",
                "--variant", cls.variant, "--pairs", pairs_path, "--out", cls.out] + cls.extra
        cls.rc, cls.log = _run(argv, cls.client)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def load(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return json.load(f)


class TestWalkVariant(_Base):
    variant = "walk"

    def test_exit_and_files(self):
        self.assertEqual(self.rc, 0, self.log[-2000:])
        for name in ("front.json", "slider.json", "profiles.json", "front.svg", "front.md",
                     "checkpoint.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)

    def test_no_bicycle_anywhere(self):
        for name in ("front.json", "slider.json", "profiles.json", "checkpoint.json"):
            with open(os.path.join(self.out, name), encoding="utf-8") as f:
                self.assertNotIn("BICYCLE", f.read(), name)
        for p in self.load("front.json")["front"]:
            self.assertNotIn("bicycle", p["query"]["preferences"]["street"])
            for pp in p["per_pair"]:
                self.assertNotIn("BICYCLE", pp["modes"])
        # nothing sent to OTP asked for a bicycle either
        self.assertFalse(any("BICYCLE" in json.dumps(r.get("modes")) for r in self.client.requests))

    def test_meta(self):
        meta = self.load("front.json")["meta"]
        self.assertEqual(meta["variant"], "walk")
        self.assertEqual(meta["ticks"], 7)
        self.assertEqual(meta["dedupe_decimals"], 6)
        self.assertEqual(meta["slider"]["n"], 7)
        self.assertNotIn("access", meta["active_genes"])

    def test_slider_schema(self):
        doc = self.load("slider.json")
        m = doc["meta"]
        self.assertEqual(m["variant"], "walk")
        self.assertEqual(m["n"], 7)
        self.assertTrue(m["feasible_front"])
        self.assertEqual(len(doc["ticks"]), 7)
        self.assertEqual([t["s"] for t in doc["ticks"]], [i / 6 for i in range(7)])
        self.assertEqual(m["distinct"], len({t["index"] for t in doc["ticks"]}))
        self.assertEqual(self.load("front.json")["meta"]["slider"]["distinct"], m["distinct"])

    def test_tick_index_points_into_sorted_front(self):
        front = self.load("front.json")["front"]
        ordered = slider.sorted_front(front)
        for t in self.load("slider.json")["ticks"]:
            p = ordered[t["index"]]
            self.assertEqual(t["modes"], p["query"]["modes"])
            self.assertEqual(t["preferences"], p["query"]["preferences"])
            self.assertEqual(t["metrics"]["active_kcal"], p["active_kcal"])

    def test_profiles_match_extreme_ticks(self):
        prof = self.load("profiles.json")
        ticks = self.load("slider.json")["ticks"]
        for key, tick in (("fast", ticks[0]), ("active", ticks[-1])):
            self.assertEqual(prof[key]["modes"], tick["modes"], key)
            self.assertEqual(prof[key]["preferences"], tick["preferences"], key)
            self.assertEqual(prof[key]["metrics"]["f_time_ratio"], tick["metrics"]["f_time_ratio"])
            self.assertEqual(prof[key]["metrics"]["active_kcal"], tick["metrics"]["active_kcal"])

    def test_steps_grow_along_slider(self):
        ticks = self.load("slider.json")["ticks"]
        self.assertGreater(ticks[-1]["metrics"]["steps"], ticks[0]["metrics"]["steps"])

    def test_anchor_uses_walking_fallback(self):
        anchor = self.load("front.json")["meta"]["anchor"]
        self.assertIsNotNone(anchor)
        for k in ("f_time_ratio", "active_kcal", "steps", "duration_min", "cv", "per_pair",
                  "in_front"):
            self.assertIn(k, anchor)
        short = next(pp for pp in anchor["per_pair"] if pp["pair_id"] == "short")
        self.assertEqual(short["fallback"], "walk")
        self.assertTrue(short["found"])
        self.assertEqual(anchor["cv"], 0)
        self.assertIsInstance(anchor["in_front"], bool)

    def test_front_unique_objectives(self):
        front = self.load("front.json")["front"]
        keys = [(round(p["f_time_ratio"], 4), round(p["active_kcal"], 4)) for p in front]
        self.assertEqual(len(keys), len(set(keys)))

    def test_report_has_ticks(self):
        with open(os.path.join(self.out, "front.svg"), encoding="utf-8") as f:
            self.assertIn('class="tick"', f.read())


class TestBikeVariantAnchor(_Base):
    variant = "bike"

    def test_exit(self):
        self.assertEqual(self.rc, 0, self.log[-2000:])

    def test_anchor_seeded(self):
        """The first evaluated genome after the baselines is the anchor K1."""
        anchor_q = genome.decode(genome.encode_anchor("bike"), "bike")
        # baselines have preferences None; the first genome request is row 0 of the population
        first = next(r for r in self.client.requests if r.get("preferences") is not None)
        self.assertEqual(first["modes"], anchor_q["modes"])
        self.assertEqual(first["preferences"], anchor_q["preferences"])
        meta = self.load("front.json")["meta"]
        self.assertEqual(meta["variant"], "bike")
        self.assertIsNotNone(meta["anchor"])
        self.assertEqual(self.load("slider.json")["meta"]["variant"], "bike")

    def test_bike_can_use_bicycle(self):
        text = json.dumps([r.get("modes") for r in self.client.requests])
        self.assertIn("BICYCLE", text)

    def test_profiles_match_extreme_ticks(self):
        prof = self.load("profiles.json")
        ticks = self.load("slider.json")["ticks"]
        self.assertEqual(prof["fast"]["modes"], ticks[0]["modes"])
        self.assertEqual(prof["fast"]["preferences"], ticks[0]["preferences"])
        self.assertEqual(prof["active"]["modes"], ticks[-1]["modes"])
        self.assertEqual(prof["active"]["preferences"], ticks[-1]["preferences"])


class TestNoAnchorAndTicks(_Base):
    extra = ["--no-anchor", "--ticks", "5", "--no-report"]

    def test_no_anchor(self):
        self.assertEqual(self.rc, 0, self.log[-2000:])
        self.assertIsNone(self.load("front.json")["meta"].get("anchor"))

    def test_ticks(self):
        doc = self.load("slider.json")
        self.assertEqual(doc["meta"]["n"], 5)
        self.assertEqual(len(doc["ticks"]), 5)
        self.assertEqual(self.load("front.json")["meta"]["ticks"], 5)


class TestInfeasibleFront(_Base):
    """No genome finds a route: the front is infeasible, the slider is still written and flagged."""
    no_routes = True
    variant = "walk"

    def test_flagged(self):
        self.assertEqual(self.rc, 0, self.log[-2000:])
        front_doc = self.load("front.json")
        self.assertFalse(front_doc["meta"]["feasible_front"])
        self.assertTrue(all(p["cv"] > 0 for p in front_doc["front"]))
        doc = self.load("slider.json")
        self.assertFalse(doc["meta"]["feasible_front"])
        self.assertEqual(len(doc["ticks"]), 7)
        self.assertIn("slider.json built from an infeasible front", self.log)
        # The anchor gets the walking fallback on the short pair only; the long pair has no route.
        anchor = front_doc["meta"]["anchor"]
        long_pp = next(pp for pp in anchor["per_pair"] if pp["pair_id"] == "long")
        self.assertFalse(long_pp["found"])
        self.assertGreaterEqual(anchor["cv"], NO_ROUTE_PENALTY / 2)


class TestBuildSliderDoc(unittest.TestCase):
    def _p(self, t, k, cv=0.0):
        return {"query": {"modes": {"t": t}, "preferences": {}}, "f_time_ratio": t,
                "active_kcal": k, "steps": k, "duration_min": t, "cv": cv}

    def test_mixed_front_rejected(self):
        with self.assertRaises(ValueError):
            run_ga.build_slider_doc([self._p(1.0, 1), self._p(1.2, 5, cv=2.0)], {}, 7, "walk")

    def test_feasible_flag(self):
        doc = run_ga.build_slider_doc([self._p(1.0, 1), self._p(1.2, 5)], {}, 3, "walk")
        self.assertTrue(doc["meta"]["feasible_front"])
        self.assertEqual(doc["meta"]["variant"], "walk")


if __name__ == "__main__":
    unittest.main()
