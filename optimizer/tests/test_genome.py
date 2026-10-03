"""Tests for optimizer.genome (no OTP needed)."""
import json
import unittest

import numpy as np

from optimizer import genome
from optimizer.genome import FIXED_BIKE_SPEED, FIXED_WALK_SPEED, DIM, GENES, IDX, clip, decode, describe, random_genome
from optimizer.genome import (ANCHOR_VALUES, VARIANTS, active_mask, canonical, encode_anchor)


def flat(d):
    """All leaf values of a decoded dict, as (path, value)."""
    if isinstance(d, dict):
        for k, v in d.items():
            for p, leaf in flat(v):
                yield (f"{k}.{p}" if p else k), leaf
    elif isinstance(d, list):
        for i, v in enumerate(d):
            for p, leaf in flat(v):
                yield (f"{i}.{p}" if p else str(i)), leaf
    else:
        yield "", d


def scalars(q):
    p, m = q["preferences"], q["modes"]
    return {
        "walk.reluctance": p["street"]["walk"]["reluctance"],
        "bicycle.reluctance": p["street"]["bicycle"]["reluctance"],
        "transit.board.waitReluctance": p["transit"]["board"]["waitReluctance"],
        "transit.transfer.cost": p["transit"]["transfer"]["cost"],
        "BUS.cost.reluctance": next(t for t in m["transit"]["transit"]
                                    if t["mode"] == "BUS")["cost"]["reluctance"],
    }


class GenomeTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(123)
        self.genomes = [random_genome(rng) for _ in range(1000)]
        self.decoded = [decode(x) for x in self.genomes]

    def test_genes_table(self):
        self.assertEqual(DIM, 12)
        self.assertEqual(len(GENES), DIM)
        for g in GENES:
            self.assertTrue({"name", "type", "scale"} <= g.keys())

    def test_random_genome_shape(self):
        x = random_genome(np.random.default_rng(0))
        self.assertEqual(x.shape, (DIM,))
        self.assertTrue(((x >= 0) & (x <= 1)).all())

    def test_clip(self):
        np.testing.assert_array_equal(clip(np.array([-1.0, 0.5, 2.0])), [0.0, 0.5, 1.0])

    def test_decode_structure_json(self):
        for q in self.decoded[:50]:
            self.assertEqual(set(q), {"modes", "preferences"})
            json.loads(json.dumps(q))  # serializable, plain types
            for path, leaf in flat(q):
                self.assertIsInstance(leaf, (bool, int, float, str), path)
            self.assertEqual(set(q["preferences"]), {"street", "transit"})
            self.assertEqual(set(q["preferences"]["street"]["bicycle"]["optimization"]),
                             {"triangle"})

    def test_triangle_sums_to_one(self):
        for q in self.decoded:
            t = q["preferences"]["street"]["bicycle"]["optimization"]["triangle"]
            self.assertEqual(set(t), {"safety", "flatness", "time"})
            self.assertAlmostEqual(sum(t.values()), 1.0, delta=1e-9)
            for v in t.values():
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)

    def test_triangle_all_zero(self):
        x = np.full(DIM, 0.5)
        x[IDX["bicycle.triangle.safety"]:IDX["bicycle.triangle.time"] + 1] = 0.0
        t = decode(x)["preferences"]["street"]["bicycle"]["optimization"]["triangle"]
        self.assertAlmostEqual(sum(t.values()), 1.0, delta=1e-9)
        self.assertTrue(all(abs(v - 1 / 3) < 0.002 for v in t.values()))

    def test_values_in_range(self):
        ranges = {g["name"]: g["range"] for g in GENES if g["type"] in ("float", "int")}
        for q in self.decoded:
            for name, v in scalars(q).items():
                lo, hi = ranges[name]
                self.assertGreaterEqual(v, lo, name)
                self.assertLessEqual(v, hi, name)
            self.assertIsInstance(q["preferences"]["transit"]["transfer"]["cost"], int)

    def test_boundaries(self):
        lo = scalars(decode(np.zeros(DIM)))
        hi = scalars(decode(np.ones(DIM)))
        for g in GENES:
            if g["type"] in ("float", "int") and g["name"] not in genome.WALK_ONLY_GENES:
                self.assertAlmostEqual(lo[g["name"]], g["range"][0], places=9, msg=g["name"])
                self.assertAlmostEqual(hi[g["name"]], g["range"][1], places=9, msg=g["name"])
        m0, m1 = decode(np.zeros(DIM))["modes"], decode(np.ones(DIM))["modes"]
        self.assertEqual(m0["transit"]["access"], ["WALK"])
        self.assertTrue(m0["transitOnly"])
        self.assertNotIn("direct", m0)
        self.assertEqual(m1["transit"]["access"], ["BICYCLE_PARKING"])  # x=1 clipped to k-1
        self.assertEqual(m1["direct"], ["BICYCLE"])
        self.assertNotIn("transitOnly", m1)

    def test_log_scale_midpoint(self):
        x = np.full(DIM, 0.5)
        v = scalars(decode(x))
        self.assertAlmostEqual(v["walk.reluctance"], round((0.5 * 5.0) ** 0.5, 3), places=9)

    def test_fixed_speeds(self):
        names = {g["name"] for g in GENES}
        self.assertNotIn("walk.speed", names)
        self.assertNotIn("bicycle.speed", names)
        self.assertEqual((FIXED_WALK_SPEED, FIXED_BIKE_SPEED), (1.33, 4.5))
        for x in [np.zeros(DIM), np.ones(DIM)] + self.genomes[:100]:
            st = decode(x)["preferences"]["street"]
            self.assertEqual(st["walk"]["speed"], FIXED_WALK_SPEED)
            self.assertEqual(st["bicycle"]["speed"], FIXED_BIKE_SPEED)

    def test_no_bicycle_rental(self):
        for q in self.decoded:
            self.assertNotIn("RENTAL", json.dumps(q["modes"]))

    def test_access_egress_transfer(self):
        seen = set()
        for q in self.decoded:
            t = q["modes"]["transit"]
            seen.add(t["access"][0])
            leg = ["BICYCLE"] if t["access"] == ["BICYCLE"] else ["WALK"]
            self.assertEqual(t["egress"], leg)
            self.assertEqual(t["transfer"], leg)
            self.assertEqual(t["transit"][0], {"mode": "TRAM"})
        self.assertEqual(seen, {"WALK", "BICYCLE", "BICYCLE_PARKING"})

    def test_direct(self):
        seen = set()
        for q in self.decoded:
            m = q["modes"]
            if "direct" in m:
                self.assertIn(m["direct"], (["WALK"], ["BICYCLE"]))
                self.assertNotIn("transitOnly", m)
                seen.add(m["direct"][0])
            else:
                self.assertIs(m["transitOnly"], True)
                seen.add(None)
        self.assertEqual(seen, {None, "WALK", "BICYCLE"})

    def test_deterministic_and_describe(self):
        x = self.genomes[0]
        self.assertEqual(decode(x), decode(x.copy()))
        s = describe(x)
        self.assertIsInstance(s, str)
        self.assertLess(len(s), 250)

    def test_bad_shape(self):
        with self.assertRaises(ValueError):
            decode(np.zeros(DIM - 1))

    def test_digits(self):
        self.assertEqual(genome.DIGITS, 3)
        for q in self.decoded[:100]:
            for name, v in scalars(q).items():
                self.assertEqual(v, round(v, 3), name)


WALK_ONLY = ("walk.boardCost", "walk.safetyFactor")
WALK_INACTIVE = ("bicycle.reluctance", "bicycle.triangle.safety", "bicycle.triangle.flatness",
                 "bicycle.triangle.time", "access")


class VariantTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(321)
        self.genomes = [random_genome(rng) for _ in range(1000)]
        self.walk = [decode(x, "walk") for x in self.genomes]

    def test_variants(self):
        self.assertEqual(VARIANTS, ("bike", "walk"))

    def test_default_variant_is_bike(self):
        for x in self.genomes[:200]:
            self.assertEqual(decode(x), decode(x, "bike"))
            self.assertEqual(describe(x), describe(x, "bike"))

    def test_unknown_variant(self):
        x = self.genomes[0]
        for fn in (lambda: decode(x, "car"), lambda: describe(x, "car"),
                   lambda: active_mask("car"), lambda: canonical(x, "car"),
                   lambda: encode_anchor("car")):
            with self.assertRaises(ValueError):
                fn()

    def test_walk_modes(self):
        seen = set()
        for q in self.walk:
            m = q["modes"]
            t = m["transit"]
            self.assertEqual(t["access"], ["WALK"])
            self.assertEqual(t["egress"], ["WALK"])
            self.assertEqual(t["transfer"], ["WALK"])
            if "direct" in m:
                self.assertEqual(m["direct"], ["WALK"])
                self.assertNotIn("transitOnly", m)
                seen.add("WALK")
            else:
                self.assertIs(m["transitOnly"], True)
                seen.add(None)
            self.assertNotIn("BICYCLE", json.dumps(q))
            self.assertNotIn("bicycle", q["preferences"]["street"])
            self.assertEqual(set(q["preferences"]["street"]), {"walk"})
        self.assertEqual(seen, {None, "WALK"})

    def test_walk_direct_floor_x2(self):
        d = IDX["direct"]
        for v, expect in [(0.0, None), (0.49, None), (0.5, "WALK"), (0.99, "WALK"), (1.0, "WALK")]:
            x = np.full(DIM, 0.5)
            x[d] = v
            m = decode(x, "walk")["modes"]
            self.assertEqual(m.get("direct", [None])[0], expect, v)

    def test_walk_shared_genes_match_bike(self):
        for x in self.genomes[:200]:
            w, b = decode(x, "walk"), decode(x, "bike")
            self.assertEqual(w["preferences"]["transit"], b["preferences"]["transit"])
            wk = dict(w["preferences"]["street"]["walk"])
            self.assertEqual(set(wk) - set(b["preferences"]["street"]["walk"]),
                             {"boardCost", "safetyFactor"})
            for k in ("boardCost", "safetyFactor"):
                wk.pop(k)
            self.assertEqual(wk, b["preferences"]["street"]["walk"])
            self.assertEqual(w["modes"]["transit"]["transit"], b["modes"]["transit"]["transit"])

    def test_active_mask(self):
        mb = active_mask("bike")
        self.assertEqual(sorted(np.flatnonzero(~mb).tolist()), sorted(IDX[n] for n in WALK_ONLY))
        self.assertEqual(active_mask().shape, (DIM,))
        m = active_mask("walk")
        self.assertEqual(m.dtype, bool)
        inactive = sorted(IDX[n] for n in WALK_INACTIVE)
        self.assertEqual(inactive, [1, 2, 3, 4, 8])
        self.assertEqual(sorted(np.flatnonzero(~m).tolist()), inactive)

    def test_canonical(self):
        for x in self.genomes[:300]:
            c = canonical(x, "walk")
            self.assertEqual(decode(c, "walk"), decode(x, "walk"))
            np.testing.assert_array_equal(c[~active_mask("walk")], 0.5)
            np.testing.assert_array_equal(c[active_mask("walk")], x[active_mask("walk")])
            cb = canonical(x, "bike")
            np.testing.assert_array_equal(cb[active_mask("bike")], x[active_mask("bike")])
            np.testing.assert_array_equal(cb[~active_mask("bike")], 0.5)
            self.assertEqual(decode(cb, "bike"), decode(x, "bike"))
        x0 = self.genomes[0].copy()
        self.assertFalse(np.shares_memory(canonical(x0, "walk"), x0))
        np.testing.assert_array_equal(x0, self.genomes[0])  # input untouched

    def test_canonical_ignores_inactive_genes(self):
        rng = np.random.default_rng(7)
        idx = [IDX[n] for n in WALK_INACTIVE]
        for x in self.genomes[:200]:
            y = x.copy()
            y[idx] = rng.random(len(idx))
            np.testing.assert_array_equal(canonical(x, "walk"), canonical(y, "walk"))
            self.assertEqual(decode(x, "walk"), decode(y, "walk"))

    def test_encode_anchor(self):
        for v in VARIANTS:
            x = encode_anchor(v)
            self.assertEqual(x.shape, (DIM,))
            self.assertTrue(((x >= 0) & (x <= 1)).all())
            np.testing.assert_array_equal(x, canonical(x, v))
            q = decode(x, v)
            m, p = q["modes"], q["preferences"]
            self.assertIs(m["transitOnly"], True)
            self.assertNotIn("direct", m)
            self.assertEqual(m["transit"]["access"], ["WALK"])
            self.assertEqual(m["transit"]["egress"], ["WALK"])
            self.assertEqual(p["street"]["walk"]["reluctance"], 2.0)
            self.assertEqual(p["transit"]["board"]["waitReluctance"], 1.0)
            self.assertEqual(p["transit"]["transfer"]["cost"], 0)
            bus = next(t for t in m["transit"]["transit"] if t["mode"] == "BUS")
            self.assertEqual(bus["cost"]["reluctance"], 1.0)
            for name in ("walk.reluctance", "transit.board.waitReluctance",
                         "transit.transfer.cost", "BUS.cost.reluctance"):
                self.assertEqual(scalars_any(q)[name], ANCHOR_VALUES[name], (v, name))
        b = decode(encode_anchor("bike"), "bike")["preferences"]["street"]["bicycle"]
        self.assertEqual(b["reluctance"], ANCHOR_VALUES["bicycle.reluctance"])
        t = b["optimization"]["triangle"]
        self.assertTrue(all(abs(w - 1 / 3) < 0.002 for w in t.values()))
        self.assertNotIn("bicycle", decode(encode_anchor("walk"), "walk")["preferences"]["street"])

    def test_walk_levers(self):
        bc, sf = IDX["walk.boardCost"], IDX["walk.safetyFactor"]
        for v, bcost, safe in [(0.0, 0, 0.0), (0.5, 900, 0.5), (1.0, 1800, 1.0)]:
            x = np.full(DIM, 0.5)
            x[bc] = x[sf] = v
            w = decode(x, "walk")["preferences"]["street"]["walk"]
            self.assertEqual((w["boardCost"], w["safetyFactor"]), (bcost, safe))
        w = decode(encode_anchor("walk"), "walk")["preferences"]["street"]["walk"]
        self.assertEqual((w["boardCost"], w["safetyFactor"]), (600, 1.0))
        self.assertEqual(ANCHOR_VALUES["walk.boardCost"], 600)

    def test_bike_ignores_walk_levers(self):
        bc, sf = IDX["walk.boardCost"], IDX["walk.safetyFactor"]
        for x in self.genomes[:100]:
            y = x.copy()
            y[[bc, sf]] = 1 - x[[bc, sf]]
            self.assertEqual(decode(x, "bike"), decode(y, "bike"))
            walk = decode(x, "bike")["preferences"]["street"]["walk"]
            self.assertEqual(set(walk), {"reluctance", "speed"})
            np.testing.assert_array_equal(canonical(x, "bike"), canonical(y, "bike"))

    def test_describe_walk(self):
        s = describe(self.genomes[0], "walk")
        self.assertIsInstance(s, str)
        self.assertNotIn("rower rel", s)
        self.assertLess(len(s), 250)


def scalars_any(q):
    """Shared scalars of a decoded query, for either variant."""
    p, m = q["preferences"], q["modes"]
    return {
        "walk.reluctance": p["street"]["walk"]["reluctance"],
        "transit.board.waitReluctance": p["transit"]["board"]["waitReluctance"],
        "transit.transfer.cost": p["transit"]["transfer"]["cost"],
        "BUS.cost.reluctance": next(t for t in m["transit"]["transit"]
                                    if t["mode"] == "BUS")["cost"]["reluctance"],
    }


if __name__ == "__main__":
    unittest.main()
