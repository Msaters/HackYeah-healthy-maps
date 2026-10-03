"""Measure the online route slider on O-D pairs (default: the 6 held-out pairs).

For every pair the same pipeline as the backend runs (``tick_requests`` -> ``OTPClient.plan_many``
-> ``build_route_slider``, deadline from od_pairs ``meta.arrive_by``) and these are measured:

- ``monotonic_rate``: share of pairs whose RAW ticks 0..n-1 (the itinerary OTP picked for
  ``tick:i``, before merging / filtering) have non-decreasing duration and active kcal
  (tolerance 0.5 min / 1 kcal);
- ``mean_distinct``: mean number of distinct routes (``route_signature``) among the raw ticks;
- ``mean_positions``: mean number of positions of the mini-front (``positions``);
- ``build_s_p50`` / ``build_s_max``: wall time of plan_many + build_route_slider WITHOUT disk
  cache (one warm-up request first), workers as given.

    python3 -m optimizer.slider_eval --slider optimizer/out/quick_bike/slider.json \
        [--pairs held-out|all] [--out PATH.json] [--workers 8] [--cache PATH]

``--cache`` only affects the quality pass (a second plan_many); timing is always uncached.
Needs a running OTP (see optimizer/evaluate.py). Standard library only.
"""
import argparse
import json
import statistics
import sys
import time

from optimizer.evaluate import (BASELINE_TRANSIT, DEFAULT_OD_PAIRS, DEFAULT_URL, OTPClient, itinerary_metrics,
                                load_od_pairs, pick_itinerary)
from optimizer.slider_select import (ROUTE_QUERY, build_route_slider, query_arrive_by,
                                     route_signature, tick_requests)

TOL_MIN = 0.5
TOL_KCAL = 1.0
TARGETS = {"monotonic_rate": 0.8, "mean_distinct": 4.0, "build_s_max": 2.0}


# ---------------------------------------------------------------- pure metric functions
def is_monotonic(raw, tol_min=TOL_MIN, tol_kcal=TOL_KCAL):
    """True when duration and active kcal never decrease by more than the tolerances.
    ``raw``: list of dicts with ``duration_min`` and ``active_kcal`` in tick order.
    Fewer than 2 ticks -> True (nothing to violate)."""
    for a, b in zip(raw, raw[1:]):
        if b["duration_min"] < a["duration_min"] - tol_min:
            return False
        if b["active_kcal"] < a["active_kcal"] - tol_kcal:
            return False
    return True


def count_distinct(signatures):
    """Number of different non-None signatures."""
    return len({s for s in signatures if s is not None})


def raw_ticks(results, requests, weight=70.0, height=1.75):
    """Raw per-tick rows (tick order) from plan_many answers: the picked itinerary per
    ``tick:i`` request before any merging / filtering. Ticks without a route get ``None``."""
    rows = []
    for res, req in zip(results, requests):
        tag = req.get("tag", "") if isinstance(req, dict) else ""
        if not tag.startswith("tick:"):
            continue
        it = pick_itinerary(res) if isinstance(res, dict) and "error" not in res else None
        if it is None:
            rows.append({"tick": int(tag.split(":")[1]), "signature": None})
            continue
        m = itinerary_metrics(it, weight=weight, height=height)
        rows.append({"tick": int(tag.split(":")[1]), "signature": route_signature(it),
                     "duration_min": round(m["duration_min"], 2),
                     "active_kcal": round(m["active_kcal"], 1), "steps": int(round(m["steps"]))})
    rows.sort(key=lambda r: r["tick"])
    return rows


def pair_metrics(raw, route_slider):
    """Metrics of one pair from raw ticks and the ``build_route_slider`` result."""
    valid = [r for r in raw if r["signature"] is not None]
    pos = route_slider.get("positions") or []
    return {
        "monotonic": is_monotonic(valid),
        "distinct": count_distinct(r["signature"] for r in raw),
        "n_positions": len(pos),
        "raw_ticks": [{k: v for k, v in r.items() if k != "signature"} for r in raw],
        "positions": [{"s": p["s"], "duration_min": p["metrics"]["duration_min"],
                       "active_kcal": p["metrics"]["active_kcal"], "steps": p["metrics"]["steps"],
                       "modes": p["metrics"]["modes"], "sources": p["sources"]} for p in pos],
        "dropped": route_slider.get("dropped"),
        "warnings": route_slider.get("warnings") or [],
    }


def percentile(values, q):
    """Nearest-rank percentile (q in 0..100) of a non-empty list."""
    vals = sorted(values)
    k = max(0, min(len(vals) - 1, int(round(q / 100.0 * len(vals) + 0.5)) - 1))
    return vals[k]


def aggregate(per_pair, build_times):
    """Summary over pairs: rates, means and build-time p50 / max (None when empty)."""
    n = len(per_pair)
    out = {
        "n_pairs": n,
        "monotonic_rate": sum(1 for p in per_pair if p["monotonic"]) / n if n else None,
        "mean_distinct": statistics.fmean(p["distinct"] for p in per_pair) if n else None,
        "mean_positions": statistics.fmean(p["n_positions"] for p in per_pair) if n else None,
        "build_s_p50": statistics.median(build_times) if build_times else None,
        "build_s_max": max(build_times) if build_times else None,
    }
    out["targets_met"] = {
        "monotonic_rate": n > 0 and out["monotonic_rate"] >= TARGETS["monotonic_rate"],
        "mean_distinct": n > 0 and out["mean_distinct"] >= TARGETS["mean_distinct"],
        "build_s_max": bool(build_times) and out["build_s_max"] < TARGETS["build_s_max"],
    }
    return out


# ---------------------------------------------------------------- live evaluation
def evaluate_pair(slider, pair, deadline, client, quality_client=None):
    """Run the backend pipeline for one pair; returns (metrics dict, build seconds).
    ``client`` does the timed run (should have no disk cache). ``quality_client``, when given,
    produces the answers used for the metrics (e.g. a cached client)."""
    reqs = tick_requests(slider, pair["from"], pair["to"])
    t0 = time.perf_counter()
    results = client.plan_many(reqs)
    rs = build_route_slider(results, reqs, deadline)
    dt = time.perf_counter() - t0
    if quality_client is not None:
        results = quality_client.plan_many(reqs)
        rs = build_route_slider(results, reqs, deadline)
    m = pair_metrics(raw_ticks(results, reqs), rs)
    m.update({"id": pair["id"], "baseline_min": rs.get("baseline_min"),
              "build_s": round(dt, 3), "n_requests": len(reqs)})
    return m, dt


def select_pairs(which):
    pairs = load_od_pairs()
    with open(DEFAULT_OD_PAIRS, encoding="utf-8") as f:
        quick = set(json.load(f)["quick"])
    if which == "held-out":
        pairs = [p for p in pairs if p["id"] not in quick]
    return pairs


def run(slider, pairs, deadline, url=DEFAULT_URL, workers=8, cache_path=None):
    arrive_by = query_arrive_by(deadline)
    client = OTPClient(url, cache_path=None, workers=workers, arrive_by=arrive_by,
                       query=ROUTE_QUERY)
    quality = (OTPClient(url, cache_path=cache_path, workers=workers, arrive_by=arrive_by,
                         query=ROUTE_QUERY) if cache_path else None)
    # warm-up: first request after idle is slow (JIT, graph pages); not timed
    # (reversed O-D, so no later request of the timed run is served from the in-memory cache)
    client.plan(pairs[0]["to"], pairs[0]["from"], BASELINE_TRANSIT["modes"],
                BASELINE_TRANSIT["preferences"])
    per_pair, times = [], []
    for p in pairs:
        m, dt = evaluate_pair(slider, p, deadline, client, quality)
        per_pair.append(m)
        times.append(dt)
    return {"summary": aggregate(per_pair, times), "per_pair": per_pair}


def print_table(result, file=None):
    file = file or sys.stdout
    s = result["summary"]
    print(f"{'para':<24} {'mono':>5} {'dist':>4} {'poz':>3} {'build':>6}  pozycje (czas min/kcal/kroki)",
          file=file)
    for p in result["per_pair"]:
        poz = " ".join(f"{q['duration_min']:.0f}/{q['active_kcal']:.0f}/{q['steps']}"
                       for q in p["positions"])
        print(f"{p['id']:<24} {'tak' if p['monotonic'] else 'NIE':>5} {p['distinct']:>4} "
              f"{p['n_positions']:>3} {p['build_s']:>5.2f}s  {poz}", file=file)
        if any(p["dropped"].values()):
            print(f"{'':<24} dropped: { {k: v for k, v in p['dropped'].items() if v} }", file=file)
        for w in p["warnings"]:
            print(f"{'':<24} UWAGA: {w}", file=file)
    def f(v, fmt):
        return "-" if v is None else format(v, fmt)
    t = s["targets_met"]
    print(f"\nn_pairs={s['n_pairs']}", file=file)
    print(f"monotonic_rate = {f(s['monotonic_rate'], '.2f')} (cel >= {TARGETS['monotonic_rate']}) "
          f"{'OK' if t['monotonic_rate'] else 'NIE'}", file=file)
    print(f"mean_distinct  = {f(s['mean_distinct'], '.2f')} (cel >= {TARGETS['mean_distinct']:g}) "
          f"{'OK' if t['mean_distinct'] else 'NIE'}", file=file)
    print(f"mean_positions = {f(s['mean_positions'], '.2f')}", file=file)
    print(f"build_s_p50    = {f(s['build_s_p50'], '.2f')} s, build_s_max = "
          f"{f(s['build_s_max'], '.2f')} s (cel < {TARGETS['build_s_max']:g}) "
          f"{'OK' if t['build_s_max'] else 'NIE'}", file=file)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the online route slider on O-D pairs")
    ap.add_argument("--slider", required=True, help="slider.json ({meta, ticks})")
    ap.add_argument("--pairs", choices=("held-out", "all"), default="held-out")
    ap.add_argument("--out", help="write the result JSON here")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cache", default=None, help="JSONL cache for the quality pass only")
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)
    with open(args.slider, encoding="utf-8") as f:
        slider = json.load(f)
    with open(DEFAULT_OD_PAIRS, encoding="utf-8") as f:
        deadline = json.load(f)["meta"]["arrive_by"]
    pairs = select_pairs(args.pairs)
    result = run(slider, pairs, deadline, url=args.url, workers=args.workers,
                 cache_path=args.cache)
    result["meta"] = {"slider": args.slider, "pairs": args.pairs, "deadline": deadline,
                      "workers": args.workers, "n_ticks": len(slider["ticks"]),
                      "variant": (slider.get("meta") or {}).get("variant")}
    print_table(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
