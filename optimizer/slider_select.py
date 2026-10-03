"""Online "time <-> activity" slider for ONE user route (library for the backend).

Offline, the GA produces a ``slider.json`` ({"meta", "ticks"}): n weight profiles ("ticks")
spread along the Pareto front. Online, for a concrete origin/destination/deadline:

Backend entry point (does all of the below)::

    route_slider = plan_route_slider(slider, origin, destination, deadline,
                                     walk_speed=user_walk_speed, weight=user_kg, height=user_m,
                                     lock_reason="smog" if bad_air else None)

Steps inside:

1. ``tick_requests(slider, origin, destination)`` -> n tick requests + ``anchor`` (plain KMK
   with default weights, ``BASELINE_TRANSIT``) + ``walk`` (direct walk, ``BASELINE_WALK``);
2. ``OTPClient(arrive_by=query_arrive_by(deadline, buffer_min), query=ROUTE_QUERY)
   .plan_many(requests)`` (ROUTE_QUERY adds leg geometry, line numbers and stop names);
3. ``build_route_slider(results, requests, deadline)`` -> deduplicated, non-dominated
   positions with slider coordinates ``s`` in [0, 1] (0 = fastest, 1 = most active),
   lock / transit fallback, ``dropped`` counters and ``warnings``.

Smog / weather data are NOT fetched here: the caller decides and passes ``lock_reason``.

CLI (live OTP demo):
    python3 -m optimizer.slider_select --slider PATH (--pair ID | --from lat,lon --to lat,lon)
        [--deadline ISO] [--no-cache | --cache PATH] [--lock smog] [--workers 8] [--url URL]
        exit 2 when every OTP request failed.

Standard library only (+ optimizer.evaluate).
"""
import argparse
import copy
import datetime
import hashlib
import json
import math
import sys
import time

from optimizer.evaluate import (BASELINE_TRANSIT, BASELINE_WALK, DEFAULT_OD_PAIRS, DEFAULT_URL,
                                QUERY, OTPClient, constraint_violation, itineraries,
                                itinerary_metrics, load_od_pairs, pick_itinerary)

try:  # T3: offline slider module; same arc-length algorithm. Optional at import time.
    from optimizer.slider import arc_positions as _slider_arc_positions
except Exception:  # noqa: BLE001 - module missing or broken -> local implementation
    _slider_arc_positions = None

DROP_KEYS = ("late", "too_long", "no_route", "error", "duplicate", "dominated")

# evaluate.QUERY + the leg fields the UI needs (map geometry, line numbers, stop names, realtime).
# Checked against the OTP 2.10 schema. Different text -> different cache keys than the GA.
_LEGS_GA = "legs { mode duration distance }"
_LEGS_UI = """legs { mode duration distance
        start { scheduledTime estimated { time delay } } end { scheduledTime }
        from { name lat lon } to { name lat lon }
        route { shortName } legGeometry { points } realTime }"""
assert _LEGS_GA in QUERY
ROUTE_QUERY = QUERY.replace(_LEGS_GA, _LEGS_UI)


# ---------------------------------------------------------------- requests

def _set_speed(req, walk_speed, bike_speed):
    """Override user speeds in place on an already deep-copied request."""
    if walk_speed is None and bike_speed is None:
        return
    prefs = req.get("preferences") or {}
    street = prefs.setdefault("street", {})
    if walk_speed is not None:
        street.setdefault("walk", {})["speed"] = float(walk_speed)
    # Bike speed only where a bicycle can be used: adding it to a walk/transit-only request
    # would not change the route but would change the cache key.
    if bike_speed is not None and ("bicycle" in street or "BICYCLE" in json.dumps(req.get("modes"))):
        street.setdefault("bicycle", {})["speed"] = float(bike_speed)
    req["preferences"] = prefs


def tick_requests(slider, origin, destination, include_anchor=True, include_walk=True,
                  walk_speed=None, bike_speed=None):
    """OTP requests for all slider ticks of one route, ready for ``OTPClient.plan_many``.

    Returns a list of dicts ``{"tag", "origin", "destination", "modes", "preferences"}`` in the
    order: n ticks (``tag`` = ``"tick:i"``), ``"anchor"`` (plain KMK, default weights) and
    ``"walk"`` (direct walk). ``plan_many`` reads only origin/destination/modes/preferences, so
    the extra ``tag`` key is ignored both by the request and by the cache key (checked in tests);
    identical ticks (a front with fewer distinct points than n) are sent to OTP once.

    The deadline is not part of a request: ``OTPClient`` has one ``arrive_by`` per client, so
    create the client with ``arrive_by=query_arrive_by(deadline, buffer_min)``.

    ``walk_speed`` / ``bike_speed`` [m/s] override the fixed GA speeds with the user's own; they
    are applied to deep copies, the input ``slider`` is never modified.
    """
    reqs = []
    for i, tick in enumerate(slider["ticks"]):
        reqs.append({"tag": f"tick:{i}", "origin": origin, "destination": destination,
                     "modes": copy.deepcopy(tick.get("modes")),
                     "preferences": copy.deepcopy(tick.get("preferences"))})
    if include_anchor:
        reqs.append({"tag": "anchor", "origin": origin, "destination": destination,
                     **copy.deepcopy(BASELINE_TRANSIT)})
    if include_walk:
        reqs.append({"tag": "walk", "origin": origin, "destination": destination,
                     **copy.deepcopy(BASELINE_WALK)})
    for r in reqs:
        _set_speed(r, walk_speed, bike_speed)
    return reqs


# ---------------------------------------------------------------- helpers

def _parse_dt(value):
    """Timezone-aware datetime from a datetime or an ISO string (``Z`` accepted)."""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"datetime without timezone: {value!r}")
    return dt


def query_arrive_by(deadline, buffer_min=3.0):
    """ISO ``latestArrival`` for OTP: deadline minus the safety buffer.

    Querying with the bare deadline would make OTP return routes arriving at e.g. 08:29 for an
    08:30 deadline, all of which ``build_route_slider`` then drops as ``late``.
    """
    return (_parse_dt(deadline) - datetime.timedelta(minutes=buffer_min)).isoformat()


def _leg_line(leg):
    route = leg.get("route")
    if isinstance(route, dict):
        return route.get("shortName")
    return leg.get("line")


def route_signature(itin):
    """Per leg: (mode, round(duration/30 s), round(distance/50 m)) + line number when present."""
    sig = []
    for leg in itin.get("legs") or []:
        part = (leg.get("mode"), round(float(leg.get("duration") or 0.0) / 30.0),
                round(float(leg.get("distance") or 0.0) / 50.0))
        line = _leg_line(leg)
        sig.append(part + (line,) if line is not None else part)
    return tuple(sig)


def route_key(signature):
    """Short stable id of a route signature."""
    return hashlib.sha1(json.dumps(signature).encode("utf-8")).hexdigest()[:12]


def _arc_positions_local(points):
    """Arc-length positions of points already sorted by time (same algorithm as slider.py).

    ``points``: dicts with ``f_time_ratio`` and ``active_kcal``. Both are normalized to [0, 1]
    within the set; s = cumulative Euclidean length / total length. 1 point -> [0.0].
    """
    if not points:
        return []
    if len(points) == 1:
        return [0.0]
    pts = sorted(points, key=lambda p: p["f_time_ratio"])

    def norm(vals):
        lo, hi = min(vals), max(vals)
        return [(v - lo) / (hi - lo) if hi > lo else 0.0 for v in vals]

    xs = norm([p["f_time_ratio"] for p in pts])
    ys = norm([p["active_kcal"] for p in pts])
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    total = cum[-1]
    if total <= 0:
        return [i / (len(pts) - 1) for i in range(len(pts))]
    return [c / total for c in cum]


def _arc_positions(points):
    """slider.arc_positions when available and sane, else the local implementation.

    Points are passed sorted by time, so "sorted output" and "input order output" coincide.
    """
    if _slider_arc_positions is not None:
        try:
            s = [float(v) for v in _slider_arc_positions(points)]
            if len(s) == len(points) and all(0.0 <= v <= 1.0 + 1e-9 for v in s):
                return s
        except Exception:  # noqa: BLE001 - incompatible API -> local fallback
            pass
    return _arc_positions_local(points)


# ---------------------------------------------------------------- slider

FASTEST_TAGS = ("anchor", "walk")  # reference routes: fastest itinerary, like compute_baselines


def _fastest(plan_result):
    """Itinerary with minimal duration (ties -> lower generalizedCost); None when there is none."""
    its = [it for it in itineraries(plan_result) if it.get("duration") is not None]
    if not its:
        return None
    return min(its, key=lambda it: (it["duration"], it.get("generalizedCost")
                                    if it.get("generalizedCost") is not None else float("inf")))


def _position(c, s, deadline, locked, fallback=False):
    m = c["m"]
    return {
        "s": round(s, 4),
        "route_key": route_key(c["sig"]),
        "sources": c["sources"],
        "metrics": {
            "duration_min": round(m["duration_min"], 2),
            "active_kcal": round(m["active_kcal"], 1),
            "steps": int(round(m["steps"])),
            "end": c["itin"]["end"],
            "slack_min": round((deadline - c["end"]).total_seconds() / 60.0, 1),
            "modes": m["modes"],
        },
        "itinerary": c["itin"],
        "locked": locked,
        "fallback": fallback,
    }


def _front_s(front, base):
    pts = [{"f_time_ratio": c["m"]["duration_min"] / base if base else c["m"]["duration_min"],
            "active_kcal": c["m"]["active_kcal"]} for c in front]
    return _arc_positions(pts)


def build_route_slider(results, requests, deadline, baseline_min=None, *, weight=70.0,
                       height=1.75, buffer_min=3.0, lock_reason=None, lock_above_s=0.5):
    """Local slider for one route from the OTP answers to ``tick_requests``.

    ``results[i]`` answers ``requests[i]`` (``plan_many`` order). Steps:

    1. ``baseline_min`` (if not given): fastest itinerary of the ``anchor`` answer, else of the
       ``walk`` answer; when neither exists the ``too_long`` check is skipped (warning).
    2. Per tick answer the itinerary with minimal ``generalizedCost`` (what OTP itself would
       show); for the reference answers ``anchor`` / ``walk`` the fastest one (min duration,
       the "Najszybsza" card, consistent with the baseline and ``compute_baselines``).
       OTP/network error -> ``error``; no itinerary -> ``no_route``.
    3. ``end > deadline - buffer_min`` -> ``late``; ``constraint_violation > 0`` (slower than
       190% of the baseline, ``evaluate.MAX_TIME_RATIO``) -> ``too_long``.
    4. Merge equal ``route_signature`` -> one position with all ``sources`` (``duplicate``
       counts the merged-away answers); the itinerary of the first source is kept.
    5. Sort by (duration, -kcal), keep the non-dominated ones (time min, kcal max; equal kcal
       with longer time counts as dominated -> ``dominated``), s by arc length.

    Without ``lock_reason``: nothing is locked, ``default_index`` = position with s closest
    to 0.5 (ties -> faster), ``fallback`` is False everywhere.

    With ``lock_reason`` (smog / weather: CLAUDE.md "do not promote bike/walk"):

    - ``locked = s > lock_above_s`` for every regular position;
    - the plain-transit route (the position whose ``sources`` contain ``"anchor"``) is always
      offered unlocked and is the default. If it was dominated (the usual case for a bike
      slider) or its s exceeds ``lock_above_s``, it is added as a ``"fallback": True``
      position at s = 0 placed first, and the regular positions are shifted to
      ``s' = d + (1 - d) * s`` with ``d = 1 / (m + 1)`` (m regular positions), so s stays
      sorted and unique; ``locked`` is computed on the shifted s. A resurrected dominated
      anchor is not counted in ``dropped["dominated"]``.
    - Other unlocked positions (``active_kcal > 0``, s <= lock_above_s) stay selectable but
      are never the default.
    - Without a usable anchor route (late / too long / no route) the shortest walk (``walk``
      answer, already the fastest direct route) takes over exactly the anchor's role: same
      ``fallback`` / s = 0 / default mechanism (and a warning). Rationale: a short walk means
      less effort and shorter exposure than a longer bike ride with high ventilation, so a bike
      is never the default under a lock when an alternative exists.
    - Without anchor and walk the default is the least active unlocked position WITHOUT a
      BICYCLE leg; if every unlocked position has one, the least active unlocked one. Either
      way a warning is added.

    Invariant: ``sum(len(p["sources"])) + sum(dropped.values()) == len(requests)``.

    ``warnings``: human-readable diagnostics (Polish, may be shown to developers / logged), e.g.
    OTP unavailable, partial OTP errors, all routes late just before the deadline (query made
    without ``query_arrive_by``), no baseline, lock without a transit route.

    ``deadline``: timezone-aware datetime or ISO string.
    """
    if len(results) != len(requests):
        raise ValueError("results and requests must have the same length")
    deadline = _parse_dt(deadline)
    limit = deadline - datetime.timedelta(minutes=buffer_min)
    tags = [r.get("tag", f"req:{i}") if isinstance(r, dict) else f"req:{i}"
            for i, r in enumerate(requests)]
    warnings = []

    if baseline_min is None:
        for want in ("anchor", "walk"):
            durs = [it["duration"] / 60.0 for tag, res in zip(tags, results) if tag == want
                    for it in itineraries(res) if it.get("duration") is not None]
            if durs:
                baseline_min = min(durs)
                break

    dropped = {k: 0 for k in DROP_KEYS}
    errors = []
    late_ends = []
    groups = {}  # signature -> candidate (insertion order = request order)
    for tag, res in zip(tags, results):
        if not isinstance(res, dict) or "error" in res:
            dropped["error"] += 1
            errors.append(str(res.get("error")) if isinstance(res, dict) else repr(res))
            continue
        it = _fastest(res) if tag in FASTEST_TAGS else pick_itinerary(res)
        if it is None:
            dropped["no_route"] += 1
            continue
        end = _parse_dt(it["end"]) if it.get("end") else None
        if end is None or end > limit:
            dropped["late"] += 1
            if end is not None:
                late_ends.append(end)
            continue
        m = itinerary_metrics(it, weight=weight, height=height)
        if baseline_min is not None and constraint_violation(m["duration_min"], baseline_min) > 0:
            dropped["too_long"] += 1
            continue
        sig = route_signature(it)
        if sig in groups:
            groups[sig]["sources"].append(tag)
            dropped["duplicate"] += 1
            continue
        groups[sig] = {"sig": sig, "sources": [tag], "itin": it, "m": m, "end": end}

    cands = sorted(groups.values(), key=lambda c: (c["m"]["duration_min"], -c["m"]["active_kcal"]))
    front = []
    best_kcal = -math.inf
    for c in cands:
        if c["m"]["active_kcal"] > best_kcal:
            front.append(c)
            best_kcal = c["m"]["active_kcal"]
        else:
            dropped["dominated"] += 1

    base = baseline_min if baseline_min else None
    s_vals = _front_s(front, base)
    locking = lock_reason is not None
    positions = []
    default_index = None

    if not locking:
        positions = [_position(c, s, deadline, False) for c, s in zip(front, s_vals)]
        best = None
        for i, p in enumerate(positions):
            d = abs(p["s"] - 0.5)
            if best is None or d < best - 1e-12:
                best, default_index = d, i
    else:
        # reference route = plain transit; without it the shortest walk (see docstring)
        ref_tag = "anchor"
        anchor = next((c for c in groups.values() if "anchor" in c["sources"]), None)
        if anchor is None:
            ref_tag = "walk"
            anchor = next((c for c in groups.values() if "walk" in c["sources"]), None)
        fallback = None
        if anchor is not None:
            in_front = next((i for i, c in enumerate(front) if c is anchor), None)
            if in_front is None:
                fallback = anchor
                dropped["dominated"] -= 1
            elif round(s_vals[in_front], 4) > lock_above_s:
                fallback = anchor
                front = [c for c in front if c is not anchor]
                s_vals = _front_s(front, base)
        if fallback is not None:
            d = 1.0 / (len(front) + 1)
            positions.append(_position(fallback, 0.0, deadline, False, fallback=True))
            s_vals = [d + (1.0 - d) * s for s in s_vals]
        for c, s in zip(front, s_vals):
            positions.append(_position(c, s, deadline, round(s, 4) > lock_above_s))
        if anchor is not None:
            default_index = next(i for i, p in enumerate(positions) if ref_tag in p["sources"])
            if ref_tag == "walk":
                warnings.append(f"Blokada '{lock_reason}', brak trasy samą komunikacją — "
                                "domyślna pozycja to najkrótszy spacer (nie rower).")
        else:
            free = [i for i, p in enumerate(positions) if not p["locked"]]
            no_bike = [i for i in free if "BICYCLE" not in (positions[i]["metrics"]["modes"] or [])]
            pool = no_bike or free
            if pool:
                default_index = min(pool, key=lambda i: (positions[i]["metrics"]["active_kcal"],
                                                         positions[i]["s"]))
            if no_bike:
                note = "domyślna pozycja to najmniej aktywna dostępna bez roweru."
            else:
                note = ("brak dostępnej pozycji bez roweru — domyślna to najmniej aktywna "
                        "dostępna (rowerowa).")
            warnings.append(f"Blokada '{lock_reason}', ale brak trasy samą komunikacją "
                            f"ani spaceru (anchor i walk odrzucone lub bez trasy) — {note}")

    n = len(requests)
    if n and dropped["error"] == n:
        warnings.append(f"OTP niedostępny: wszystkie {n} zapytań zakończyły się błędem "
                        f"({errors[0]}).")
    elif dropped["error"]:
        warnings.append(f"{dropped['error']}/{n} zapytań OTP zakończyło się błędem ({errors[0]}).")
    if late_ends and not groups and dropped["too_long"] == 0:
        latest = max(late_ends)
        if limit < latest <= deadline:
            warnings.append("Wszystkie trasy odrzucone jako spóźnione, a najpóźniejsza kończy się "
                            f"{latest.isoformat()} — w buforze {buffer_min:g} min przed terminem. "
                            "Prawdopodobnie zapytanie OTP bez query_arrive_by(deadline, buffer_min).")
        else:
            warnings.append("Wszystkie trasy kończą się po terminie minus bufor.")
    if baseline_min is None and n and dropped["error"] < n:
        warnings.append("Brak baseline (brak trasy anchor i walk) — pominięto filtr too_long.")

    return {"positions": positions, "default_index": default_index, "lock_reason": lock_reason,
            "dropped": dropped,
            "baseline_min": round(baseline_min, 2) if baseline_min is not None else None,
            "warnings": warnings}


def plan_route_slider(slider, origin, destination, deadline, *, url=DEFAULT_URL, buffer_min=3.0,
                      workers=8, cache_path=None, lock_reason=None, walk_speed=None,
                      bike_speed=None, weight=70.0, height=1.75, lock_above_s=0.5, client=None):
    """Single backend entry point: requests -> OTP -> ``build_route_slider`` result.
    Creates ``OTPClient(url, arrive_by=query_arrive_by(deadline, buffer_min), query=ROUTE_QUERY)``
    (``client`` may be injected, e.g. in tests; its ``arrive_by``/``query`` are then the
    caller's responsibility). ``cache_path=None`` = no disk cache (default for live requests).
    Adds ``"otp_stats"`` (hits/misses/errors) and ``"n_requests"`` to the result.
    """
    if client is None:
        client = OTPClient(url, cache_path=cache_path, workers=workers,
                           arrive_by=query_arrive_by(deadline, buffer_min), query=ROUTE_QUERY)
    reqs = tick_requests(slider, origin, destination, walk_speed=walk_speed, bike_speed=bike_speed)
    results = client.plan_many(reqs)
    rs = build_route_slider(results, reqs, deadline, weight=weight, height=height,
                            buffer_min=buffer_min, lock_reason=lock_reason,
                            lock_above_s=lock_above_s)
    rs["otp_stats"] = dict(client.stats)
    rs["n_requests"] = len(reqs)
    return rs


# ---------------------------------------------------------------- CLI

def _latlon(text):
    lat, lon = (float(v) for v in text.split(","))
    return {"lat": lat, "lon": lon}


def _short_modes(itin):
    out = []
    for leg in itin.get("legs") or []:
        m = leg.get("mode")
        line = _leg_line(leg)
        label = f"{m}({line})" if line else m
        if not out or out[-1] != label:
            out.append(label)
    return "+".join(out)


def print_route_slider(rs, file=None):
    file = file or sys.stdout
    print(f"baseline {rs['baseline_min']} min, lock: {rs['lock_reason']}, "
          f"default_index: {rs['default_index']}, dropped: {rs['dropped']}", file=file)
    print(f"{'#':>2} {'s':>6} {'czas':>6} {'zapas':>6} {'kcal':>6} {'kroki':>6}  "
          f"{'tryby':<36} źródła", file=file)
    for i, p in enumerate(rs["positions"]):
        m = p["metrics"]
        marks = []
        if i == rs["default_index"]:
            marks.append("*domyślna")
        if p.get("fallback"):
            marks.append("[fallback pieszo]" if "walk" in p.get("sources", []) else "[fallback KMK]")
        if p["locked"]:
            marks.append("[zablok.]")
        print(f"{i:>2} {p['s']:>6.3f} {m['duration_min']:>6.1f} {m['slack_min']:>6.1f} "
              f"{m['active_kcal']:>6.0f} {m['steps']:>6d}  {_short_modes(p['itinerary']):<36} "
              f"{','.join(p['sources'])} {' '.join(marks)}".rstrip(), file=file)
    for w in rs.get("warnings") or []:
        print(f"UWAGA: {w}", file=file)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Live route slider for one origin/destination")
    ap.add_argument("--slider", required=True, help="slider.json ({meta, ticks})")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--pair", help="pair id from od_pairs.json")
    where.add_argument("--from", dest="origin", help="lat,lon")
    ap.add_argument("--to", dest="destination", help="lat,lon (with --from)")
    ap.add_argument("--deadline", help="ISO arrival deadline with timezone "
                                       "(default for --pair: od_pairs meta.arrive_by)")
    ap.add_argument("--buffer", type=float, default=3.0, help="safety buffer [min]")
    ap.add_argument("--lock", default=None, help="lock reason, e.g. smog / weather")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--cache", default=None, help="JSONL disk cache (default: none)")
    ap.add_argument("--no-cache", action="store_true", help="ignore --cache (default anyway)")
    ap.add_argument("--json", dest="json_out", help="also write the result to this path")
    args = ap.parse_args(argv)

    with open(args.slider, encoding="utf-8") as f:
        slider = json.load(f)

    if args.pair:
        with open(DEFAULT_OD_PAIRS, encoding="utf-8") as f:
            default_deadline = json.load(f)["meta"].get("arrive_by")
        pairs = {p["id"]: p for p in load_od_pairs()}
        if args.pair not in pairs:
            ap.error(f"unknown pair {args.pair!r}; known: {', '.join(pairs)}")
        origin, destination = pairs[args.pair]["from"], pairs[args.pair]["to"]
        deadline = args.deadline or default_deadline
    else:
        if not args.destination or not args.deadline:
            ap.error("--from requires --to and --deadline")
        origin, destination = _latlon(args.origin), _latlon(args.destination)
        deadline = args.deadline

    t0 = time.perf_counter()
    rs = plan_route_slider(slider, origin, destination, deadline, url=args.url,
                           buffer_min=args.buffer, workers=args.workers,
                           cache_path=None if args.no_cache else args.cache,
                           lock_reason=args.lock)
    dt = time.perf_counter() - t0

    print(f"deadline {deadline}, {rs['n_requests']} requests, OTP {rs['otp_stats']}")
    print_route_slider(rs)
    print(f"build time: {dt:.2f} s")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rs, f, ensure_ascii=False, indent=1)
    if rs["n_requests"] and rs["dropped"]["error"] == rs["n_requests"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
