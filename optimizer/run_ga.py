"""Run NSGA-II over OTP weight genomes and export front.json, profiles.json and a report.

Usage (from the repo root):
    python3 -m optimizer.run_ga --mode quick|full --seed N --out DIR
                                [--variant bike|walk] [--ticks N] [--no-anchor]
                                [--workers K] [--pop P --gens G]
                                [--url URL] [--cache PATH | --no-cache]

Variants (the "[mam rower]" tick, see optimizer.genome): "bike" searches the full genome,
"walk" never uses a bicycle (bicycle genes are inactive and canonicalised to 0.5).
Unless --no-anchor is given, the first individual of the initial population is the anchor K1
(genome.encode_anchor: OTP default weights, plain transit); its metrics go to meta.anchor.

Budgets (OTP queries = pop * (gens + 1) * pairs, plus one baseline per pair):
    quick: pop=12, gens=4,  4 "quick" pairs ->  240 queries
    full:  pop=24, gens=12, 10 pairs        -> 3120 queries

Outputs in DIR:
    checkpoint.json  current feasible front after every generation (front.json schema + "generation")
    front.json       {"meta": {...}, "front": [points]} - feasible first front, deduplicated by query,
                     sorted by f_time_ratio
    slider.json      {"meta", "ticks"} - optimizer.slider.build_slider over the exported front
                     (tick.index = index in slider.sorted_front(front))
    profiles.json    {"fast"|"balanced"|"active": {"modes", "preferences", "metrics"}};
                     fast = tick 0, active = tick n-1, balanced = knee point
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

from optimizer import genome, report, slider
from optimizer.evaluate import (DEFAULT_CACHE, DEFAULT_OD_PAIRS, DEFAULT_URL, OTPClient,
                                compute_baselines, load_od_pairs, make_evaluator)
from optimizer.nsga2 import hypervolume_2d, nsga2
from optimizer.profiles import build_profiles, dedupe_front, non_dominated, query_key

MODES = {
    "quick": {"pop": 12, "gens": 4, "quick_pairs": True},
    "full": {"pop": 24, "gens": 12, "quick_pairs": False},
}
HV_REF = (2.0, 0.0)
ROUND = 4  # digits for exported objective values (stable, readable JSON)
DEDUPE_DECIMALS = 6  # objective-space dedupe in NSGA-II survival (passed explicitly, kept in meta)


def safe_decode(x, variant="bike"):
    """Decode after replacing NaN/inf, clipping to [0, 1] and canonicalising the inactive genes
    of the variant (variation operators should not produce NaN/inf, but a single bad gene must
    not crash a 20-minute run)."""
    x = np.nan_to_num(np.asarray(x, dtype=float), nan=0.5, posinf=1.0, neginf=0.0)
    return genome.decode(genome.canonical(np.clip(x, 0.0, 1.0), variant), variant)


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


def _point_metrics(d):
    """Rounded objective/constraint values of one evaluation detail (front.json point fields)."""
    return {"f_time_ratio": _r(d["f_time_ratio"]), "active_kcal": _r(d["active_kcal"]),
            "steps": _r(d["steps"]), "duration_min": _r(d["duration_min"]), "cv": _r(d["cv"])}


def anchor_summary(detail, front):
    """meta.anchor: metrics of the anchor K1 and whether its query is a point of the exported front."""
    key = query_key(detail["query"])
    return dict(_point_metrics(detail), per_pair=detail["per_pair"],
                in_front=any(query_key(p.get("query")) == key for p in front))


def build_slider_doc(front, meta, n, variant):
    """slider.json for the exported front, built from feasible points (cv == 0) only.

    run_ga exports either only feasible points or (no feasible point at all) only infeasible
    ones, so the feasible subset is the whole front or empty; tick.index therefore always points
    into slider.sorted_front(front) of front.json. An infeasible front still gets a slider
    (meta.feasible_front False) so the pipeline output is complete.
    """
    feas = [p for p in front if p.get("cv", 0) <= 0]
    if feas and len(feas) != len(front):
        raise ValueError("front mixes feasible and infeasible points; tick.index would be ambiguous")
    pts = feas or front
    doc = slider.build_slider({"meta": meta, "front": pts}, n=n, variant=variant)
    doc["meta"]["feasible_front"] = bool(feas)
    return doc


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="NSGA-II over OTP routing weights (time vs activity).")
    ap.add_argument("--mode", choices=sorted(MODES), default="quick")
    ap.add_argument("--variant", choices=genome.VARIANTS, default="bike",
                    help="bike = may use a bicycle, walk = never (the '[mam rower]' tick)")
    ap.add_argument("--ticks", type=int, default=slider.DEFAULT_TICKS,
                    help=f"slider ticks in slider.json (default {slider.DEFAULT_TICKS})")
    ap.add_argument("--no-anchor", action="store_true",
                    help="do not seed the initial population with the anchor K1")
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
    args = ap.parse_args(argv)
    if args.ticks < 2:
        ap.error("--ticks must be >= 2")
    return args


def main(argv=None, client=None):
    """CLI entry point. `client` (an OTPClient look-alike with plan_many, stats, arrive_by)
    replaces the real OTP client; tests use it to run the whole pipeline offline."""
    args = parse_args(argv)
    variant = args.variant
    cfg = MODES[args.mode]
    pop = args.pop or cfg["pop"]
    gens = args.gens if args.gens is not None else cfg["gens"]
    os.makedirs(args.out, exist_ok=True)
    started = datetime.datetime.now().astimezone()
    t_start = time.perf_counter()

    pairs = load_od_pairs(args.pairs, quick=cfg["quick_pairs"])
    if client is None:
        client = OTPClient(args.url, cache_path=None if args.no_cache else args.cache,
                           workers=args.workers)
    print(f"[run_ga] mode={args.mode} variant={variant} anchor={not args.no_anchor} "
          f"seed={args.seed} pop={pop} gens={gens} pairs={len(pairs)} "
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

    evaluate = make_evaluator(pairs, baselines, client, lambda x: safe_decode(x, variant))

    def evaluate_batch(X):
        F, cv, details = evaluate(X)
        return np.nan_to_num(F, nan=1e6, posinf=1e6, neginf=-1e6), cv, details

    meta = {
        "seed": args.seed, "mode": args.mode, "variant": variant, "pop": pop, "gens": gens,
        "ticks": args.ticks, "dedupe_decimals": DEDUPE_DECIMALS,
        "pairs": [p["id"] for p in pairs],
        "baselines": {k: round(v, 2) for k, v in baselines.items()},
        "arrive_by": client.arrive_by,
        "hv_ref": list(HV_REF),
        "genes": [g["name"] for g in genome.GENES],
        "active_genes": [g["name"] for g, a in zip(genome.GENES, genome.active_mask(variant)) if a],
    }
    X0 = None if args.no_anchor else np.atleast_2d(genome.encode_anchor(variant))
    anchor_detail = []  # details of row 0 of the initial population (= X0[0])
    history = []
    t_gen = [time.perf_counter()]
    base_stats = dict(client.stats)

    def callback(gen, state):
        now = time.perf_counter()
        if gen == 0 and X0 is not None:
            anchor_detail.append(state["details"][0])
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

    result = nsga2(evaluate_batch, genome.DIM, pop, gens, np.random.default_rng(args.seed),
                   callback, X0=X0, dedupe_decimals=DEDUPE_DECIMALS)

    front, feasible = front_points(result)
    if not feasible:
        print("[run_ga] WARNING: no feasible point; exporting the infeasible first front",
              file=sys.stderr, flush=True)
    anchor = anchor_summary(anchor_detail[0], front) if anchor_detail else None
    if anchor is not None and anchor["cv"] > 0:
        print(f"[run_ga] WARNING: anchor K1 violates the constraint (cv={anchor['cv']})",
              file=sys.stderr, flush=True)
    slider_doc = build_slider_doc(front, meta, args.ticks, variant)
    if not slider_doc["meta"]["feasible_front"]:
        print("[run_ga] WARNING: slider.json built from an infeasible front "
              "(slider.meta.feasible_front = false)", file=sys.stderr, flush=True)
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
        "anchor": anchor,
        "slider": {"n": slider_doc["meta"]["n"], "distinct": slider_doc["meta"]["distinct"],
                   "feasible_front": slider_doc["meta"]["feasible_front"], "file": "slider.json"},
        "history": history,
    })
    front_path = os.path.join(args.out, "front.json")
    _write_json(front_path, {"meta": meta, "front": front})
    _write_json(os.path.join(args.out, "slider.json"), slider_doc)
    profiles = build_profiles(front, slider_doc)
    _write_json(os.path.join(args.out, "profiles.json"), profiles)

    print(f"[run_ga] done in {elapsed:.1f} s: {len(front)} front points, "
          f"{meta['queries']} queries, {meta['otp_requests']} sent to OTP (hits {st['hits']}, misses {st['misses']}, errors {st['errors']})")
    for key in ("fast", "balanced", "active"):
        m = profiles[key]["metrics"]
        print(f"  {key:<9} time x{m['f_time_ratio']:.3f}  {m['active_kcal']:6.1f} kcal  "
              f"{m['steps']:6.0f} steps  {m['duration_min']:5.1f} min")
    if anchor is not None:
        print(f"  anchor K1 time x{anchor['f_time_ratio']:.3f}  {anchor['active_kcal']:6.1f} kcal  "
              f"{anchor['steps']:6.0f} steps  cv {anchor['cv']}  in_front={anchor['in_front']}")
    sm = slider_doc["meta"]
    print(f"[run_ga] slider: {sm['n']} ticks, {sm['distinct']} distinct front points")
    if not args.no_report:  # after slider.json, so the report draws the ticks
        svg, md = report.build_report(front_path)
        print(f"[run_ga] wrote {svg}\n[run_ga] wrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
