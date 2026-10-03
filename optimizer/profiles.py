"""Front post-processing: deduplication, sorting and fast/balanced/active profiles.

The knee-point selection itself lives in optimizer.report.pick_profiles, so the
report and profiles.json always agree on which points are the profiles. When a
slider (optimizer.slider) is given, "fast" and "active" are its first and last
ticks, so profiles.json and slider.json name the same extreme routes.
Standard library only.
"""
import json

from optimizer.report import pick_profiles
from optimizer.slider import sorted_front

PROFILE_KEYS = ("fast", "balanced", "active")
METRIC_KEYS = ("f_time_ratio", "active_kcal", "steps", "duration_min")


def query_key(query):
    """Canonical JSON of an OTP query (modes + preferences) used for deduplication."""
    return json.dumps(query, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sort_key(point):
    """Deterministic order: time ratio asc, kcal desc, then the query text."""
    return (float(point["f_time_ratio"]), -float(point["active_kcal"]), query_key(point.get("query")))


def dedupe_front(points):
    """Drop points with an identical query; keep the first in sort_key order.

    Different genomes can decode to the same query (rounding, categorical genes),
    and then OTP returns the same routes, so they are one front point.
    """
    seen = set()
    out = []
    for p in sorted(points, key=sort_key):
        k = query_key(p.get("query"))
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _dominates(a, b):
    """a dominates b on (f_time_ratio min, active_kcal max)."""
    ta, ka = float(a["f_time_ratio"]), float(a["active_kcal"])
    tb, kb = float(b["f_time_ratio"]), float(b["active_kcal"])
    return ta <= tb and ka >= kb and (ta < tb or ka > kb)


def non_dominated(points):
    """Keep only points not dominated by any other (ties with equal metrics are all kept).

    NSGA-II's first front is non-dominated in F, but deduplication and the
    exported (rounded) values can still leave dominated points; report.py does
    not filter, so front.json must.
    """
    return [p for p in points if not any(_dominates(q, p) for q in points if q is not p)]


def _metrics(point):
    return {k: point.get(k) for k in METRIC_KEYS}


def build_profiles(front, slider=None):
    """front (list of front.json points) -> {"fast"|"balanced"|"active": {modes, preferences, metrics}}.

    Uses the knee-point logic of optimizer.report.pick_profiles. With a slider
    document (slider.json built from this same front), "fast" is tick 0 and
    "active" is tick n-1 (tick.index points into slider.sorted_front(front));
    "balanced" stays the knee point. With fewer than three distinct points,
    profiles may repeat; an empty front raises ValueError.
    """
    if not front:
        raise ValueError("empty front: no profiles to build")
    idx = pick_profiles(front)
    chosen = {key: front[idx[key]] for key in PROFILE_KEYS}
    if slider is not None:
        ticks = slider.get("ticks") or []
        if not ticks:
            raise ValueError("slider has no ticks")
        ordered = sorted_front(front)
        for key, tick in (("fast", ticks[0]), ("active", ticks[-1])):
            if not 0 <= tick["index"] < len(ordered):
                raise ValueError(f"slider tick index {tick['index']} outside the front")
            chosen[key] = ordered[tick["index"]]
    out = {}
    for key in PROFILE_KEYS:
        p = chosen[key]
        q = p.get("query") or {}
        out[key] = {"modes": q.get("modes"), "preferences": q.get("preferences"),
                    "metrics": _metrics(p)}
    return out
