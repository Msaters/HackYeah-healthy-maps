# FROZEN REFERENCE: verbatim copy of optimizer/nsga2.py from GA v1 (git HEAD 08141b0,
# before objective-space dedupe and X0 were added). Used only by
# tests/test_nsga2.py to check that nsga2(..., dedupe_decimals=None) reproduces
# the old behaviour exactly. Do not edit.

"""Elitist NSGA-II (Deb et al. 2002) with constraint-domination, OTP-independent.

All objectives are minimised. Decision variables live in [0, 1]^D.
`evaluate_batch(X) -> (F, cv, details)` is called once per generation with the
whole offspring matrix, so the caller may parallelise evaluations.
"""

import numpy as np


def dominates(fa, fb, cva=0.0, cvb=0.0):
    """Deb's constraint-domination: does solution a dominate solution b?"""
    if cva <= 0 and cvb > 0:
        return True
    if cva > 0 and cvb <= 0:
        return False
    if cva > 0 and cvb > 0:
        return cva < cvb
    fa = np.asarray(fa, dtype=float)
    fb = np.asarray(fb, dtype=float)
    return bool(np.all(fa <= fb) and np.any(fa < fb))


def fast_non_dominated_sort(F, cv):
    """Return fronts (lists of indices), best first."""
    F = np.asarray(F, dtype=float)
    cv = np.asarray(cv, dtype=float)
    n = len(F)
    dominated_by = [[] for _ in range(n)]  # S_p: solutions p dominates
    count = np.zeros(n, dtype=int)         # n_p: how many dominate p
    for p in range(n):
        for q in range(p + 1, n):
            if dominates(F[p], F[q], cv[p], cv[q]):
                dominated_by[p].append(q)
                count[q] += 1
            elif dominates(F[q], F[p], cv[q], cv[p]):
                dominated_by[q].append(p)
                count[p] += 1
    fronts = []
    current = [i for i in range(n) if count[i] == 0]
    while current:
        fronts.append(current)
        nxt = []
        for p in current:
            for q in dominated_by[p]:
                count[q] -= 1
                if count[q] == 0:
                    nxt.append(q)
        current = sorted(nxt)
    return fronts


def crowding_distance(F):
    """Crowding distance for the points of a single front (rows of F)."""
    F = np.asarray(F, dtype=float)
    n, m = F.shape
    d = np.zeros(n)
    if n <= 2:
        d[:] = np.inf
        return d
    for j in range(m):
        order = np.argsort(F[:, j], kind="stable")
        fmin, fmax = F[order[0], j], F[order[-1], j]
        d[order[0]] = d[order[-1]] = np.inf
        span = fmax - fmin
        if span <= 0:
            continue
        d[order[1:-1]] += (F[order[2:], j] - F[order[:-2], j]) / span
    return d


def binary_tournament(rank, crowd, rng, size=None):
    """Crowded binary tournament. Returns one index, or `size` indices."""
    rank = np.asarray(rank)
    crowd = np.asarray(crowd, dtype=float)
    n = len(rank)
    k = 1 if size is None else size
    a = rng.integers(0, n, size=k)
    b = rng.integers(0, n, size=k)
    better_a = (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (crowd[a] >= crowd[b]))
    winners = np.where(better_a, a, b)
    return int(winners[0]) if size is None else winners


def sbx(p1, p2, rng, eta=15, pc=0.9):
    """Simulated binary crossover bounded to [0, 1]."""
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    c1, c2 = p1.copy(), p2.copy()
    D = len(p1)
    # Draw all randoms up front so the stream consumed is fixed per call.
    do_cross = rng.random()
    per_var = rng.random(D)
    u = rng.random(D)
    swap = rng.random(D)
    if do_cross > pc:
        return c1, c2
    for i in range(D):
        if per_var[i] > 0.5 or abs(p1[i] - p2[i]) < 1e-14:
            continue
        y1, y2 = min(p1[i], p2[i]), max(p1[i], p2[i])
        dy = y2 - y1
        # child near y1
        beta = 1.0 + 2.0 * (y1 - 0.0) / dy
        alpha = 2.0 - beta ** -(eta + 1.0)
        betaq = _sbx_betaq(u[i], alpha, eta)
        a = 0.5 * ((y1 + y2) - betaq * dy)
        # child near y2
        beta = 1.0 + 2.0 * (1.0 - y2) / dy
        alpha = 2.0 - beta ** -(eta + 1.0)
        betaq = _sbx_betaq(u[i], alpha, eta)
        b = 0.5 * ((y1 + y2) + betaq * dy)
        a, b = min(max(a, 0.0), 1.0), min(max(b, 0.0), 1.0)
        if swap[i] <= 0.5:
            c1[i], c2[i] = b, a
        else:
            c1[i], c2[i] = a, b
    return c1, c2


def _sbx_betaq(u, alpha, eta):
    if u <= 1.0 / alpha:
        return (u * alpha) ** (1.0 / (eta + 1.0))
    return (1.0 / (2.0 - u * alpha)) ** (1.0 / (eta + 1.0))


def poly_mutation(x, rng, eta=20, pm=None):
    """Bounded polynomial mutation on [0, 1]; default rate 1/D."""
    y = np.asarray(x, dtype=float).copy()
    D = len(y)
    if pm is None:
        pm = 1.0 / D
    mask = rng.random(D)
    u = rng.random(D)
    mpow = 1.0 / (eta + 1.0)
    for i in range(D):
        if mask[i] >= pm:
            continue
        v = y[i]
        d1, d2 = v - 0.0, 1.0 - v
        if u[i] < 0.5:
            xy = 1.0 - d1
            val = 2.0 * u[i] + (1.0 - 2.0 * u[i]) * xy ** (eta + 1.0)
            dq = val ** mpow - 1.0
        else:
            xy = 1.0 - d2
            val = 2.0 * (1.0 - u[i]) + 2.0 * (u[i] - 0.5) * xy ** (eta + 1.0)
            dq = 1.0 - val ** mpow
        y[i] = min(max(v + dq, 0.0), 1.0)
    return y


def hypervolume_2d(F, ref):
    """Hypervolume (minimisation) of 2-D points w.r.t. reference point `ref`."""
    F = np.asarray(F, dtype=float).reshape(-1, 2)
    ref = np.asarray(ref, dtype=float)
    F = F[np.all(F < ref, axis=1)]
    if len(F) == 0:
        return 0.0
    F = F[np.lexsort((F[:, 1], F[:, 0]))]
    hv, best_f2 = 0.0, ref[1]
    for f1, f2 in F:
        if f2 < best_f2:
            hv += (ref[0] - f1) * (best_f2 - f2)
            best_f2 = f2
    return float(hv)


def _rank_and_crowd(F, cv):
    n = len(F)
    rank = np.empty(n, dtype=int)
    crowd = np.empty(n)
    fronts = fast_non_dominated_sort(F, cv)
    for r, fr in enumerate(fronts):
        rank[fr] = r
        crowd[fr] = crowding_distance(F[fr])
    return fronts, rank, crowd


def _make_offspring(X, rank, crowd, rng, n_off):
    dim = X.shape[1]
    parents = binary_tournament(rank, crowd, rng, size=2 * ((n_off + 1) // 2))
    kids = []
    for k in range(0, len(parents), 2):
        c1, c2 = sbx(X[parents[k]], X[parents[k + 1]], rng)
        kids.append(poly_mutation(c1, rng))
        kids.append(poly_mutation(c2, rng))
    return np.array(kids[:n_off]).reshape(n_off, dim)


def _state(X, F, cv, details, rank, fronts):
    front0 = list(fronts[0]) if fronts else []
    feasible = [i for i in front0 if cv[i] <= 0]
    if feasible:
        front0 = feasible
    return {"X": X, "F": F, "cv": cv, "details": details,
            "rank": rank, "front0": front0}


def _evaluate(evaluate_batch, X):
    F, cv, details = evaluate_batch(X)
    F = np.asarray(F, dtype=float).reshape(len(X), -1)
    cv = np.asarray(cv, dtype=float).reshape(len(X))
    details = list(details) if details is not None else [None] * len(X)
    return F, cv, details


def nsga2(evaluate_batch, dim, pop, gens, rng, callback=None):
    """Run elitist (mu+lambda) NSGA-II.

    Returns {"X","F","cv","details","rank","front0"} for the final population;
    "front0" holds indices of the first front (feasible only, if any exist).
    """
    X = rng.random((pop, dim))
    F, cv, details = _evaluate(evaluate_batch, X)
    fronts, rank, crowd = _rank_and_crowd(F, cv)
    if callback is not None:
        callback(0, _state(X, F, cv, details, rank, fronts))

    for gen in range(1, gens + 1):
        Xo = _make_offspring(X, rank, crowd, rng, pop)
        Fo, cvo, do = _evaluate(evaluate_batch, Xo)

        XA = np.vstack([X, Xo])
        FA = np.vstack([F, Fo])
        cvA = np.concatenate([cv, cvo])
        dA = details + do

        selected = []
        for fr in fast_non_dominated_sort(FA, cvA):
            if len(selected) + len(fr) <= pop:
                selected.extend(fr)
            else:
                cd = crowding_distance(FA[fr])
                order = np.argsort(-cd, kind="stable")
                selected.extend(fr[i] for i in order[: pop - len(selected)])
            if len(selected) >= pop:
                break

        X, F, cv = XA[selected], FA[selected], cvA[selected]
        details = [dA[i] for i in selected]
        fronts, rank, crowd = _rank_and_crowd(F, cv)
        if callback is not None:
            callback(gen, _state(X, F, cv, details, rank, fronts))

    return _state(X, F, cv, details, rank, fronts)
