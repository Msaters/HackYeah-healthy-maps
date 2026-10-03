"""Run NSGA-II over OTP weight genomes and export front.json, profiles.json and a report.

Usage (from the repo root):
    python3 -m optimizer.run_ga --mode quick|full --seed N --out DIR
                                [--workers K] [--pop P --gens G]
                                [--url URL] [--cache PATH | --no-cache]

Budgets (OTP queries = pop * (gens + 1) * pairs, plus one baseline per pair):
    quick: pop=12, gens=4,  4 "quick" pairs ->  240 queries
    full:  pop=24, gens=12, 10 pairs        -> 3120 queries

Outputs in DIR:
    checkpoint.json  current feasible front after every generation (front.json schema + "generation")
    front.json       {"meta": {...}, "front": [points]} - feasible first front, deduplicated by query,
                     sorted by f_time_ratio
    profiles.json    {"fast"|"balanced"|"active": {"modes", "preferences", "metrics"}}
    front.svg, front.md  report (optimizer.report)

Hypervolume (logged per generation) is computed on F = [time_ratio, -active_kcal] of the feasible
first front with reference point (2.0, 0.0): a route twice as slow as the fastest one with no active
kcal. Every feasible point is better than that in both objectives (the constraint keeps most ratios
well below 2), so HV grows when the front moves left (faster) or up (more kcal). Unit: ratio x kcal.

Standard library + numpy only.
"""
import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

from optimizer import genome, report
from optimizer.evaluate import (DEFAULT_CACHE, DEFAULT_OD_PAIRS, DEFAULT_URL, OTPClient,
                                compute_baselines, load_od_pairs, make_evaluator)
from optimizer.nsga2 import hypervolume_2d, nsga2
from optimizer.profiles import build_profiles, dedupe_front, non_dominated

MODES = {
    "quick": {"pop": 12, "gens": 4, "quick_pairs": True},
    "full": {"pop": 24, "gens": 12, "quick_pairs": False},
}
HV_REF = (2.0, 0.0)
ROUND = 4  # digits for exported objective values (stable, readable JSON)


def safe_decode(x):
    """Decode after replacing NaN/inf and clipping to [0, 1] (variation operators should not
    produce them, but a single bad gene must not crash a 20-minute run)."""
    x = np.nan_to_num(np.asarray(x, dtype=float), nan=0.5, posinf=1.0, neginf=0.0)
    return genome.decode(np.clip(x, 0.0, 1.0))


def _r(v):
    return round(float(v), ROUND)


def front_points(state):
    """Feasible first-front points of an NSGA-II state: deduplicated, non-dominated, sorted.

    Returns (points, feasible_flag). If no point is feasible yet, the (infeasible)
    first front is returned with feasible_flag=False so checkpoints are still useful.
    """
    idx = list(state["front0"])
    feas = [i for i in idx if state["cv"][i] <= 0]
    flag = bool(feas)
    if feas:
        idx = feas
    pts = []
    for i in idx:
        d = state["details"][i]
        pts.append({
            "x": [_r(v) for v in state["X"][i]],
            "query": d["query"],
            "f_time_ratio": _r(d["f_time_ratio"]),
            "active_kcal": _r(d["active_kcal"]),
            "steps": _r(d["steps"]),
            "duration_min": _r(d["duration_min"]),
            "cv": _r(d["cv"]),
            "per_pair": d["per_pair"],
        })
    return non_dominated(dedupe_front(pts)), flag


def _hv(points, feasible):
    if not points or not feasible:
        return 0.0
    F = np.array([[p["f_time_ratio"], -p["active_kcal"]] for p in points])
    return hypervolume_2d(F, HV_REF)


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="NSGA-II over OTP routing weights (time vs activity).")
    ap.add_argument("--mode", choices=sorted(MODES), default="quick")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--workers", type=int, default=10, help="parallel OTP requests (default 10)")
    ap.add_argument("--pop", type=int, help="population size (overrides --mode)")
    ap.add_argument("--gens", type=int, help="number of generations (overrides --mode)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--pairs", default=DEFAULT_OD_PAIRS, help="od_pairs.json path")
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="JSONL cache path")
    ap.add_argument("--no-cache", action="store_true", help="disable the on-disk cache")
    ap.add_argument("--no-report", action="store_true", help="skip front.svg / front.md")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    cfg = MODES[args.mode]
    pop = args.pop or cfg["pop"]
    gens = args.gens if args.gens is not None else cfg["gens"]
    os.makedirs(args.out, exist_ok=True)
    started = datetime.datetime.now().astimezone()
    t_start = time.perf_counter()

    pairs = load_od_pairs(args.pairs, quick=cfg["quick_pairs"])
    client = OTPClient(args.url, cache_path=None if args.no_cache else args.cache,
                       workers=args.workers)
    print(f"[run_ga] mode={args.mode} seed={args.seed} pop={pop} gens={gens} pairs={len(pairs)} "
          f"workers={args.workers} nominal budget={pop * (gens + 1) * len(pairs)} queries "
          "(actual count differs: batch dedupe, cache, walking fallback)", flush=True)

    t0 = time.perf_counter()
    baselines = compute_baselines(client, pairs)
    missing = [p["id"] for p in pairs if p["id"] not in baselines]
    if missing:
        print(f"[run_ga] WARNING: no baseline (OTP down?) for {missing}; dropping them",
              file=sys.stderr, flush=True)
        pairs = [p for p in pairs if p["id"] in baselines]
    if not pairs:
        print("[run_ga] ERROR: no pair has a baseline - is OTP running at "
              f"{args.url}? stats={client.stats}", file=sys.stderr)
        return 2
    print(f"[run_ga] baselines ({time.perf_counter() - t0:.1f} s): "
          + ", ".join(f"{k}={v:.1f} min" for k, v in baselines.items()), flush=True)

    evaluate = make_evaluator(pairs, baselines, client, safe_decode)

    def evaluate_batch(X):
        F, cv, details = evaluate(X)
        return np.nan_to_num(F, nan=1e6, posinf=1e6, neginf=-1e6), cv, details

    meta = {
        "seed": args.seed, "mode": args.mode, "pop": pop, "gens": gens,
        "pairs": [p["id"] for p in pairs],
        "baselines": {k: round(v, 2) for k, v in baselines.items()},
        "arrive_by": client.arrive_by,
        "hv_ref": list(HV_REF),
        "genes": [g["name"] for g in genome.GENES],
    }
    history = []
    t_gen = [time.perf_counter()]
    base_stats = dict(client.stats)

    def callback(gen, state):
        now = time.perf_counter()
        pts, feasible = front_points(state)
        hv = _hv(pts, feasible)
        n_feas = int(np.sum(state["cv"] <= 0))
        st = client.stats
        rec = {"gen": gen, "seconds": round(now - t_gen[0], 2), "feasible": n_feas,
               "front0": len(pts), "hv": round(hv, 4), "hits": st["hits"],
               "misses": st["misses"], "errors": st["errors"]}
        history.append(rec)
        print(f"[gen {gen:>3}/{gens}] {rec['seconds']:6.1f} s  feasible {n_feas:>3}/{len(state['cv'])}  "
              f"front0 {len(pts):>3}  HV {hv:8.3f}  cache hits {st['hits']} misses {st['misses']}"
              f" errors {st['errors']}", flush=True)
        t_gen[0] = now
        _write_json(os.path.join(args.out, "checkpoint.json"),
                    {"meta": dict(meta, generation=gen, feasible_front=feasible), "front": pts})

    result = nsga2(evaluate_batch, genome.DIM, pop, gens, np.random.default_rng(args.seed), callback)

    front, feasible = front_points(result)
    if not feasible:
        print("[run_ga] WARNING: no feasible point; exporting the infeasible first front",
              file=sys.stderr, flush=True)
    elapsed = time.perf_counter() - t_start
    st = client.stats
    meta.update({
        "feasible_front": feasible,
        "generated": started.isoformat(timespec="seconds"),
        "elapsed_s": round(elapsed, 1),
        # Measured, not pop*pairs: unique lookups per batch (plan_many dedupes identical
        # requests; walking fallbacks add some) and how many of them actually hit OTP.
        "queries": st["hits"] + st["misses"],
        "otp_requests": st["misses"],
        "cache": {"hits": st["hits"], "misses": st["misses"], "errors": st["errors"],
                  "baseline_hits": base_stats["hits"], "baseline_misses": base_stats["misses"]},
        "workers": args.workers,
        "history": history,
    })
    front_path = os.path.join(args.out, "front.json")
    _write_json(front_path, {"meta": meta, "front": front})
    profiles = build_profiles(front)
    _write_json(os.path.join(args.out, "profiles.json"), profiles)

    print(f"[run_ga] done in {elapsed:.1f} s: {len(front)} front points, "
          f"{meta['queries']} queries, {meta['otp_requests']} sent to OTP (hits {st['hits']}, misses {st['misses']}, errors {st['errors']})")
    for key in ("fast", "balanced", "active"):
        m = profiles[key]["metrics"]
        print(f"  {key:<9} time x{m['f_time_ratio']:.3f}  {m['active_kcal']:6.1f} kcal  "
              f"{m['steps']:6.0f} steps  {m['duration_min']:5.1f} min")
    if not args.no_report:
        svg, md = report.build_report(front_path)
        print(f"[run_ga] wrote {svg}\n[run_ga] wrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
