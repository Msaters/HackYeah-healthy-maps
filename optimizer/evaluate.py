"""Evaluation of OTP weight genomes against a set of origin-destination pairs.

Pieces:
- OTPClient: thread-pooled planConnection client with an on-disk JSONL cache.
- itinerary_metrics / pick_itinerary: per-itinerary metrics and route choice.
- compute_baselines / constraint_violation: fastest KMK+walk baseline and the
  "not much slower than the fastest" constraint.
- make_evaluator: batch evaluator for NSGA-II (F, cv, details).

The genome decoder is injected (make_evaluator(..., decode=...)), so this module
does not depend on genome.py. Standard library + numpy only.

CLI (live OTP smoke/benchmark):
    python3 -m optimizer.evaluate [--url ...] [--no-cache]
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

DEFAULT_URL = "http://localhost:8080/otp/gtfs/v1"
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "otp_cache.jsonl")
DEFAULT_OD_PAIRS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "od_pairs.json")
ARRIVE_BY = "2026-10-05T08:30:00+02:00"

# Active MET values only: transit legs (sitting/standing) count as 0 active kcal.
MET_ACTIVE = {"WALK": 3.5, "BICYCLE": 7.0}
STEP_FACTOR = 0.415  # step length = 0.415 * height[m]

NO_ROUTE_PENALTY = 60.0  # constraint violation [min] for a pair without any itinerary

QUERY = """
query Plan($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
           $arriveBy: OffsetDateTime!, $modes: PlanModesInput, $prefs: PlanPreferencesInput) {
  planConnection(origin: $from, destination: $to, dateTime: { latestArrival: $arriveBy },
                 modes: $modes, preferences: $prefs, first: 3) {
    routingErrors { code }
    edges { node {
      start end duration generalizedCost walkDistance elevationGained
      legs { mode duration distance }
    } }
  }
}"""

BASELINE_TRANSIT = {
    "modes": {"transitOnly": True,
              "transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}},
    "preferences": None,
}
BASELINE_WALK = {"modes": {"direct": ["WALK"], "directOnly": True}, "preferences": None}


def _loc(p):
    return {"label": p.get("label", ""),
            "location": {"coordinate": {"latitude": p["lat"], "longitude": p["lon"]}}}


def build_payload(origin, destination, modes, preferences, arrive_by=ARRIVE_BY):
    """GraphQL request body (query + variables) for one planConnection call."""
    return {"query": QUERY,
            "variables": {"from": _loc(origin), "to": _loc(destination), "arriveBy": arrive_by,
                          "modes": modes, "prefs": preferences}}


def cache_key(payload):
    """sha1 of the canonical JSON of the request (query + variables, sorted keys)."""
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


class OTPClient:
    """planConnection client: urllib + ThreadPoolExecutor, 1 retry, JSONL disk cache."""

    def __init__(self, url=DEFAULT_URL, cache_path=DEFAULT_CACHE, workers=6, timeout=60,
                 arrive_by=ARRIVE_BY):
        self.url = url
        self.cache_path = cache_path
        self.workers = workers
        self.timeout = timeout
        self.arrive_by = arrive_by
        self.stats = {"hits": 0, "misses": 0, "errors": 0}
        self._cache = {}
        self._lock = threading.Lock()
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # tolerate a truncated last line
                    self._cache[rec["key"]] = rec["result"]

    def reset_stats(self):
        with self._lock:
            self.stats = {"hits": 0, "misses": 0, "errors": 0}

    def _bump(self, name):
        with self._lock:
            self.stats[name] += 1

    def _post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def _store(self, key, result):
        with self._lock:
            self._cache[key] = result
            if self.cache_path:
                os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
                with open(self.cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "result": result}, ensure_ascii=False) + "\n")

    def plan(self, origin, destination, modes, preferences=None):
        """Parsed planConnection dict ({"edges", "routingErrors"}) or {"error": msg}.

        Errors (network, GraphQL) are not cached so a later run can retry them.
        """
        payload = build_payload(origin, destination, modes, preferences, self.arrive_by)
        key = cache_key(payload)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            self._bump("hits")
            return cached
        self._bump("misses")
        last_err = None
        for _attempt in range(2):  # one retry
            try:
                res = self._post(payload)
            except (urllib.error.URLError, OSError, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
                continue
            if res.get("errors"):
                last_err = "GraphQL: " + res["errors"][0].get("message", "?")
                break  # deterministic error, no point retrying
            result = res["data"]["planConnection"]
            self._store(key, result)
            return result
        self._bump("errors")
        return {"error": last_err}

    def plan_many(self, requests):
        """Run many plan() calls in parallel, preserving order.

        Each request is a dict {"origin", "destination", "modes", "preferences"}
        or a tuple (origin, destination, modes, preferences). Identical requests
        within one batch are sent once and share the result.
        """
        def norm(r):
            if isinstance(r, dict):
                return (r["origin"], r["destination"], r.get("modes"), r.get("preferences"))
            return tuple(r)

        if not requests:
            return []
        normed = [norm(r) for r in requests]
        keys = [cache_key(build_payload(*r, self.arrive_by)) for r in normed]
        unique = {}
        for k, r in zip(keys, normed):
            unique.setdefault(k, r)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            out = dict(zip(unique, ex.map(lambda r: self.plan(*r), unique.values())))
        return [out[k] for k in keys]


def itinerary_metrics(itin, weight=70.0, height=1.75):
    """Duration, active kcal, steps, active minutes, generalized cost and leg modes."""
    kcal = 0.0
    active_s = 0.0
    walk_m = 0.0
    modes = []
    for leg in itin.get("legs") or []:
        mode = leg.get("mode")
        modes.append(mode)
        dur = float(leg.get("duration") or 0.0)
        met = MET_ACTIVE.get(mode)
        if met is not None:
            kcal += met * weight * dur / 3600.0
            active_s += dur
        if mode == "WALK":
            walk_m += float(leg.get("distance") or 0.0)
    return {
        "duration_min": float(itin.get("duration") or 0.0) / 60.0,
        "active_kcal": kcal,
        "steps": walk_m / (STEP_FACTOR * height),
        "active_min": active_s / 60.0,
        "generalized_cost": itin.get("generalizedCost"),
        "modes": modes,
    }


def _walking_better(plan_result):
    """True when OTP found no itinerary because walking beats transit."""
    if not plan_result or "error" in plan_result or _itineraries(plan_result):
        return False
    return any(e.get("code") == "WALKING_BETTER_THAN_TRANSIT"
               for e in plan_result.get("routingErrors") or [])


def walk_fallback_request(origin, destination, query):
    """Direct-walk request used when transit loses to walking; keeps the request's walk speed (fixed in genome.py)."""
    speed = (((query or {}).get("preferences") or {}).get("street") or {}).get("walk", {}).get("speed")
    prefs = {"street": {"walk": {"speed": speed}}} if speed is not None else None
    return {"origin": origin, "destination": destination, **BASELINE_WALK, "preferences": prefs}


def _itineraries(plan_result):
    if not plan_result or "error" in plan_result:
        return []
    return [e["node"] for e in plan_result.get("edges") or [] if e.get("node")]


def pick_itinerary(plan_result):
    """Itinerary with the lowest generalizedCost (what OTP itself considers best)."""
    its = _itineraries(plan_result)
    if not its:
        return None
    return min(its, key=lambda it: it.get("generalizedCost")
               if it.get("generalizedCost") is not None else float("inf"))


def _fastest(plan_result):
    its = _itineraries(plan_result)
    return min(its, key=lambda it: it["duration"]) if its else None


def compute_baselines(client, od_pairs):
    """pair_id -> fastest KMK+walk duration [min]; falls back to direct walk.

    Pairs with neither transit nor walk route are omitted (and reported by the caller).
    """
    reqs = [{"origin": p["from"], "destination": p["to"], **BASELINE_TRANSIT} for p in od_pairs]
    results = client.plan_many(reqs)
    baselines = {}
    missing = []
    for p, res in zip(od_pairs, results):
        it = _fastest(res)
        if it is None:
            missing.append(p)
        else:
            baselines[p["id"]] = it["duration"] / 60.0
    if missing:
        walk = client.plan_many([{"origin": p["from"], "destination": p["to"], **BASELINE_WALK}
                                 for p in missing])
        for p, res in zip(missing, walk):
            it = _fastest(res)
            if it is not None:
                baselines[p["id"]] = it["duration"] / 60.0
    return baselines


def constraint_violation(duration_min, baseline_min):
    """Minutes beyond baseline + max(15 min, 50% of baseline); no route -> 60."""
    if duration_min is None:
        return NO_ROUTE_PENALTY
    allowed = baseline_min + max(15.0, 0.5 * baseline_min)
    return max(0.0, duration_min - allowed)


def make_evaluator(od_pairs, baselines, client, decode, weight=70.0, height=1.75):
    """Return evaluate_batch(X) -> (F [k,2], cv [k], details list).

    F[i] = [mean(duration/baseline), -mean(active_kcal)], both minimized.
    A pair without a route counts as duration = 2*baseline in F and 60 in cv.
    """
    pairs = [p for p in od_pairs if p["id"] in baselines]
    if len(pairs) != len(od_pairs):
        missing = [p["id"] for p in od_pairs if p["id"] not in baselines]
        raise ValueError(f"no baseline for pairs: {missing}")

    def evaluate_batch(X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        k = X.shape[0]
        queries = [decode(x) for x in X]
        reqs = [{"origin": p["from"], "destination": p["to"],
                 "modes": q.get("modes"), "preferences": q.get("preferences")}
                for q in queries for p in pairs]
        results = client.plan_many(reqs)

        # WALKING_BETTER_THAN_TRANSIT: the app would show the walking route, so
        # evaluate that instead of penalizing the pair as "no route".
        fb_idx = [r for r, res in enumerate(results) if _walking_better(res)]
        fallback = {}
        if fb_idx:
            n_pairs = len(pairs)
            fb_reqs = [walk_fallback_request(pairs[r % n_pairs]["from"], pairs[r % n_pairs]["to"],
                                             queries[r // n_pairs]) for r in fb_idx]
            fallback = dict(zip(fb_idx, client.plan_many(fb_reqs)))

        F = np.zeros((k, 2))
        cv = np.zeros(k)
        details = []
        n = len(pairs)
        for i in range(k):
            ratios, kcals, steps, durs, cvs, per_pair = [], [], [], [], [], []
            for j, p in enumerate(pairs):
                base = baselines[p["id"]]
                fb = None
                it = pick_itinerary(results[i * n + j])
                if it is None and (i * n + j) in fallback:
                    it = pick_itinerary(fallback[i * n + j])
                    fb = "walk" if it is not None else None
                if it is None:
                    dur, kcal, st, modes = 2.0 * base, 0.0, 0.0, []
                    c = NO_ROUTE_PENALTY
                    found = False
                else:
                    m = itinerary_metrics(it, weight=weight, height=height)
                    dur, kcal, st, modes = m["duration_min"], m["active_kcal"], m["steps"], m["modes"]
                    c = constraint_violation(dur, base)
                    found = True
                ratios.append(dur / base if base > 0 else 1.0)
                kcals.append(kcal)
                steps.append(st)
                durs.append(dur)
                cvs.append(c)
                per_pair.append({"pair_id": p["id"], "duration_min": round(dur, 2),
                                 "active_kcal": round(kcal, 2), "steps": round(st),
                                 "modes": modes, "found": found, "fallback": fb})
            F[i, 0] = float(np.mean(ratios))
            F[i, 1] = -float(np.mean(kcals))
            cv[i] = float(np.mean(cvs))
            details.append({
                "query": queries[i],
                "f_time_ratio": F[i, 0],
                "active_kcal": float(np.mean(kcals)),
                "steps": float(np.mean(steps)),
                "duration_min": float(np.mean(durs)),
                "cv": cv[i],
                "per_pair": per_pair,
            })
        return F, cv, details

    return evaluate_batch


def load_od_pairs(path=DEFAULT_OD_PAIRS, quick=False):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    pairs = d["pairs"]
    if quick:
        ids = set(d["quick"])
        pairs = [p for p in pairs if p["id"] in ids]
    return pairs


def main():
    """Live check: baselines, cache hit rate and throughput."""
    import argparse
    ap = argparse.ArgumentParser(description="OTP evaluator smoke test / benchmark")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    pairs = load_od_pairs()
    client = OTPClient(args.url, cache_path=args.cache, workers=args.workers)
    t0 = time.perf_counter()
    baselines = compute_baselines(client, pairs)
    print(f"baselines ({time.perf_counter() - t0:.2f} s, {client.stats}):")
    for p in pairs:
        print(f"  {p['id']:<28} {baselines.get(p['id'], float('nan')):6.1f} min")


if __name__ == "__main__":
    main()
