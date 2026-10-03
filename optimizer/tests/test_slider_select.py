"""Offline tests for optimizer.slider_select (no OTP server needed)."""
import copy
import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from optimizer import slider_select as ss
from optimizer.evaluate import (BASELINE_TRANSIT, BASELINE_WALK, QUERY, OTPClient, build_payload,
                                cache_key)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "route_ticks_sample.json")
DROP_KEYS = {"late", "too_long", "no_route", "error", "duplicate", "dominated"}
O = {"lat": 50.0717, "lon": 20.0373, "label": "A"}
D = {"lat": 50.0663, "lon": 19.9232, "label": "B"}


def load():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class RecordingClient(OTPClient):
    """OTPClient whose plan() records calls instead of hitting the network."""

    def __init__(self):
        super().__init__(cache_path=None)
        self.calls = []

    def plan(self, origin, destination, modes, preferences=None):
        self.calls.append((origin, destination, modes, preferences))
        return {"edges": [], "routingErrors": []}


class TickRequestsTest(unittest.TestCase):
    def setUp(self):
        self.fx = load()
        self.slider = self.fx["slider"]

    def test_nine_requests_with_tags_in_order(self):
        reqs = ss.tick_requests(self.slider, O, D)
        self.assertEqual(len(reqs), 9)
        self.assertEqual([r["tag"] for r in reqs],
                         [f"tick:{i}" for i in range(7)] + ["anchor", "walk"])
        for i, r in enumerate(reqs[:7]):
            self.assertEqual(r["modes"], self.slider["ticks"][i]["modes"])
            self.assertEqual(r["preferences"], self.slider["ticks"][i]["preferences"])
            self.assertIs(r["origin"], O)
            self.assertIs(r["destination"], D)
        self.assertEqual(reqs[7]["modes"], BASELINE_TRANSIT["modes"])
        self.assertIsNone(reqs[7]["preferences"])
        self.assertEqual(reqs[8]["modes"], BASELINE_WALK["modes"])

    def test_without_anchor_and_walk(self):
        reqs = ss.tick_requests(self.slider, O, D, include_anchor=False, include_walk=False)
        self.assertEqual([r["tag"] for r in reqs], [f"tick:{i}" for i in range(7)])

    def test_speed_override_on_copy_only(self):
        before = copy.deepcopy(self.slider)
        transit_before = copy.deepcopy(BASELINE_TRANSIT)
        reqs = ss.tick_requests(self.slider, O, D, walk_speed=1.1, bike_speed=4.0)
        self.assertEqual(self.slider, before)
        self.assertEqual(BASELINE_TRANSIT, transit_before)
        for r in reqs:
            self.assertEqual(r["preferences"]["street"]["walk"]["speed"], 1.1)
        bike_ticks = [r for r in reqs[:7] if "bicycle" in r["preferences"]["street"]]
        self.assertTrue(bike_ticks)
        for r in bike_ticks:
            self.assertEqual(r["preferences"]["street"]["bicycle"]["speed"], 4.0)
        # the walk-only request gets no bicycle speed (cache key unaffected by bike_speed)
        self.assertNotIn("bicycle", reqs[8]["preferences"]["street"])
        # without overrides the tick preferences are untouched
        plain = ss.tick_requests(self.slider, O, D)
        self.assertEqual(plain[0]["preferences"], self.slider["ticks"][0]["preferences"])
        plain[0]["preferences"]["street"]["walk"]["speed"] = 9.9
        self.assertEqual(self.slider, before)

    def test_tag_ignored_by_plan_many_and_cache_key(self):
        reqs = ss.tick_requests(self.slider, O, D)
        client = RecordingClient()
        out = client.plan_many(reqs)
        self.assertEqual(len(out), len(reqs))
        # 7 distinct ticks + anchor + walk; tag is not forwarded to plan()
        self.assertEqual(len(client.calls), 9)
        for call in client.calls:
            self.assertEqual(len(call), 4)
        untagged = [{k: v for k, v in r.items() if k != "tag"} for r in reqs]
        for a, b in zip(reqs, untagged):
            ka = cache_key(build_payload(a["origin"], a["destination"], a["modes"], a["preferences"]))
            kb = cache_key(build_payload(b["origin"], b["destination"], b["modes"], b["preferences"]))
            self.assertEqual(ka, kb)

    def test_duplicate_ticks_sent_once(self):
        slider = copy.deepcopy(self.slider)
        slider["ticks"][1] = copy.deepcopy(slider["ticks"][0])
        reqs = ss.tick_requests(slider, O, D)
        client = RecordingClient()
        client.plan_many(reqs)
        self.assertEqual(len(client.calls), 8)

    def test_query_arrive_by(self):
        self.assertEqual(ss.query_arrive_by("2026-10-05T08:30:00+02:00", 3.0),
                         "2026-10-05T08:27:00+02:00")
        with self.assertRaises(ValueError):
            ss.query_arrive_by("2026-10-05T08:30:00")


class BuildRouteSliderSyntheticTest(unittest.TestCase):
    def setUp(self):
        self.syn = load()["synthetic"]
        self.deadline = self.syn["deadline"]

    def build(self, named, **kw):
        """named: list of (tag, synthetic case name)."""
        reqs = [{"tag": t} for t, _ in named]
        res = [copy.deepcopy(self.syn[n]) for _, n in named]
        return ss.build_route_slider(res, reqs, kw.pop("deadline", self.deadline), **kw)

    def test_late_two_minutes_before_deadline(self):
        rs = self.build([("anchor", "anchor_42"), ("tick:0", "late_2min")])
        self.assertEqual(rs["dropped"]["late"], 1)
        self.assertEqual([p["sources"] for p in rs["positions"]], [["anchor"]])
        # with a 1-minute buffer the same route is accepted
        rs1 = self.build([("anchor", "anchor_42"), ("tick:0", "late_2min")], buffer_min=1.0)
        self.assertEqual(rs1["dropped"]["late"], 0)

    def test_too_long_vs_baseline(self):
        rs = self.build([("anchor", "anchor_42"), ("tick:0", "too_long_110")])
        self.assertEqual(rs["baseline_min"], 42.0)
        self.assertEqual(rs["dropped"]["too_long"], 1)
        self.assertEqual(len(rs["positions"]), 1)
        # explicit baseline_min overrides the anchor
        rs2 = self.build([("tick:0", "too_long_110")], baseline_min=42.0)
        self.assertEqual(rs2["dropped"]["too_long"], 1)
        self.assertEqual(rs2["positions"], [])

    def test_baseline_falls_back_to_walk(self):
        rs = self.build([("anchor", "no_route"), ("walk", "anchor_42"), ("tick:0", "too_long_110")])
        self.assertEqual(rs["baseline_min"], 42.0)
        self.assertEqual(rs["dropped"]["too_long"], 1)
        self.assertEqual(rs["dropped"]["no_route"], 1)

    def test_three_ticks_same_route_merge(self):
        rs = self.build([("tick:0", "bike_tram_44"), ("tick:1", "bike_tram_44"),
                         ("tick:2", "bike_tram_44"), ("anchor", "anchor_42")])
        self.assertEqual(rs["dropped"]["duplicate"], 2)
        merged = [p for p in rs["positions"] if len(p["sources"]) == 3]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["sources"], ["tick:0", "tick:1", "tick:2"])
        self.assertEqual(len(rs["positions"]), 2)

    def test_signature_tolerates_small_differences(self):
        a = self.syn["bike_tram_44"]["edges"][0]["node"]
        b = copy.deepcopy(a)
        b["legs"][0]["duration"] += 5  # same 30 s bucket
        b["legs"][0]["distance"] += 10  # same 50 m bucket
        self.assertEqual(ss.route_signature(a), ss.route_signature(b))
        c = copy.deepcopy(a)
        c["legs"][1]["route"] = {"shortName": "4"}
        self.assertNotEqual(ss.route_signature(a), ss.route_signature(c))

    def test_positions_sorted_and_dominated_dropped(self):
        rs = self.build([("tick:0", "bike_50"), ("tick:1", "slow_transit_48"),
                         ("tick:2", "bike_tram_44"), ("anchor", "anchor_42"),
                         ("walk", "no_route")])
        pos = rs["positions"]
        self.assertEqual([p["sources"][0] for p in pos], ["anchor", "tick:2", "tick:0"])
        self.assertEqual(rs["dropped"]["dominated"], 1)  # slow_transit_48
        durs = [p["metrics"]["duration_min"] for p in pos]
        kcal = [p["metrics"]["active_kcal"] for p in pos]
        s = [p["s"] for p in pos]
        self.assertEqual(durs, sorted(durs))
        self.assertEqual(kcal, sorted(kcal))
        self.assertEqual(s, sorted(s))
        self.assertEqual(s[0], 0.0)
        self.assertEqual(s[-1], 1.0)
        m = pos[0]["metrics"]
        self.assertEqual(set(m), {"duration_min", "active_kcal", "steps", "end", "slack_min", "modes"})
        self.assertEqual(m["slack_min"], 3.0)
        self.assertEqual(m["modes"], ["WALK", "TRAM", "WALK"])
        self.assertIn("legs", pos[0]["itinerary"])

    def test_lock_and_default_index(self):
        named = [("tick:0", "bike_50"), ("tick:2", "bike_tram_44"), ("anchor", "anchor_42")]
        free = self.build(named)
        self.assertFalse(any(p["locked"] for p in free["positions"]))
        self.assertIsNone(free["lock_reason"])
        locked = self.build(named, lock_reason="smog")
        self.assertEqual(locked["lock_reason"], "smog")
        for p in locked["positions"]:
            self.assertEqual(p["locked"], p["s"] > 0.5)
        self.assertTrue(any(p["locked"] for p in locked["positions"]))
        di = locked["default_index"]
        self.assertIsNotNone(di)
        self.assertFalse(locked["positions"][di]["locked"])
        # default = unlocked position with s closest to 0.5
        unlocked = [i for i, p in enumerate(free["positions"])]
        best = min(unlocked, key=lambda i: abs(free["positions"][i]["s"] - 0.5))
        self.assertEqual(free["default_index"], best)

    def test_only_rejections(self):
        rs = self.build([("tick:0", "late_2min"), ("tick:1", "too_long_110"),
                         ("tick:2", "no_route"), ("tick:3", "error")], baseline_min=42.0)
        self.assertEqual(rs["positions"], [])
        self.assertIsNone(rs["default_index"])
        self.assertEqual(set(rs["dropped"]), DROP_KEYS)
        self.assertEqual(rs["dropped"], {"late": 1, "too_long": 1, "no_route": 1, "error": 1,
                                         "duplicate": 0, "dominated": 0})
        empty = ss.build_route_slider([], [], self.deadline)
        self.assertEqual(empty["positions"], [])
        self.assertEqual(set(empty["dropped"]), DROP_KEYS)
        self.assertIsNone(empty["baseline_min"])

    def test_deadline_datetime_equals_iso(self):
        named = [("tick:0", "bike_50"), ("anchor", "anchor_42")]
        dt = datetime.datetime.fromisoformat(self.deadline)
        self.assertEqual(self.build(named), self.build(named, deadline=dt))
        with self.assertRaises(ValueError):
            self.build(named, deadline="2026-10-05T08:30:00")

    def test_single_position(self):
        rs = self.build([("anchor", "anchor_42")])
        self.assertEqual([p["s"] for p in rs["positions"]], [0.0])
        self.assertEqual(rs["default_index"], 0)
        self.assertFalse(self.build([("anchor", "anchor_42")], lock_reason="smog")
                         ["positions"][0]["locked"])


def sources_total(rs):
    return sum(len(p["sources"]) for p in rs["positions"]) + sum(rs["dropped"].values())


def fast_bus_40():
    """Synthetic 40-min bus route with almost no walking (faster but less active than anchor_42)."""
    it = {"start": "2026-10-05T07:46:00+02:00", "end": "2026-10-05T08:26:00+02:00",
          "duration": 2400, "generalizedCost": 3000, "walkDistance": 80.0, "elevationGained": 0.0,
          "legs": [{"mode": "WALK", "duration": 60.0, "distance": 80.0},
                   {"mode": "BUS", "duration": 2340.0, "distance": 12000.0, "route": {"shortName": "502"}}]}
    return {"routingErrors": [], "edges": [{"node": it}]}


class LockFallbackTest(BuildRouteSliderSyntheticTest):
    """Smog / weather lock: plain-transit route always offered and default."""

    def test_dominated_anchor_becomes_fallback(self):
        named = [("tick:0", "bike_tram_44"), ("tick:1", "bike_50"), ("anchor", "slow_transit_48")]
        free = self.build(named)
        self.assertEqual(len(free["positions"]), 2)
        self.assertEqual(free["dropped"]["dominated"], 1)
        self.assertFalse(any(p["fallback"] for p in free["positions"]))

        rs = self.build(named, lock_reason="smog")
        pos = rs["positions"]
        self.assertEqual(len(pos), 3)
        self.assertTrue(pos[0]["fallback"])
        self.assertEqual(pos[0]["sources"], ["anchor"])
        self.assertEqual(pos[0]["s"], 0.0)
        self.assertFalse(pos[0]["locked"])
        self.assertEqual(rs["default_index"], 0)
        self.assertEqual(rs["dropped"]["dominated"], 0)
        self.assertEqual(sources_total(rs), len(named))
        s = [p["s"] for p in pos]
        self.assertEqual(s, sorted(s))
        self.assertEqual(len(set(s)), len(s))
        self.assertEqual(s[-1], 1.0)
        for p in pos[1:]:
            self.assertFalse(p["fallback"])
            self.assertEqual(p["locked"], p["s"] > 0.5)
        # active but allowed position stays selectable (not locked), yet is not the default
        allowed = [i for i, p in enumerate(pos) if not p["locked"] and p["metrics"]["active_kcal"] > 0
                   and not p["fallback"]]
        self.assertTrue(allowed)
        self.assertNotIn(rs["default_index"], allowed)

    def test_anchor_on_active_end_moved_to_fallback(self):
        reqs = [{"tag": "tick:0"}, {"tag": "anchor"}]
        res = [fast_bus_40(), copy.deepcopy(self.syn["anchor_42"])]
        free = ss.build_route_slider(res, reqs, self.deadline)
        self.assertEqual([p["sources"] for p in free["positions"]], [["tick:0"], ["anchor"]])
        self.assertEqual(free["positions"][1]["s"], 1.0)
        rs = ss.build_route_slider(res, reqs, self.deadline, lock_reason="smog")
        pos = rs["positions"]
        self.assertEqual([p["sources"] for p in pos], [["anchor"], ["tick:0"]])
        self.assertTrue(pos[0]["fallback"])
        self.assertEqual([p["s"] for p in pos], [0.0, 0.5])
        self.assertEqual([p["locked"] for p in pos], [False, False])
        self.assertEqual(rs["default_index"], 0)
        self.assertEqual(sources_total(rs), 2)

    def test_anchor_in_front_is_default(self):
        named = [("anchor", "anchor_42"), ("tick:2", "bike_tram_44"), ("tick:0", "bike_50")]
        rs = self.build(named, lock_reason="smog")
        pos = rs["positions"]
        self.assertFalse(any(p["fallback"] for p in pos))
        self.assertEqual(pos[rs["default_index"]]["sources"], ["anchor"])
        for p in pos:
            self.assertEqual(p["locked"], p["s"] > 0.5)

    def test_lock_without_anchor_route(self):
        named = [("tick:0", "bike_tram_44"), ("tick:1", "bike_50"), ("anchor", "late_2min")]
        rs = self.build(named, lock_reason="smog", baseline_min=42.0)
        pos = rs["positions"]
        self.assertFalse(any(p["fallback"] for p in pos))
        di = rs["default_index"]
        self.assertFalse(pos[di]["locked"])
        self.assertEqual(pos[di]["sources"], ["tick:0"])  # least active unlocked
        self.assertTrue(any("anchor" in w for w in rs["warnings"]))


def walk_60(syn):
    """Pure walking itinerary of 60 min (ratio 1.43 vs a 42 min baseline, ends before the limit)."""
    res = copy.deepcopy(syn["too_long_110"])
    it = res["edges"][0]["node"]
    it["duration"] = 3600
    it["legs"][0]["duration"] = 3600.0
    return res


def walky_transit_45(syn):
    """45 min WALK+TRAM+WALK with much walking: > bike_tram_44 kcal, more than bike_tram_44 (~139)."""
    res = copy.deepcopy(syn["anchor_42"])
    it = res["edges"][0]["node"]
    it["duration"] = 2700
    it["end"] = "2026-10-05T08:26:00+02:00"
    it["start"] = "2026-10-05T07:41:00+02:00"
    it["legs"][0]["duration"], it["legs"][1]["duration"], it["legs"][2]["duration"] = 1500.0, 300.0, 900.0
    it["legs"][0]["distance"], it["legs"][2]["distance"] = 1500.0, 1000.0
    return res


class LockDefaultWithoutAnchorTest(BuildRouteSliderSyntheticTest):
    """Lock without a usable anchor: walk > non-bike position > any unlocked position."""

    def run_lock(self, results, tags, **kw):
        reqs = [{"tag": t} for t in tags]
        rs = ss.build_route_slider(results, reqs, self.deadline, lock_reason="smog",
                                   baseline_min=42.0, **kw)
        self.assertEqual(sources_total(rs), len(reqs))
        return rs

    def check_scale(self, rs):
        s = [p["s"] for p in rs["positions"]]
        self.assertEqual(s, sorted(s))
        self.assertEqual(len(set(s)), len(s))

    def test_walk_is_default_not_bike(self):
        # anchor late, walk available alongside bike routes -> walk (not bike) is the default
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["bike_50"]),
               copy.deepcopy(self.syn["late_2min"]), walk_60(self.syn)]
        rs = self.run_lock(res, ["tick:0", "tick:1", "anchor", "walk"])
        pos = rs["positions"]
        di = rs["default_index"]
        self.assertEqual(pos[di]["sources"], ["walk"])
        self.assertEqual(pos[di]["metrics"]["modes"], ["WALK"])
        self.assertEqual(pos[di]["s"], 0.0)
        self.assertFalse(pos[di]["locked"])
        self.assertTrue(pos[di]["fallback"] or di == 0)
        self.assertEqual(rs["dropped"]["late"], 1)
        self.assertTrue(any("spacer" in w for w in rs["warnings"]))
        self.check_scale(rs)
        for p in pos:
            if "walk" not in p["sources"]:
                self.assertEqual(p["locked"], p["s"] > 0.5)

    def test_walk_fallback_not_double_counted(self):
        # walk dominated by the bike route (more kcal, faster) -> resurrected as fallback
        res = [copy.deepcopy(self.syn["bike_50"]), walk_60(self.syn)]
        rs = self.run_lock(res, ["tick:0", "walk"])
        pos = rs["positions"]
        self.assertTrue(pos[0]["fallback"])
        self.assertEqual(pos[0]["sources"], ["walk"])
        self.assertEqual(rs["default_index"], 0)
        self.assertEqual(rs["dropped"]["dominated"], 0)
        self.check_scale(rs)

    def test_walk_too_long_falls_through(self):
        # 110 min walk is over 190% of the baseline -> not offered; non-bike position wins
        res = [copy.deepcopy(self.syn["bike_50"]), copy.deepcopy(self.syn["slow_transit_48"]),
               copy.deepcopy(self.syn["too_long_110"])]
        rs = self.run_lock(res, ["tick:0", "tick:1", "walk"])
        di = rs["default_index"]
        self.assertEqual(rs["positions"][di]["sources"], ["tick:1"])
        self.assertNotIn("BICYCLE", rs["positions"][di]["metrics"]["modes"])
        self.assertTrue(any("bez roweru" in w for w in rs["warnings"]))

    def test_no_anchor_prefers_non_bike_over_less_active_bike(self):
        # a walking+tram position must beat a less active bike+tram position
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["bike_50"]),
               walky_transit_45(self.syn)]
        rs = self.run_lock(res, ["tick:0", "tick:1", "tick:2"])
        di = rs["default_index"]
        pos = rs["positions"]
        self.assertEqual(pos[di]["sources"], ["tick:2"])
        # the bike position has lower kcal, so only the BICYCLE filter explains the choice
        self.assertLess(pos[0]["metrics"]["active_kcal"], pos[di]["metrics"]["active_kcal"])
        self.assertFalse(pos[di]["locked"])
        self.assertNotIn("BICYCLE", rs["positions"][di]["metrics"]["modes"])
        self.assertTrue(any("bez roweru" in w for w in rs["warnings"]))
        self.check_scale(rs)

    def test_only_bike_positions(self):
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["bike_50"])]
        rs = self.run_lock(res, ["tick:0", "tick:1"])
        pos = rs["positions"]
        di = rs["default_index"]
        self.assertFalse(pos[di]["locked"])
        free = [p for p in pos if not p["locked"]]
        self.assertEqual(pos[di]["metrics"]["active_kcal"],
                         min(p["metrics"]["active_kcal"] for p in free))
        self.assertTrue(any("brak dostępnej pozycji bez roweru" in w for w in rs["warnings"]))

    def test_anchor_regression_wins_over_walk(self):
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["anchor_42"]),
               walk_60(self.syn)]
        rs = self.run_lock(res, ["tick:0", "anchor", "walk"])
        self.assertEqual(rs["positions"][rs["default_index"]]["sources"], ["anchor"])
        self.assertFalse(any("spacer" in w for w in rs["warnings"]))

    def test_no_lock_unchanged(self):
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["bike_50"]),
               copy.deepcopy(self.syn["anchor_42"]), walk_60(self.syn)]
        reqs = [{"tag": t} for t in ("tick:0", "tick:1", "anchor", "walk")]
        rs = ss.build_route_slider(res, reqs, self.deadline, baseline_min=42.0)
        pos = rs["positions"]
        self.assertFalse(any(p["fallback"] or p["locked"] for p in pos))
        best = min(range(len(pos)), key=lambda i: abs(pos[i]["s"] - 0.5))
        self.assertEqual(rs["default_index"], best)
        self.assertEqual(sources_total(rs), len(reqs))


class AnchorFastestTest(BuildRouteSliderSyntheticTest):
    """anchor / walk take the fastest itinerary, ticks the min-generalizedCost one."""

    def two_itins(self):
        slow = copy.deepcopy(self.syn["slow_transit_48"]["edges"][0]["node"])  # 48 min
        fast = copy.deepcopy(self.syn["anchor_42"]["edges"][0]["node"])
        fast["duration"] = 2430  # 40.5 min
        fast["legs"][1]["duration"] = 1710.0
        fast["start"] = "2026-10-05T07:46:30+02:00"
        slow["generalizedCost"], fast["generalizedCost"] = 3000, 4000
        return {"routingErrors": [], "edges": [{"node": slow}, {"node": fast}]}

    def test_anchor_takes_fastest(self):
        res = self.two_itins()
        rs = ss.build_route_slider([res], [{"tag": "anchor"}], self.deadline)
        self.assertEqual(rs["positions"][0]["metrics"]["duration_min"], 40.5)
        rs = ss.build_route_slider([copy.deepcopy(res)], [{"tag": "walk"}], self.deadline)
        self.assertEqual(rs["positions"][0]["metrics"]["duration_min"], 40.5)

    def test_tick_takes_min_generalized_cost(self):
        rs = ss.build_route_slider([self.two_itins()], [{"tag": "tick:0"}], self.deadline)
        self.assertEqual(rs["positions"][0]["metrics"]["duration_min"], 48.0)

    def test_fallback_uses_fastest_anchor(self):
        reqs = [{"tag": "tick:0"}, {"tag": "tick:1"}, {"tag": "anchor"}]
        res = [copy.deepcopy(self.syn["bike_tram_44"]), copy.deepcopy(self.syn["bike_50"]),
               self.two_itins()]
        rs = ss.build_route_slider(res, reqs, self.deadline, lock_reason="smog")
        self.assertEqual(rs["positions"][rs["default_index"]]["sources"], ["anchor"])
        self.assertEqual(rs["positions"][rs["default_index"]]["metrics"]["duration_min"], 40.5)
        # anchor (40.5 min, 49 kcal walking) is now non-dominated -> regular position, sorted by time
        self.assertFalse(any(p["fallback"] for p in rs["positions"]))
        durs = [p["metrics"]["duration_min"] for p in rs["positions"]]
        self.assertEqual(durs, sorted(durs))


class DiagnosticsTest(BuildRouteSliderSyntheticTest):
    def test_all_errors(self):
        rs = self.build([("tick:0", "error"), ("anchor", "error"), ("walk", "error")])
        self.assertEqual(rs["dropped"]["error"], 3)
        self.assertEqual(rs["dropped"]["no_route"], 0)
        self.assertEqual(rs["positions"], [])
        self.assertTrue(any("OTP niedostępny" in w for w in rs["warnings"]))

    def test_partial_errors(self):
        rs = self.build([("tick:0", "error"), ("anchor", "anchor_42")])
        self.assertEqual(rs["dropped"]["error"], 1)
        self.assertTrue(any("1/2" in w for w in rs["warnings"]))
        self.assertFalse(any("niedostępny" in w for w in rs["warnings"]))

    def test_all_late_inside_buffer_hints_query_arrive_by(self):
        rs = self.build([("tick:0", "late_2min"), ("tick:1", "late_2min")], baseline_min=42.0)
        self.assertEqual(rs["dropped"]["late"], 2)
        self.assertTrue(any("query_arrive_by" in w for w in rs["warnings"]))
        # routes ending after the deadline itself -> no hint about query_arrive_by
        rs2 = self.build([("tick:0", "late_2min")], baseline_min=42.0,
                         deadline="2026-10-05T08:20:00+02:00")
        self.assertEqual(rs2["dropped"]["late"], 1)
        self.assertFalse(any("query_arrive_by" in w for w in rs2["warnings"]))
        self.assertTrue(rs2["warnings"])

    def test_no_warnings_on_clean_input(self):
        rs = self.build([("anchor", "anchor_42"), ("tick:0", "bike_50")])
        self.assertEqual(rs["warnings"], [])

    def test_no_baseline_warning(self):
        rs = self.build([("tick:0", "bike_50")])
        self.assertIsNone(rs["baseline_min"])
        self.assertTrue(any("baseline" in w for w in rs["warnings"]))


class RouteQueryTest(unittest.TestCase):
    def test_route_query_fields(self):
        for field in ("legGeometry { points }", "route { shortName }", "from { name lat lon }",
                      "to { name lat lon }", "estimated { time delay }", "realTime",
                      "generalizedCost", "latestArrival"):
            self.assertIn(field, ss.ROUTE_QUERY)

    def test_default_query_unchanged_for_ga(self):
        c = OTPClient(cache_path=None)
        self.assertIs(c.query, QUERY)
        self.assertEqual(build_payload(O, D, None, None)["query"], QUERY)
        k_ga = cache_key(build_payload(O, D, None, None))
        k_ui = cache_key(build_payload(O, D, None, None, query=ss.ROUTE_QUERY))
        self.assertNotEqual(k_ga, k_ui)

    def test_client_uses_query_in_payload(self):
        c = OTPClient(cache_path=None, query=ss.ROUTE_QUERY)
        sent = []
        c._post = lambda payload: (sent.append(payload) or
                                   {"data": {"planConnection": {"edges": [], "routingErrors": []}}})
        c.plan(O, D, None, None)
        self.assertEqual(sent[0]["query"], ss.ROUTE_QUERY)


class FixtureClient:
    """plan_many returns the fixture answers; records requests."""

    def __init__(self, results):
        self.results = results
        self.stats = {"hits": 0, "misses": len(results), "errors": 0}
        self.seen = None

    def plan_many(self, requests):
        self.seen = requests
        return copy.deepcopy(self.results)


class PlanRouteSliderTest(unittest.TestCase):
    def setUp(self):
        self.fx = load()
        r0 = self.fx["requests"][0]
        self.o, self.d = r0["origin"], r0["destination"]

    def test_with_injected_client(self):
        fx = self.fx
        client = FixtureClient(fx["results"])
        rs = ss.plan_route_slider(fx["slider"], self.o, self.d, fx["deadline"], client=client,
                                  lock_reason="smog")
        self.assertEqual(client.seen, fx["requests"])
        self.assertEqual(rs["n_requests"], 9)
        self.assertEqual(rs["otp_stats"], client.stats)
        want = ss.build_route_slider(fx["results"], fx["requests"], fx["deadline"], lock_reason="smog")
        for k in want:
            self.assertEqual(rs[k], want[k])
        self.assertFalse(rs["positions"][rs["default_index"]]["locked"])
        self.assertIn("anchor", rs["positions"][rs["default_index"]]["sources"])

    def test_builds_client_with_route_query_and_buffered_arrival(self):
        fx = self.fx
        captured = {}

        def fake_client(*args, **kw):
            captured["args"], captured["kw"] = args, kw
            return FixtureClient(fx["results"])

        with mock.patch.object(ss, "OTPClient", side_effect=fake_client):
            ss.plan_route_slider(fx["slider"], self.o, self.d, "2026-10-05T08:30:00+02:00",
                                 url="http://otp.example/otp/gtfs/v1", buffer_min=5.0, workers=3)
        kw = captured["kw"]
        self.assertEqual(captured["args"], ("http://otp.example/otp/gtfs/v1",))
        self.assertIs(kw["query"], ss.ROUTE_QUERY)
        self.assertEqual(kw["arrive_by"], "2026-10-05T08:25:00+02:00")
        self.assertIsNone(kw["cache_path"])
        self.assertEqual(kw["workers"], 3)


class CliExitTest(unittest.TestCase):
    def test_exit_2_when_otp_unreachable(self):
        fx = load()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "slider.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(fx["slider"], f)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = ss.main(["--slider", path, "--pair", "nowa_huta_agh",
                                "--url", "http://127.0.0.1:9/otp/gtfs/v1", "--workers", "4"])
        self.assertEqual(code, 2)
        self.assertIn("OTP niedostępny", buf.getvalue())


class BuildRouteSliderRealTest(unittest.TestCase):
    """Real OTP answers for nowa_huta_agh (fixture)."""

    def setUp(self):
        self.fx = load()

    def test_real_answers(self):
        fx = self.fx
        rs = ss.build_route_slider(fx["results"], fx["requests"], fx["deadline"])
        pos = rs["positions"]
        self.assertGreaterEqual(len(pos), 1)
        self.assertIsNotNone(rs["baseline_min"])
        self.assertEqual(set(rs["dropped"]), DROP_KEYS)
        self.assertEqual(sources_total(rs), len(fx["requests"]))
        self.assertEqual(rs["warnings"], [])
        # ROUTE_QUERY fields: every leg drawable on the map, transit legs carry line numbers
        for p in pos:
            for leg in p["itinerary"]["legs"]:
                self.assertTrue(leg["legGeometry"]["points"])
                self.assertIn("lat", leg["from"])
                if leg["mode"] in ("TRAM", "BUS"):
                    self.assertTrue(leg["route"]["shortName"])
        anchor_it = ss.pick_itinerary(fx["results"][fx["requests"].index(
            next(r for r in fx["requests"] if r["tag"] == "anchor"))])
        sig = ss.route_signature(anchor_it)
        self.assertTrue(any(len(part) == 4 for part in sig))  # line number in the signature
        self.assertEqual([p["s"] for p in pos], sorted(p["s"] for p in pos))
        self.assertEqual(pos[0]["s"], 0.0)
        if len(pos) > 1:
            self.assertEqual(pos[-1]["s"], 1.0)
        kcal = [p["metrics"]["active_kcal"] for p in pos]
        self.assertEqual(kcal, sorted(kcal))
        for p in pos:
            self.assertGreaterEqual(p["metrics"]["slack_min"], 3.0)
        json.dumps(rs)  # JSON-serializable for the backend

    def test_real_answers_with_lock(self):
        fx = self.fx
        rs = ss.build_route_slider(fx["results"], fx["requests"], fx["deadline"], lock_reason="smog")
        for p in rs["positions"]:
            self.assertEqual(p["locked"], p["s"] > 0.5)
        self.assertFalse(rs["positions"][rs["default_index"]]["locked"])

    def test_requests_in_fixture_match_tick_requests(self):
        fx = self.fx
        p = fx["requests"][0]
        self.assertEqual(ss.tick_requests(fx["slider"], p["origin"], p["destination"]),
                         fx["requests"])


class ArcPositionsTest(unittest.TestCase):
    def test_local_basic(self):
        pts = [{"f_time_ratio": 1.0, "active_kcal": 0.0}, {"f_time_ratio": 1.5, "active_kcal": 50.0},
               {"f_time_ratio": 2.0, "active_kcal": 100.0}]
        self.assertEqual([round(v, 9) for v in ss._arc_positions_local(pts)], [0.0, 0.5, 1.0])
        self.assertEqual(ss._arc_positions_local(pts[:1]), [0.0])
        self.assertEqual(ss._arc_positions_local([]), [])

    def test_matches_slider_module(self):
        try:
            from optimizer.slider import arc_positions
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"optimizer.slider.arc_positions not available: {e}")
        cases = [
            [{"f_time_ratio": 1.0, "active_kcal": 0.0}, {"f_time_ratio": 1.5, "active_kcal": 50.0},
             {"f_time_ratio": 2.0, "active_kcal": 100.0}],
            [{"f_time_ratio": 1.0, "active_kcal": 22.0}, {"f_time_ratio": 1.03, "active_kcal": 38.0},
             {"f_time_ratio": 1.12, "active_kcal": 104.0}, {"f_time_ratio": 1.31, "active_kcal": 192.0},
             {"f_time_ratio": 1.58, "active_kcal": 246.0}],
            [{"f_time_ratio": 1.2, "active_kcal": 10.0}],
        ]
        for pts in cases:
            got = [float(v) for v in arc_positions(pts)]
            want = ss._arc_positions_local(pts)
            self.assertEqual(len(got), len(want))
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=9)


class CliTest(unittest.TestCase):
    def test_print_table(self):
        fx = load()
        rs = ss.build_route_slider(fx["results"], fx["requests"], fx["deadline"], lock_reason="smog")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ss.print_route_slider(rs)
        out = buf.getvalue()
        self.assertIn("kcal", out)
        self.assertEqual(len(out.strip().splitlines()), 2 + len(rs["positions"]))


if __name__ == "__main__":
    unittest.main()
