import hashlib
import time
import unittest

import numpy as np

from optimizer.nsga2 import (
    binary_tournament,
    crowding_distance,
    dominates,
    fast_non_dominated_sort,
    hypervolume_2d,
    nsga2,
    poly_mutation,
    sbx,
    survival_select,
)
from optimizer.tests._nsga2_legacy import nsga2 as legacy_nsga2


def zdt1_batch(X):
    X = np.asarray(X)
    f1 = X[:, 0]
    g = 1.0 + 9.0 * X[:, 1:].mean(axis=1)
    f2 = g * (1.0 - np.sqrt(f1 / g))
    F = np.column_stack([f1, f2])
    return F, np.zeros(len(X)), [None] * len(X)


def constrained_batch(X):
    # ZDT1 with f1 < 0.3 forbidden and a tight band on the tail genes;
    # random initial population is almost entirely infeasible.
    F, _, _ = zdt1_batch(X)
    cv = np.maximum(0.0, 0.3 - X[:, 0]) + np.maximum(0.0, X[:, 1:].mean(axis=1) - 0.2)
    details = [{"i": i} for i in range(len(X))]
    return F, cv, details


def quantized_batch(X):
    # ZDT1 snapped to a 0.25 grid: many genomes share identical objectives,
    # like GA weight vectors that decode to the same OTP itinerary.
    F, cv, details = zdt1_batch(X)
    return np.round(F * 4) / 4, cv, details


def run_hash(res):
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(res["X"]).tobytes())
    h.update(np.ascontiguousarray(res["F"]).tobytes())
    h.update(repr(res["front0"]).encode())
    return h.hexdigest()


class TestDominates(unittest.TestCase):
    def test_pareto(self):
        self.assertTrue(dominates([1, 2], [2, 3]))
        self.assertTrue(dominates([1, 2], [1, 3]))
        self.assertFalse(dominates([1, 2], [1, 2]))  # equal
        self.assertFalse(dominates([1, 3], [2, 2]))  # incomparable
        self.assertFalse(dominates([2, 2], [1, 3]))
        self.assertFalse(dominates([2, 3], [1, 2]))

    def test_feasible_beats_infeasible(self):
        # feasible dominates infeasible even with worse objectives
        self.assertTrue(dominates([9, 9], [0, 0], 0.0, 0.1))
        self.assertFalse(dominates([0, 0], [9, 9], 0.1, 0.0))

    def test_two_infeasible_by_cv(self):
        self.assertTrue(dominates([9, 9], [0, 0], 1.0, 2.0))
        self.assertFalse(dominates([0, 0], [9, 9], 2.0, 1.0))
        self.assertFalse(dominates([0, 0], [9, 9], 1.0, 1.0))  # tie in cv


class TestSorting(unittest.TestCase):
    def test_six_points(self):
        F = np.array([[1, 5], [2, 3], [4, 1], [3, 4], [5, 2], [6, 6]], dtype=float)
        fronts = fast_non_dominated_sort(F, np.zeros(6))
        self.assertEqual([sorted(f) for f in fronts], [[0, 1, 2], [3, 4], [5]])

    def test_infeasible_go_last(self):
        F = np.array([[0, 0], [5, 5], [6, 6], [1, 1]], dtype=float)
        cv = np.array([2.0, 0.0, 0.0, 1.0])
        fronts = fast_non_dominated_sort(F, cv)
        self.assertEqual([sorted(f) for f in fronts], [[1], [2], [3], [0]])


class TestCrowding(unittest.TestCase):
    def test_values(self):
        F = np.array([[0, 5], [1, 2], [3, 1], [4, 0]], dtype=float)
        d = crowding_distance(F)
        self.assertTrue(np.isinf(d[0]) and np.isinf(d[3]))
        # f1 range 4, f2 range 5
        self.assertAlmostEqual(d[1], (3 - 0) / 4 + (5 - 1) / 5)  # 1.55
        self.assertAlmostEqual(d[2], (4 - 1) / 4 + (2 - 0) / 5)  # 1.15

    def test_zero_range(self):
        F = np.array([[1, 3], [1, 2], [1, 1]], dtype=float)
        d = crowding_distance(F)
        self.assertFalse(np.any(np.isnan(d)))
        self.assertAlmostEqual(d[1], (3 - 1) / 2)

    def test_small_front(self):
        self.assertTrue(np.all(np.isinf(crowding_distance(np.array([[1.0, 2.0], [2.0, 1.0]])))))


class TestTournament(unittest.TestCase):
    def test_prefers_rank_then_crowd(self):
        rank = np.array([0, 1])
        crowd = np.array([0.1, 9.0])
        rng = np.random.default_rng(0)
        for _ in range(50):
            i = binary_tournament(rank, crowd, rng)
            self.assertIn(i, (0, 1))
        idx = binary_tournament(rank, crowd, np.random.default_rng(0), size=200)
        # whenever both candidates differ, index 0 wins; so 1 wins only vs itself
        self.assertGreater(np.mean(idx == 0), 0.6)
        rank = np.array([0, 0])
        idx = binary_tournament(rank, crowd, np.random.default_rng(0), size=200)
        self.assertGreater(np.mean(idx == 1), 0.6)


class TestOperators(unittest.TestCase):
    def test_sbx_bounds_and_determinism(self):
        rng = np.random.default_rng(42)
        for _ in range(2000):
            p1, p2 = rng.random(12), rng.random(12)
            p1[0], p2[0] = 0.0, 1.0  # exercise edges
            c1, c2 = sbx(p1, p2, rng)
            self.assertTrue(np.all((c1 >= 0) & (c1 <= 1)))
            self.assertTrue(np.all((c2 >= 0) & (c2 <= 1)))
        p1, p2 = np.full(5, 0.2), np.full(5, 0.7)
        a = sbx(p1, p2, np.random.default_rng(7))
        b = sbx(p1, p2, np.random.default_rng(7))
        np.testing.assert_array_equal(a[0], b[0])
        np.testing.assert_array_equal(a[1], b[1])

    def test_mutation_bounds_and_determinism(self):
        rng = np.random.default_rng(3)
        for _ in range(2000):
            x = rng.random(12)
            x[0], x[1] = 0.0, 1.0
            y = poly_mutation(x, rng, pm=1.0)
            self.assertTrue(np.all((y >= 0) & (y <= 1)))
        x = np.full(8, 0.5)
        np.testing.assert_array_equal(
            poly_mutation(x, np.random.default_rng(9), pm=1.0),
            poly_mutation(x, np.random.default_rng(9), pm=1.0),
        )
        # input not modified
        self.assertTrue(np.all(x == 0.5))


class TestHypervolume(unittest.TestCase):
    def test_manual(self):
        F = np.array([[1, 3], [2, 2], [3, 1], [5, 5]], dtype=float)
        # staircase vs ref (4,4): 3*1 + 2*1 + 1*1 = 6; (5,5) ignored
        self.assertAlmostEqual(hypervolume_2d(F, (4, 4)), 6.0)
        self.assertEqual(hypervolume_2d(np.array([[5.0, 5.0]]), (4, 4)), 0.0)


class TestNSGA2(unittest.TestCase):
    def test_zdt1(self):
        t0 = time.perf_counter()
        res = nsga2(zdt1_batch, dim=10, pop=40, gens=60, rng=np.random.default_rng(1))
        elapsed = time.perf_counter() - t0
        hv = hypervolume_2d(res["F"][res["front0"]], (1.1, 1.1))
        print(f"\nZDT1 HV={hv:.4f} time={elapsed:.2f}s front0={len(res['front0'])}")
        self.assertGreaterEqual(hv, 0.6)
        self.assertLess(elapsed, 20.0)
        self.assertEqual(res["X"].shape, (40, 10))
        self.assertTrue(np.all((res["X"] >= 0) & (res["X"] <= 1)))

    def test_determinism_and_callback(self):
        calls = []
        r1 = nsga2(zdt1_batch, 6, 12, 5, np.random.default_rng(5),
                   callback=lambda g, s: calls.append((g, len(s["front0"]), s["rank"].shape)))
        r2 = nsga2(zdt1_batch, 6, 12, 5, np.random.default_rng(5))
        np.testing.assert_array_equal(r1["X"], r2["X"])
        np.testing.assert_array_equal(r1["F"], r2["F"])
        self.assertEqual(r1["front0"], r2["front0"])
        self.assertEqual([c[0] for c in calls], list(range(6)))

    def test_batch_evaluation(self):
        sizes = []

        def ev(X):
            sizes.append(len(X))
            return zdt1_batch(X)

        nsga2(ev, 4, 10, 3, np.random.default_rng(0))
        self.assertEqual(sizes, [10, 10, 10, 10])

    def test_constrained_front_feasible(self):
        _, cv0, _ = constrained_batch(np.random.default_rng(2).random((30, 6)))
        self.assertGreater(np.mean(cv0 > 0), 0.8)  # start mostly infeasible
        res = nsga2(constrained_batch, dim=6, pop=30, gens=40, rng=np.random.default_rng(2))
        f0 = res["front0"]
        self.assertGreater(len(f0), 0)
        self.assertTrue(np.all(res["cv"][f0] == 0))
        self.assertTrue(np.all(res["F"][f0, 0] >= 0.3))
        # details travel with their individuals
        self.assertEqual(len(res["details"]), 30)


class TestSurvivalSelect(unittest.TestCase):
    # 6 unique points: front0 = A,B,C,D; E rank 1; G rank 2; plus 4 copies of
    # front0 members (indices 6..9) -> 10 points in total.
    F = np.array([[0, 5], [1, 3], [3, 1], [5, 0], [4, 4], [6, 6],
                  [1, 3], [1, 3], [3, 1], [0, 5]], dtype=float)
    cv = np.zeros(10)

    def test_unique_preferred(self):
        sel = survival_select(self.F, self.cv, 6, 6)
        self.assertEqual(len(sel), 6)
        self.assertEqual(sorted(sel), [0, 1, 2, 3, 4, 5])
        self.assertEqual(len({tuple(r) for r in self.F[sel]}), 6)
        # plain NSGA-II keeps copies from the 8-member first front instead
        plain = survival_select(self.F, self.cv, 6, None)
        self.assertEqual(len(plain), 6)
        self.assertLess(len({tuple(r) for r in self.F[plain]}), 6)

    def test_duplicates_fill_up(self):
        sel = survival_select(self.F, self.cv, 8, 6)
        self.assertEqual(sorted(sel[:6]), [0, 1, 2, 3, 4, 5])
        self.assertEqual(sel[6:], [6, 7])  # copies by (rank, index)
        self.assertEqual(sorted(survival_select(self.F, self.cv, 10, 6)), list(range(10)))

    def test_duplicates_ordered_by_rank(self):
        # copies of a rank-1 point and of a rank-0 point: rank-0 copy first
        F = np.array([[0, 1], [1, 0], [2, 2], [2, 2], [1, 0]], dtype=float)
        sel = survival_select(F, np.zeros(5), 5, 6)
        self.assertEqual(sorted(sel[:3]), [0, 1, 2])
        self.assertEqual(sel[3:], [4, 3])

    def test_representative_lowest_rank(self):
        # index 1 equals index 0 after rounding but strictly dominates it
        F = np.array([[1.0, 1.0], [1.0, 1.0 - 1e-9], [0.0, 2.0], [2.0, 0.0]])
        sel = survival_select(F, np.zeros(4), 3, 6)
        self.assertEqual(sorted(sel), [1, 2, 3])
        # equal rank -> lower index wins
        F2 = np.array([[1.0, 1.0], [1.0 + 1e-9, 1.0 - 1e-9], [0.0, 2.0]])
        self.assertEqual(sorted(survival_select(F2, np.zeros(3), 2, 6)), [0, 2])

    def test_cv_distinguishes(self):
        F = np.array([[1.0, 1.0], [1.0, 1.0], [0.0, 2.0]])
        cv = np.array([0.0, 0.5, 0.0])
        sel = survival_select(F, cv, 2, 6)
        self.assertEqual(sorted(sel), [0, 2])
        sel = survival_select(F, cv, 3, 6)
        self.assertEqual(sorted(sel), [0, 1, 2])


class TestNSGA2Dedupe(unittest.TestCase):
    # dedupe_decimals=None must reproduce the frozen GA v1 implementation
    # run-for-run (compared within one process, so no float-bit constants).
    LEGACY_CASES = {
        "zdt1": (zdt1_batch, 6, 12, 5, 7),
        "quant": (quantized_batch, 6, 16, 8, 3),
        "constr": (constrained_batch, 6, 20, 10, 2),
    }

    def test_none_matches_legacy(self):
        for name, (fn, dim, pop, gens, seed) in self.LEGACY_CASES.items():
            with self.subTest(name):
                old = legacy_nsga2(fn, dim, pop, gens, np.random.default_rng(seed))
                new = nsga2(fn, dim, pop, gens, np.random.default_rng(seed),
                            dedupe_decimals=None)
                for key in ("X", "F", "cv", "rank"):
                    np.testing.assert_array_equal(new[key], old[key])
                self.assertEqual(new["front0"], old["front0"])
                self.assertEqual(new["details"], old["details"])

    def test_front0_unique_and_more_diverse(self):
        def uniq(res):
            return len({tuple(r) for r in res["F"][res["front0"]]})

        plain = nsga2(quantized_batch, 6, 20, 15, np.random.default_rng(3),
                      dedupe_decimals=None)
        dd = nsga2(quantized_batch, 6, 20, 15, np.random.default_rng(3))
        print(f"\nquantized ZDT1 unique front0: plain={uniq(plain)} dedupe={uniq(dd)}")
        self.assertEqual(uniq(dd), len(dd["front0"]))  # no duplicate F in front0
        self.assertGreater(uniq(dd), uniq(plain))
        self.assertEqual(dd["X"].shape, (20, 6))

    def test_x0_anchor_seeded(self):
        x_anchor = np.linspace(0.0, 1.0, 6)
        states = {}

        def cb(g, s):
            states[g] = s["X"].copy()

        nsga2(zdt1_batch, 6, 10, 2, np.random.default_rng(4), callback=cb,
              X0=x_anchor)
        np.testing.assert_array_equal(states[0][0], x_anchor)
        # rows after the seeded ones keep the original random stream
        ref = np.random.default_rng(4).random((10, 6))
        np.testing.assert_array_equal(states[0][1:], ref[1:])

    def test_x0_matrix_clip_and_errors(self):
        X0 = np.array([[-0.5] * 4, [0.3] * 4, [1.7] * 4])
        states = {}
        nsga2(zdt1_batch, 4, 5, 0, np.random.default_rng(0),
              callback=lambda g, s: states.setdefault(g, s["X"].copy()), X0=X0)
        np.testing.assert_array_equal(states[0][:3], np.clip(X0, 0, 1))
        with self.assertRaises(ValueError):
            nsga2(zdt1_batch, 4, 2, 1, np.random.default_rng(0), X0=X0)  # k > pop
        with self.assertRaises(ValueError):
            nsga2(zdt1_batch, 4, 5, 1, np.random.default_rng(0), X0=np.zeros((1, 3)))
        with self.assertRaises(ValueError):
            nsga2(zdt1_batch, 4, 5, 1, np.random.default_rng(0),
                  X0=np.array([0.1, np.nan, 0.2, 0.3]))

    def test_determinism_with_x0(self):
        x_anchor = np.full(6, 0.25)
        r1 = nsga2(quantized_batch, 6, 14, 6, np.random.default_rng(11), X0=x_anchor)
        r2 = nsga2(quantized_batch, 6, 14, 6, np.random.default_rng(11), X0=x_anchor)
        self.assertEqual(run_hash(r1), run_hash(r2))
        self.assertEqual(r1["details"], r2["details"])


if __name__ == "__main__":
    unittest.main()
