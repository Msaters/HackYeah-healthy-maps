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
)


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


if __name__ == "__main__":
    unittest.main()
