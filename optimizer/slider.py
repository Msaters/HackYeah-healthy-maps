"""Offline "time <-> activity" slider over a Pareto front.

Usage:
    python3 -m optimizer.slider PATH/front.json [--n 7] [--variant bike|walk] [--out PATH]

The user gets a slider s in [0, 1] (0 = fastest, 1 = most physical activity)
with ``n`` ticks. Ticks are placed by **arc length** along the front, not by a
weighted sum of objectives: a weighted sum can only reach the convex hull of
the front and jumps over its concave stretches, while arc length visits the
front evenly.

Objectives (keys of every point): ``f_time_ratio`` (minimised) and
``active_kcal`` (maximised).

Ordering contract (shared with ``slider_select``, which calls these helpers on
its own points with the same keys):

* :func:`sorted_front` - stable sort by ``f_time_ratio`` ascending, ties by
  ``active_kcal`` descending. No filtering.
* :func:`arc_positions` - positions ``u`` aligned with ``sorted_front(points)``
  (``u[j]`` belongs to ``sorted_front(points)[j]``); it does not filter.
* :func:`pareto_filter` - the non-dominated subset (exact duplicates collapsed
  to their first occurrence), in ``sorted_front`` order. :func:`sample_front`
  applies it before computing positions, so ticks are monotone even when the
  input contains dominated points.

Writes ``slider.json`` (default: next to front.json):
``{"meta": {variant, n, f1, f2, distinct, merged, merge_eps, source, generated}, "ticks": [...]}``.
"""

import argparse
import datetime
import json
import math
import os
import sys

F1 = "f_time_ratio"
F2 = "active_kcal"
VARIANTS = ("bike", "walk")
DEFAULT_TICKS = 7
# Points closer than this to a group's representative in BOTH objectives are one
# variant for the user. Absolute units (not normalised), so a small front is not
# collapsed by min-max scaling. 0.005 = half a percent of the fastest time
# (~15 s on a 45 min trip); 2 kcal is below the accuracy of the MET estimate.
# Observed GA fronts have clusters of ~0.001-0.002x / ~0.5 kcal steps.
DEFAULT_MERGE_EPS = (0.005, 2.0)


def _key(p):
    return (float(p[F1]), -float(p[F2]))


def sorted_front(points):
    """Points sorted by f_time_ratio ascending (ties: more kcal first); stable, no filtering."""
    return sorted(points, key=_key)


def pareto_filter(points):
    """Non-dominated points (min f_time_ratio, max active_kcal) in sorted_front order.

    Exact duplicates of (f_time_ratio, active_kcal) are collapsed to the first
    one in sorted order. On the result both objectives are strictly increasing.
    """
    out = []
    best_kcal = -math.inf
    for p in sorted_front(points):
        # Sorted by time asc, kcal desc: p is non-dominated iff it beats every
        # faster-or-equal point on kcal.
        if float(p[F2]) > best_kcal:
            out.append(p)
            best_kcal = float(p[F2])
    return out


def _norm_eps(merge_eps):
    """``(eps_time, eps_kcal)`` or None when merging is off (None / 0 / (0, 0))."""
    if not merge_eps:
        return None
    et, ek = merge_eps
    if et < 0 or ek < 0:
        raise ValueError(f"merge_eps must be >= 0, got {merge_eps}")
    return (float(et), float(ek)) if (et > 0 or ek > 0) else None


def merge_close(points, merge_eps=DEFAULT_MERGE_EPS):
    """Collapse practically identical points of a non-dominated front.

    ``points`` should be :func:`pareto_filter` output (sorted_front order).
    Greedy, left to right: a group starts at its fastest point (the
    representative - stable, it is the point a user would get at the lower end)
    and takes every following point whose time AND kcal are both within
    ``merge_eps`` of the representative (no chaining, so a group spans at most
    eps). Endpoint pinning: the last group is represented by its last point, so
    the slider end stays the maximum-kcal point. ``merge_eps`` off -> unchanged.

    Returns ``(representatives, merged_count)``; objects are the input dicts.
    """
    eps = _norm_eps(merge_eps)
    pts = list(points)
    if eps is None or len(pts) < 2:
        return pts, 0
    et, ek = eps
    groups = []
    for p in pts:
        g = groups[-1] if groups else None
        if (g is not None
                and float(p[F1]) - float(g[0][F1]) <= et
                and abs(float(p[F2]) - float(g[0][F2])) <= ek):
            g.append(p)
        else:
            groups.append([p])
    reps = [g[0] for g in groups]
    reps[-1] = groups[-1][-1]
    return reps, len(pts) - len(reps)


def arc_positions(points):
    """Normalised arc-length positions u in [0, 1], aligned with ``sorted_front(points)``.

    f_time_ratio and active_kcal are min-max normalised within ``points``; an
    objective with zero range is left out of the distance. ``u`` is the
    cumulative Euclidean length divided by the total length, so the first
    point gets 0, the last 1, and the values are non-decreasing.

    Edge cases: no points -> []; one point -> [0.0]; zero total length (all
    points identical) -> evenly spaced ``j / (m - 1)`` so that the first/last
    invariant still holds (no division by zero).
    """
    pts = sorted_front(points)
    m = len(pts)
    if m == 0:
        return []
    if m == 1:
        return [0.0]
    cols = []
    for key in (F1, F2):
        vals = [float(p[key]) for p in pts]
        lo, hi = min(vals), max(vals)
        if hi - lo > 0:
            cols.append([(v - lo) / (hi - lo) for v in vals])
    cum = [0.0]
    for j in range(1, m):
        step = math.sqrt(sum((c[j] - c[j - 1]) ** 2 for c in cols))
        cum.append(cum[-1] + step)
    total = cum[-1]
    if total <= 0:
        return [j / (m - 1) for j in range(m)]
    u = [c / total for c in cum]
    u[-1] = 1.0  # guard against float drift
    return u


def _tick(s, u, index, point):
    query = point.get("query") or {}
    return {
        "s": s,
        "u": round(u, 6),
        "index": index,
        "modes": query.get("modes"),
        "preferences": query.get("preferences"),
        "metrics": {
            F1: point.get(F1),
            F2: point.get(F2),
            "steps": point.get("steps"),
            "duration_min": point.get("duration_min"),
        },
    }


def sample_front(front, n=DEFAULT_TICKS, merge_eps=DEFAULT_MERGE_EPS):
    """Pick ``n`` ticks along the front: tick i targets s_i = i/(n-1).

    Dominated points are dropped first (:func:`pareto_filter`), then practically
    identical ones merged (:func:`merge_close`; ``merge_eps=0`` or None
    disables it, restoring the unmerged behaviour); each tick gets
    the point whose arc position u is closest to s_i (tie -> the faster one).
    ``index`` is the position of the chosen point in ``sorted_front(front)``
    (the whole input, sorted, before filtering). Consecutive ticks have
    non-decreasing time and kcal; several ticks may share one point when the
    front has fewer than n points or they are unevenly spaced.
    """
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")
    if not front:
        raise ValueError("empty front")
    full = sorted_front(front)
    nd, _ = merge_close(pareto_filter(front), merge_eps)
    # index into the sorted input; identity-based so duplicates map correctly
    pos_in_full = {id(p): j for j, p in enumerate(full)}
    u = arc_positions(nd)
    ticks = []
    for i in range(n):
        s = i / (n - 1)
        # u is sorted asc and nd is in time order: strict '<' keeps the faster on ties
        best = 0
        for j in range(1, len(nd)):
            if abs(u[j] - s) < abs(u[best] - s):
                best = j
        ticks.append(_tick(s, u[best], pos_in_full[id(nd[best])], nd[best]))
    return ticks


def build_slider(front_doc, n=DEFAULT_TICKS, variant=None, source="front.json",
                 merge_eps=DEFAULT_MERGE_EPS):
    """slider.json document for a front.json document (``{"meta", "front"}``)."""
    meta_in = front_doc.get("meta") or {}
    variant = variant or meta_in.get("variant", "bike")
    front = front_doc.get("front") or []
    ticks = sample_front(front, n, merge_eps)
    _, merged = merge_close(pareto_filter(front), merge_eps) if front else (None, 0)
    eps = _norm_eps(merge_eps)
    return {
        "meta": {
            "variant": variant,
            "n": n,
            "f1": F1,
            "f2": F2,
            "distinct": len({t["index"] for t in ticks}),
            "merged": merged,
            "merge_eps": {"time": eps[0], "kcal": eps[1]} if eps else None,
            "source": source,
            "generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "ticks": ticks,
    }


def _load_front_doc(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("front"), list):
        raise ValueError(f"{path} has no 'front' list - is it a run_ga front.json?")
    if not doc["front"]:
        raise ValueError(f"{path}: 'front' is empty")
    for k, p in enumerate(doc["front"]):
        if not isinstance(p, dict) or F1 not in p or F2 not in p:
            raise ValueError(f"{path}: front[{k}] lacks '{F1}' / '{F2}'")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build slider.json (arc-length ticks) from a front.json.")
    ap.add_argument("front", help="path to front.json")
    ap.add_argument("--n", type=int, default=DEFAULT_TICKS, help=f"number of ticks (default {DEFAULT_TICKS})")
    ap.add_argument("--variant", choices=VARIANTS, help="default: meta.variant of front.json, else bike")
    ap.add_argument("--out", help="output path (default: slider.json next to front.json)")
    ap.add_argument("--merge-eps-time", type=float, default=DEFAULT_MERGE_EPS[0],
                    help=f"merge points within this f_time_ratio distance (default {DEFAULT_MERGE_EPS[0]})")
    ap.add_argument("--merge-eps-kcal", type=float, default=DEFAULT_MERGE_EPS[1],
                    help=f"... AND within this many kcal (default {DEFAULT_MERGE_EPS[1]}); both 0 = no merging")
    args = ap.parse_args(argv)
    if args.n < 2:
        ap.error("--n must be >= 2")
    if args.merge_eps_time < 0 or args.merge_eps_kcal < 0:
        ap.error("--merge-eps-* must be >= 0")
    try:
        doc = _load_front_doc(args.front)
        slider = build_slider(doc, args.n, args.variant, source=os.path.basename(args.front),
                              merge_eps=(args.merge_eps_time, args.merge_eps_kcal))
    except ValueError as e:
        print(f"[slider] ERROR: {e}", file=sys.stderr)
        return 2
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.front)), "slider.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(slider, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, out)
    m = slider["meta"]
    print(f"[slider] {m['variant']}: {m['n']} ticks, {m['distinct']} distinct points "
          f"({m['merged']} merged) -> {out}")
    for t in slider["ticks"]:
        x = t["metrics"]
        print(f"  s={t['s']:.3f} u={t['u']:.3f} #{t['index']:<3} time x{x[F1]:.3f}  {x[F2]:6.1f} kcal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
