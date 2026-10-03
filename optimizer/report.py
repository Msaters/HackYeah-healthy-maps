"""Report for an NSGA-II run: Pareto front chart (SVG) + profile table (Markdown).

Usage:
    python3 -m optimizer.report PATH/front.json [--profiles PATH/profiles.json]
                                                [--slider PATH/slider.json] [--out DIR]

Writes ``front.svg`` and ``front.md`` into ``--out`` (default: the directory of
front.json). Profiles come from ``--profiles``, else ``profiles.json`` next to
front.json, else they are picked from the front with :func:`pick_profiles`.
Slider ticks ("czas <-> ruch") come from ``--slider``, else ``slider.json`` next
to front.json; without a slider the chart and table have no tick layer.

Stdlib only; the SVG is written by hand (no matplotlib).
"""

import argparse
import json
import math
import os
import sys
from xml.sax.saxutils import escape

PROFILE_KEYS = ("fast", "balanced", "active")
PROFILE_LABELS = {"fast": "Szybki", "balanced": "Zbalansowany", "active": "Aktywny"}

# Palette: first three categorical slots of the validated reference palette
# (blue / orange / aqua pass all-pairs CVD checks); neutrals for the front.
COLORS = {
    "fast": "#2a78d6",
    "balanced": "#eb6834",
    "active": "#1baf7a",
    "front": "#9a9892",
    "front_line": "#c3c2b7",
    "text": "#0b0b0b",
    "text2": "#52514e",
    "muted": "#8a8984",
    "grid": "#ebeae6",
    "axis": "#b8b6ae",
    "bg": "#ffffff",
    "tick": "#3d3c39",
    "track": "#d6d4cc",
}
VARIANT_LABELS = {"bike": "wariant: rower", "walk": "wariant: bez roweru"}
TICK_LEGEND = "ząbek suwaka"
SLIDER_TITLE = "Suwak: czas ↔ ruch"
X_TITLE = "Czas przejazdu względem najszybszej trasy komunikacją (×)"
REF_LABEL = "= czas KMK"
HINT = "↖ lepiej: szybciej i więcej ruchu"
FONT = "Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

W, H = 960, 600
M_LEFT, M_RIGHT, M_TOP, M_BOTTOM = 92, 40, 118, 84


# ---------------------------------------------------------------- profiles

def _num(v):
    """Coerce a metric to float; None for missing / non-numeric / non-finite."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _metric(p, key):
    return _num(p.get(key)) if isinstance(p, dict) else None


def _plottable(p):
    return _metric(p, "f_time_ratio") is not None and _metric(p, "active_kcal") is not None


def _infeasible(p):
    return (_metric(p, "cv") or 0.0) > 0


def _feasible_indices(front):
    ok = [i for i, p in enumerate(front) if _plottable(p)]
    idx = [i for i in ok if not _infeasible(front[i])]
    return idx or ok


def pick_profiles(front):
    """Pick fast / balanced / active indices from a front.

    fast = min f_time_ratio (ties: more kcal), active = max active_kcal
    (ties: lower time), balanced = knee point: max distance from the line
    joining the two extremes, with both axes normalised to [0, 1].
    Feasible points (cv == 0) are preferred when there are any.
    """
    if not front:
        raise ValueError("empty front")
    cand = _feasible_indices(front)
    if not cand:  # no point has usable metrics; keep the API total
        return {"fast": 0, "balanced": 0, "active": 0}
    t = lambda i: _metric(front[i], "f_time_ratio")
    k = lambda i: _metric(front[i], "active_kcal")
    fast = min(cand, key=lambda i: (t(i), -k(i)))
    active = max(cand, key=lambda i: (k(i), -t(i)))

    middle = [i for i in cand if i not in (fast, active)]
    if not middle:
        return {"fast": fast, "balanced": fast if len(cand) == 1 else active, "active": active}

    t0, t1 = min(t(i) for i in cand), max(t(i) for i in cand)
    k0, k1 = min(k(i) for i in cand), max(k(i) for i in cand)
    nt = lambda i: (t(i) - t0) / (t1 - t0) if t1 > t0 else 0.0
    nk = lambda i: (k(i) - k0) / (k1 - k0) if k1 > k0 else 0.0
    ax, ay = nt(fast), nk(fast)
    bx, by = nt(active), nk(active)
    dx, dy = bx - ax, by - ay
    norm = math.hypot(dx, dy)

    def dist(i):
        px, py = nt(i) - ax, nk(i) - ay
        if norm == 0:
            return math.hypot(px, py)
        return abs(dx * py - dy * px) / norm

    balanced = max(middle, key=lambda i: (dist(i), -abs(nt(i) - 0.5)))
    return {"fast": fast, "balanced": balanced, "active": active}


def _match_profile(front, prof):
    """Find the front index whose query equals a profiles.json entry, or None."""
    for i, p in enumerate(front):
        q = p.get("query") or {}
        if q.get("modes") == prof.get("modes") and q.get("preferences") == prof.get("preferences"):
            return i
    return None


def resolve_profiles(front, profiles=None):
    """Return {key: point-dict} for the three profiles.

    With profiles.json, each entry becomes a point built from its query and
    ``metrics`` (falling back to the matching front point when metrics lack a
    field). Without it, :func:`pick_profiles` is used.
    """
    if not profiles:
        idx = pick_profiles(front)
        return {key: front[i] for key, i in idx.items()}
    out = {}
    picked = None
    for key in PROFILE_KEYS:
        prof = profiles.get(key)
        if prof is None:
            picked = picked or pick_profiles(front)
            out[key] = front[picked[key]]
            continue
        i = _match_profile(front, prof)
        base = dict(front[i]) if i is not None else {}
        metrics = prof.get("metrics") or {}
        point = dict(base)
        for f in ("f_time_ratio", "active_kcal", "steps", "duration_min", "cv"):
            if f in metrics:
                point[f] = metrics[f]
        point["query"] = {"modes": prof.get("modes"), "preferences": prof.get("preferences")}
        if not _plottable(point):
            picked = picked or pick_profiles(front)
            fallback = front[picked[key]]
            for f in ("f_time_ratio", "active_kcal"):
                if _metric(point, f) is None:
                    point[f] = fallback.get(f)
        out[key] = point
    return out


# ---------------------------------------------------------------- weights

def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def main_weights(query):
    """Extract the headline OTP weights from a planConnection query."""
    query = query or {}
    modes = query.get("modes") or {}
    prefs = query.get("preferences") or {}
    access = _get(modes, "transit", "access")
    direct = modes.get("direct")
    if modes.get("transitOnly") or not direct:
        direct_s = "brak"
    else:
        direct_s = direct[0]
    return {
        "walk.reluctance": _get(prefs, "street", "walk", "reluctance"),
        "bicycle.reluctance": _get(prefs, "street", "bicycle", "reluctance"),
        "access": access[0] if access else "—",
        "direct": direct_s,
    }


# ---------------------------------------------------------------- formatting

def plural(n, one, few, many):
    """Polish plural form: 1 punkt, 2-4 punkty, 5-21 punktów, 22-24 punkty..."""
    n = abs(int(n))
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def _count(n, one, few, many):
    return f"{n} {plural(n, one, few, many)}"


def _fmt(v, nd=2, suffix=""):
    f = _num(v)
    if f is None:
        return "—"
    return f"{f:.{nd}f}{suffix}".replace(".", ",")


def _fmt_int(v):
    f = _num(v)
    if f is None:
        return "—"
    return f"{int(round(f)):,}".replace(",", "\u00a0")


def _meta_date(meta):
    for key in ("generated", "created", "timestamp", "date", "finished", "started"):
        v = meta.get(key)
        if isinstance(v, str) and v:
            return v[:16].replace("T", " ")
    return None


# ---------------------------------------------------------------- scales

def _nice_step(span, target):
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _ticks(lo, hi, target):
    if hi <= lo:
        hi = lo + 1
    step = _nice_step(hi - lo, target)
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    n = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(n + 1)], step


def _decimals(step):
    if step >= 1:
        return 0
    return max(0, -int(math.floor(math.log10(step) + 1e-9)))


# ---------------------------------------------------------------- label layout

def _text_w(s, size, bold=False):
    # Rough sans-serif width estimate; generous so boxes do not under-reserve.
    return len(s) * size * (0.60 if bold else 0.56)


def _overlap(a, b, pad=0.0):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _place_labels(items, obstacles, bounds, dists=(8, 22, 40, 64, 96, 140)):
    """Greedy placement of label boxes around anchor points.

    items: list of dicts with x, y (anchor), w, h, r (marker radius).
    obstacles: list of boxes (x0, y0, x1, y1) to avoid (markers, legend).
    Returns list of (box, text_anchor_x, baseline_y, needs_leader).
    """
    placed = []
    results = []
    bx0, by0, bx1, by1 = bounds
    for it in items:
        x, y, w, h, r = it["x"], it["y"], it["w"], it["h"], it["r"]
        own = (x - r - 2, y - r - 2, x + r + 2, y + r + 2)
        best = None
        fallback = None  # (score, box, leader) over clamped candidates
        for d in dists:
            dist = r + d
            # Candidate offsets: right, left, above, below, diagonals.
            cands = [
                (x + dist, y - h / 2),
                (x - dist - w, y - h / 2),
                (x - w / 2, y - dist - h),
                (x - w / 2, y + dist),
                (x + dist * 0.7, y - dist * 0.7 - h),
                (x - dist * 0.7 - w, y - dist * 0.7 - h),
                (x + dist * 0.7, y + dist * 0.7),
                (x - dist * 0.7 - w, y + dist * 0.7),
            ]
            for cx, cy in cands:
                box = (cx, cy, cx + w, cy + h)
                inside = not (box[0] < bx0 or box[2] > bx1 or box[1] < by0 or box[3] > by1)
                if inside and not any(_overlap(box, o, 3) for o in obstacles) \
                        and not any(_overlap(box, p, 6) for p in placed):
                    best = (box, d > 30)
                    break
                # Score a clamped version for the last-resort choice.
                kx = min(max(cx, bx0), bx1 - w)
                ky = min(max(cy, by0), by1 - h)
                kbox = (kx, ky, kx + w, ky + h)
                score = (1000 * _overlap(kbox, own, 3)
                         + 50 * sum(_overlap(kbox, p, 6) for p in placed)
                         + sum(_overlap(kbox, o, 3) for o in obstacles)
                         + d / 100)
                if fallback is None or score < fallback[0]:
                    fallback = (score, kbox, True)
            if best:
                break
        if best is None:
            best = fallback[1:]
        placed.append(best[0])
        results.append(best)
    return results


# ---------------------------------------------------------------- slider

def resolve_ticks(front, slider):
    """Return plottable slider ticks as dicts {i, s, index, point}.

    ``point`` carries the tick metrics (``metrics`` of slider.json, completed
    from ``front[index]`` when a field is missing). Ticks that cannot be placed
    on the chart are skipped. ``i`` is the tick number (0..n-1) in s order.
    """
    if not isinstance(slider, dict):
        return []
    raw = slider.get("ticks")
    if not isinstance(raw, list):
        return []
    out = []
    for i, tk in enumerate(raw):
        if not isinstance(tk, dict):
            continue
        idx = tk.get("index")
        base = front[idx] if isinstance(idx, int) and not isinstance(idx, bool) \
            and 0 <= idx < len(front) and isinstance(front[idx], dict) else {}
        point = dict(base)
        metrics = tk.get("metrics") if isinstance(tk.get("metrics"), dict) else {}
        for f in ("f_time_ratio", "active_kcal", "steps", "duration_min"):
            if _num(metrics.get(f)) is not None:
                point[f] = metrics[f]
        s = _num(tk.get("s"))
        if s is None:
            s = i / (len(raw) - 1) if len(raw) > 1 else 0.0
        out.append({"i": i, "s": min(max(s, 0.0), 1.0), "index": idx, "point": point})
    return out


def _tick_groups(ticks, key):
    """Group ticks that land on the same chart point; keeps tick order."""
    groups = []
    for tk in ticks:
        k = key(tk)
        for g in groups:
            if g["key"] == k:
                g["ticks"].append(tk)
                break
        else:
            groups.append({"key": k, "ticks": [tk]})
    return groups


def _tick_clusters(groups, min_dist):
    """Single-linkage clusters of tick groups whose chart points are closer than min_dist px.

    Groups sitting on a profile marker (``profile`` set) stay on their own: their
    big diamond is easy to tell apart and the profile label names them anyway.
    """
    parent = list(range(len(groups)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(groups)):
        for j in range(i):
            if groups[i].get("profile") or groups[j].get("profile"):
                continue
            if math.hypot(groups[i]["x"] - groups[j]["x"], groups[i]["y"] - groups[j]["y"]) < min_dist:
                parent[find(i)] = find(j)
    out = {}
    for i, g in enumerate(groups):
        out.setdefault(find(i), []).append(g)
    return list(out.values())


def _tick_range_label(nums):
    """Compact tick-number label: [2, 3, 4] -> "2–4", [1, 3] -> "1, 3"."""
    nums = sorted(nums)
    parts, start, prev = [], nums[0], nums[0]
    for v in nums[1:] + [None]:
        if v is not None and v == prev + 1:
            prev = v
            continue
        parts.append(str(start) if start == prev else
                     (f"{start}–{prev}" if prev > start + 1 else f"{start}, {prev}"))
        if v is not None:
            start = prev = v
    return ", ".join(parts)


def _variant_label(meta, slider):
    for src in (_get(slider, "meta"), meta):
        v = src.get("variant") if isinstance(src, dict) else None
        if isinstance(v, str) and v:
            return VARIANT_LABELS.get(v, f"wariant: {v}")
    return None


def _leader_ends(it, box):
    """Leader line from a profile marker's edge to the nearest point on its label box."""
    bx0, by0, bx1, by1 = box
    cx = min(max(it["x"], bx0), bx1)
    cy = min(max(it["y"], by0), by1)
    dx, dy = cx - it["x"], cy - it["y"]
    dl = math.hypot(dx, dy) or 1
    ro = 11 + 4.5 * (len(it["keys"]) - 1)
    return (it["x"] + dx / dl * ro, it["y"] + dy / dl * ro), (cx, cy)


def _diamond(x, y, h):
    return f"M{x:.1f},{y - h:.1f} L{x + h:.1f},{y:.1f} L{x:.1f},{y + h:.1f} L{x - h:.1f},{y:.1f} Z"


# ---------------------------------------------------------------- SVG

def render_svg(front, prof_points, meta=None, slider=None):
    meta = meta or {}
    ticks = [t for t in resolve_ticks(front, slider) if _plottable(t["point"])]
    pw = W - M_LEFT - M_RIGHT
    ph = H - M_TOP - M_BOTTOM
    px0, py0 = M_LEFT, M_TOP

    shown = [p for p in front if _plottable(p)]
    prof_shown = {k: p for k, p in prof_points.items() if _plottable(p)}
    all_pts = shown + list(prof_shown.values()) + [t["point"] for t in ticks]
    xs = [_metric(p, "f_time_ratio") for p in all_pts] or [1.0, 1.5]
    ys = [_metric(p, "active_kcal") for p in all_pts] or [0.0, 100.0]
    # Baseline is the fastest transit (KMK + walk) trip, so 1.0x is the
    # reference: always keep it on the axis (bike can be faster, i.e. < 1).
    xlo, xhi = min(min(xs), 1.0), max(max(xs), 1.0)
    ylo, yhi = min(ys), max(ys)
    xpad = max((xhi - xlo) * 0.06, 0.02)
    ypad = max((yhi - ylo) * 0.08, 5)
    # X: padded data range (ratios start near 1.0, rounding out wastes space);
    # Y: kcal is a magnitude, so the axis starts at 0 and ends on a tick.
    x0d, x1d = max(0.0, xlo - xpad), xhi + xpad
    xt, xstep = _ticks(x0d, x1d, 7)
    xt = [v for v in xt if x0d - 1e-9 <= v <= x1d + 1e-9]
    yt, ystep = _ticks(0.0, yhi + ypad, 5)
    y0d, y1d = yt[0], yt[-1]

    sx = lambda v: px0 + (v - x0d) / (x1d - x0d) * pw
    sy = lambda v: py0 + ph - (v - y0d) / (y1d - y0d) * ph

    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'font-family="{escape(FONT)}" role="img" aria-labelledby="title desc">')
    a('<title id="title">Front Pareto: czas vs ruch</title>')
    a(f'<desc id="desc">Front Pareto ({_count(len(front), "punkt", "punkty", "punktów")}): czas przejazdu względem najszybszej '
      'trasy komunikacją oraz aktywne kalorie; wyróżnione profile Szybki, Zbalansowany i Aktywny.</desc>')
    a(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{COLORS["bg"]}"/>')

    # Header
    a(f'<text x="{M_LEFT - 60}" y="46" font-size="26" font-weight="700" fill="{COLORS["text"]}">'
      'Front Pareto: czas vs ruch</text>')
    sub = [_count(len(front), "punkt", "punkty", "punktów") + " frontu"]
    if meta.get("pairs"):
        sub.append(_count(len(meta["pairs"]), "para", "pary", "par") + " źródło–cel")
    variant = _variant_label(meta, slider)
    if variant:
        sub.append(variant)
    if ticks:
        sub.append(_count(len(ticks), "ząbek", "ząbki", "ząbków") + " suwaka")
    d = _meta_date(meta)
    if d:
        sub.append(d)
    a(f'<text x="{M_LEFT - 60}" y="72" font-size="14" fill="{COLORS["text2"]}">'
      f'{escape(" · ".join(sub))}</text>')

    # Legend (top right, one row)
    any_infeasible = any(_infeasible(p) for p in shown)
    legend = [("front", "Front Pareto")]
    if any_infeasible:
        legend.append(("infeasible", "przekracza limit czasu"))
    legend += [(k, PROFILE_LABELS[k]) for k in PROFILE_KEYS]
    if ticks:
        legend.append(("tick", TICK_LEGEND))
    lx = W - M_RIGHT
    entries = []
    for key, label in reversed(legend):
        tw = _text_w(label, 13)
        lx -= tw
        entries.append((key, label, lx))
        lx -= 30
    # One row next to the subtitle; drop to a second row if they would collide.
    sub_right = M_LEFT - 60 + _text_w(" · ".join(sub), 14)
    ly = 66 if lx + 8 > sub_right + 24 else 98
    for key, label, tx in entries:
        cx = tx - 12
        if key == "front":
            a(f'<line x1="{cx - 9}" y1="{ly - 4}" x2="{cx + 9}" y2="{ly - 4}" '
              f'stroke="{COLORS["front_line"]}" stroke-width="2"/>')
            a(f'<circle cx="{cx}" cy="{ly - 4}" r="4" fill="{COLORS["front"]}" '
              f'stroke="{COLORS["bg"]}" stroke-width="1.5"/>')
        elif key == "tick":
            a(f'<path d="{_diamond(cx, ly - 4, 6.5)}" fill="none" stroke="{COLORS["tick"]}" '
              'stroke-width="1.6" stroke-linejoin="round"/>')
        elif key == "infeasible":
            a(f'<circle cx="{cx}" cy="{ly - 4}" r="4" fill="{COLORS["bg"]}" '
              f'stroke="{COLORS["front"]}" stroke-width="1.5"/>')
        else:
            a(f'<circle cx="{cx}" cy="{ly - 4}" r="6.5" fill="{COLORS[key]}" '
              f'stroke="{COLORS["bg"]}" stroke-width="2"/>')
        a(f'<text x="{tx:.1f}" y="{ly}" font-size="13" fill="{COLORS["text2"]}">{escape(label)}</text>')

    # Grid + ticks
    a('<g class="grid">')
    xd = _decimals(xstep)
    yd = _decimals(ystep)
    for v in xt:
        X = sx(v)
        a(f'<line x1="{X:.1f}" y1="{py0}" x2="{X:.1f}" y2="{py0 + ph}" stroke="{COLORS["grid"]}" stroke-width="1"/>')
        a(f'<text x="{X:.1f}" y="{py0 + ph + 22}" font-size="13" text-anchor="middle" '
          f'fill="{COLORS["text2"]}">{_fmt(v, xd)}×</text>')
    for v in yt:
        Y = sy(v)
        a(f'<line x1="{px0}" y1="{Y:.1f}" x2="{px0 + pw}" y2="{Y:.1f}" stroke="{COLORS["grid"]}" stroke-width="1"/>')
        a(f'<text x="{px0 - 10}" y="{Y + 4.5:.1f}" font-size="13" text-anchor="end" '
          f'fill="{COLORS["text2"]}">{_fmt(v, yd)}</text>')
    a('</g>')
    a(f'<line x1="{px0}" y1="{py0 + ph}" x2="{px0 + pw}" y2="{py0 + ph}" stroke="{COLORS["axis"]}" stroke-width="1.5"/>')
    a(f'<line x1="{px0}" y1="{py0}" x2="{px0}" y2="{py0 + ph}" stroke="{COLORS["axis"]}" stroke-width="1.5"/>')

    # Axis titles
    a(f'<text x="{px0 + pw / 2:.1f}" y="{H - 26}" font-size="15" font-weight="600" text-anchor="middle" '
      f'fill="{COLORS["text"]}">{escape(X_TITLE)}</text>')
    a(f'<text transform="translate(28 {py0 + ph / 2:.1f}) rotate(-90)" font-size="15" font-weight="600" '
      f'text-anchor="middle" fill="{COLORS["text"]}">Aktywne kalorie na trasę (kcal, 70 kg)</text>')

    # Direction hint (bottom-right / top-left corner reads as "better = up-left")
    # Keep it clear of the dashed 1.0x line: move it right of the line when the
    # line would cut through it, else give the text a background halo.
    hx, hw = px0 + 12, _text_w(HINT, 12)
    halo = ""
    if x0d <= 1.0 <= x1d and hx - 4 <= sx(1.0) <= hx + hw + 4:
        if sx(1.0) + 10 + hw <= px0 + pw - 8:
            hx = sx(1.0) + 10
        else:
            halo = f' stroke="{COLORS["bg"]}" stroke-width="4" paint-order="stroke"'
    a(f'<text x="{hx:.1f}" y="{py0 + 20}" font-size="12" fill="{COLORS["muted"]}"{halo}>'
      f'{HINT}</text>')
    hint_box = (hx - 4, py0 + 6, hx + hw, py0 + 26)

    # Reference line at 1.0x = fastest transit trip.
    ref_box = None
    if x0d <= 1.0 <= x1d:
        RX = sx(1.0)
        a(f'<line x1="{RX:.1f}" y1="{py0}" x2="{RX:.1f}" y2="{py0 + ph}" stroke="{COLORS["muted"]}" '
          'stroke-width="1.5" stroke-dasharray="5 4"/>')
        rw = _text_w(REF_LABEL, 12)
        ry = py0 + 20
        rbox = (RX + 6, ry - 13, RX + 10 + rw, ry + 4)
        if _overlap(rbox, hint_box, 4):
            ry = py0 + 40
            rbox = (RX + 6, ry - 13, RX + 10 + rw, ry + 4)
        if rbox[2] > px0 + pw:  # too close to the right edge: label on the left
            rbox = (RX - 10 - rw, rbox[1], RX - 6, rbox[3])
        a(f'<text x="{rbox[0] + 2:.1f}" y="{ry}" font-size="12" fill="{COLORS["text2"]}">'
          f'{escape(REF_LABEL)}</text>')
        ref_box = rbox

    # Front line + points
    fx = lambda p: sx(_metric(p, "f_time_ratio"))
    fy = lambda p: sy(_metric(p, "active_kcal"))
    pts = sorted(shown, key=lambda p: (_metric(p, "f_time_ratio"), _metric(p, "active_kcal")))
    if len(pts) > 1:
        path = " ".join(f'{"M" if j == 0 else "L"}{fx(p):.1f},{fy(p):.1f}' for j, p in enumerate(pts))
        a(f'<path d="{path}" fill="none" stroke="{COLORS["front_line"]}" stroke-width="2" '
          'stroke-linejoin="round" stroke-linecap="round"/>')
    a('<g class="front">')
    obstacles = []
    for p in pts:
        X, Y = fx(p), fy(p)
        infeasible = _infeasible(p)
        fill = COLORS["bg"] if infeasible else COLORS["front"]
        a(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="4.5" fill="{fill}" stroke="{COLORS["front"] if infeasible else COLORS["bg"]}" '
          f'stroke-width="1.5"><title>{_fmt(p.get("f_time_ratio"))}× · {_fmt_int(p.get("active_kcal"))} kcal · '
          f'{_fmt_int(p.get("steps"))} kroków</title></circle>')
        obstacles.append((X - 6, Y - 6, X + 6, Y + 6))
    a('</g>')
    # Sample the front polyline so labels do not cover it.
    for pa, pb in zip(pts, pts[1:]):
        xa, ya = fx(pa), fy(pa)
        xb, yb = fx(pb), fy(pb)
        n = max(1, int(math.hypot(xb - xa, yb - ya) / 5))
        for s_ in range(n + 1):
            qx, qy = xa + (xb - xa) * s_ / n, ya + (yb - ya) * s_ / n
            obstacles.append((qx - 2, qy - 2, qx + 2, qy + 2))

    if ref_box and ticks:
        RX = sx(1.0)
        obstacles.append((RX - 2, py0, RX + 2, py0 + ph))  # keep the slider widget off the 1.0x line

    # Profiles: markers, then labels placed to avoid markers / each other
    # Profiles that land on the same spot (small fronts) share one marker and
    # one label ("Zbalansowany / Aktywny") instead of stacking on top of it.
    items = []
    for key in PROFILE_KEYS:
        p = prof_shown.get(key)
        if p is None:
            continue
        X, Y = fx(p), fy(p)
        same = [it for it in items if abs(it["x"] - X) < 1 and abs(it["y"] - Y) < 1]
        if same:
            same[0]["keys"].append(key)
            continue
        obstacles.append((X - 10, Y - 10, X + 10, Y + 10))
        line2 = f'{_fmt(p.get("f_time_ratio"))}× · ~{_fmt_int(p.get("active_kcal"))} kcal'
        items.append({"key": key, "keys": [key], "x": X, "y": Y, "h": 36, "r": 9, "l2": line2})
    for it in items:
        it["l1"] = " / ".join(PROFILE_LABELS[k] for k in it["keys"])
        it["w"] = max(_text_w(it["l1"], 15, True), _text_w(it["l2"], 12.5)) + 4
    # Direction hint box is an obstacle too.
    obstacles.append(hint_box)
    if ref_box:
        obstacles.append(ref_box)
    plot_bounds = (px0 + 4, py0 + 4, px0 + pw - 4, py0 + ph - 4)

    # Slider ticks: an outline diamond around each front point picked by a
    # tick (around the profile ring when the point is also a profile), a small
    # number label ("2–4" when several ticks share a point), and a compact
    # slider track in the emptiest plot corner with the n positions s.
    tick_groups = []
    if ticks:
        ring, ring_key = {}, {}
        for it in items:
            ring[(round(it["x"]), round(it["y"]))] = 9 + 4.5 * (len(it["keys"]) - 1)
            ring_key[(round(it["x"]), round(it["y"]))] = it["key"]
        tick_groups = _tick_groups(ticks, lambda t: (round(fx(t["point"])), round(fy(t["point"]))))
        for g in tick_groups:
            X, Y = fx(g["ticks"][0]["point"]), fy(g["ticks"][0]["point"])
            r_in = ring.get(g["key"], 4.5)
            g.update(x=X, y=Y, h=(r_in + 3) * math.sqrt(2) if r_in > 5 else 8.0)
            g["label"] = _tick_range_label([t["i"] for t in g["ticks"]])
            g["profile"] = ring_key.get(g["key"])
            obstacles.append((X - g["h"], Y - g["h"], X + g["h"], Y + g["h"]))

        # Slider track widget: try plot corners, take the one with fewest collisions.
        tw_, th_ = 290, 54
        corners = [(px0 + pw - tw_ - 10, py0 + ph - th_ - 10),
                   (px0 + 10, hint_box[3] + 8),
                   (px0 + pw - tw_ - 10, py0 + 10),
                   (px0 + 10, py0 + ph - th_ - 10)]
        def _hits(c):
            box = (c[0], c[1], c[0] + tw_, c[1] + th_)
            return sum(_overlap(box, ob, 4) for ob in obstacles)
        wx, wy = min(corners, key=_hits)
        track = {"x0": wx + 48, "x1": wx + tw_ - 48, "y": wy + 31, "box": (wx, wy, wx + tw_, wy + th_)}
        obstacles.append(track["box"])

    placed = _place_labels(items, obstacles, plot_bounds)

    if ticks:
        # Tick numbers go last: they avoid profile label boxes and leader lines.
        tobst = list(obstacles)
        for it, (box, leader) in zip(items, placed):
            tobst.append((box[0] - 6, box[1] - 3, box[2] + 6, box[3] + 3))
            if leader:
                (x1, y1), (x2, y2) = _leader_ends(it, box)
                m = max(1, int(math.hypot(x2 - x1, y2 - y1) / 4))
                tobst += [(x1 + (x2 - x1) * q / m - 2, y1 + (y2 - y1) * q / m - 2,
                           x1 + (x2 - x1) * q / m + 2, y1 + (y2 - y1) * q / m + 2) for q in range(m + 1)]
        # Ticks whose small diamonds (h = 8) nearly touch, i.e. closer than
        # ~20 px, share one range label ("1–5"); a label that
        # ends up away from its diamonds gets a thin leader line.
        tick_clusters = []
        for members in _tick_clusters(tick_groups, 20):
            x0c = min(g["x"] - g["h"] for g in members)
            x1c = max(g["x"] + g["h"] for g in members)
            y0c = min(g["y"] - g["h"] for g in members)
            y1c = max(g["y"] + g["h"] for g in members)
            label = _tick_range_label([t["i"] for g in members for t in g["ticks"]])
            tick_clusters.append({"members": members, "label": label,
                                  "x": (x0c + x1c) / 2, "y": (y0c + y1c) / 2,
                                  "r": max(x1c - x0c, y1c - y0c) / 2 - 4})
        titems = [{"x": c["x"], "y": c["y"], "w": _text_w(c["label"], 12, True) + 2, "h": 13, "r": c["r"]}
                  for c in tick_clusters]
        tdists = (2, 6, 12, 20, 32, 48, 72, 100, 140)
        for c, (box, _leader) in zip(tick_clusters, _place_labels(titems, tobst, plot_bounds, tdists)):
            c["box"] = box
            # Nearest diamond to the label; leader when the gap exceeds ~1.5 text heights.
            best = None
            for g in c["members"]:
                qx = min(max(g["x"], box[0]), box[2])
                qy = min(max(g["y"], box[1]), box[3])
                dd = math.hypot(qx - g["x"], qy - g["y"])
                if best is None or dd < best[0]:
                    best = (dd, g, qx, qy)
            dd, g, qx, qy = best
            c["leader"] = None
            if dd - g["h"] / math.sqrt(2) > 1.5 * 13:
                ux, uy = (qx - g["x"]) / (dd or 1), (qy - g["y"]) / (dd or 1)
                # Diamond edge along direction (ux, uy): |x| + |y| = h.
                re = g["h"] / ((abs(ux) + abs(uy)) or 1)
                c["leader"] = (g["x"] + ux * (re + 2), g["y"] + uy * (re + 2), qx, qy)

    for it in items:
        key = it["key"]
        for n, extra in enumerate(it["keys"][1:], 1):  # outer rings for merged profiles
            a(f'<circle cx="{it["x"]:.1f}" cy="{it["y"]:.1f}" r="{9 + 4.5 * n:.1f}" fill="none" '
              f'stroke="{COLORS[extra]}" stroke-width="3"/>')
        a(f'<circle cx="{it["x"]:.1f}" cy="{it["y"]:.1f}" r="9" fill="{COLORS[key]}" '
          f'stroke="{COLORS["bg"]}" stroke-width="2.5"/>')
    if ticks:
        bx0, by0, bx1, by1 = track["box"]
        a('<g class="slider">')
        a(f'<rect x="{bx0:.1f}" y="{by0:.1f}" width="{bx1 - bx0:.1f}" height="{by1 - by0:.1f}" rx="8" '
          f'fill="{COLORS["bg"]}" fill-opacity="0.94" stroke="{COLORS["grid"]}" stroke-width="1.5"/>')
        a(f'<text x="{(bx0 + bx1) / 2:.1f}" y="{by0 + 15:.1f}" font-size="11.5" font-weight="600" '
          f'text-anchor="middle" fill="{COLORS["text2"]}">{escape(SLIDER_TITLE)}</text>')
        a(f'<text x="{bx0 + 12:.1f}" y="{track["y"] + 4:.1f}" font-size="11.5" fill="{COLORS["text2"]}">czas</text>')
        a(f'<text x="{bx1 - 12:.1f}" y="{track["y"] + 4:.1f}" font-size="11.5" text-anchor="end" '
          f'fill="{COLORS["text2"]}">ruch</text>')
        a(f'<line x1="{track["x0"]:.1f}" y1="{track["y"]:.1f}" x2="{track["x1"]:.1f}" '
          f'y2="{track["y"]:.1f}" stroke="{COLORS["track"]}" stroke-width="3" stroke-linecap="round"/>')
        a('</g>')
        tx_ = lambda s: track["x0"] + s * (track["x1"] - track["x0"])
        a('<g class="ticks">')
        for g in tick_groups:
            for t in g["ticks"]:
                p = t["point"]
                tip = (f'ząbek {t["i"]} · s = {_fmt(t["s"])} · {_fmt(p.get("f_time_ratio"))}× · '
                       f'~{_fmt_int(p.get("active_kcal"))} kcal · {_fmt_int(p.get("steps"))} kroków')
                kx = tx_(t["s"])
                kfill = COLORS[g["profile"]] if g["profile"] else COLORS["bg"]
                a(f'<g class="tick" data-tick="{t["i"]}" data-s="{t["s"]:.4f}" data-label="{escape(g["label"])}">'
                  f'<title>{escape(tip)}</title>'
                  f'<path d="{_diamond(g["x"], g["y"], g["h"])}" fill="none" stroke="{COLORS["tick"]}" '
                  'stroke-width="1.6" stroke-linejoin="round"/>'
                  f'<path d="{_diamond(kx, track["y"], 6)}" fill="{kfill}" stroke="{COLORS["tick"]}" '
                  'stroke-width="1.6" stroke-linejoin="round"/>'
                  f'<text x="{kx:.1f}" y="{track["y"] + 19:.1f}" font-size="10.5" font-weight="600" '
                  f'text-anchor="middle" fill="{COLORS["text2"]}">{t["i"]}</text></g>')
        a('</g>')
        a('<g class="tick-labels">')
        for c in tick_clusters:
            bx0, by0, bx1, by1 = c["box"]
            if c["leader"]:
                x1, y1, x2, y2 = c["leader"]
                a(f'<line class="tick-leader" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                  f'stroke="{COLORS["tick"]}" stroke-width="1"/>')
            a(f'<text x="{bx0 + 1:.1f}" y="{by1 - 2:.1f}" font-size="12" font-weight="700" '
              f'fill="{COLORS["tick"]}" stroke="{COLORS["bg"]}" stroke-width="3" paint-order="stroke">'
              f'{escape(c["label"])}</text>')
        a('</g>')
    a('<g class="labels">')
    for it, (box, leader) in zip(items, placed):
        key = it["key"]
        bx0, by0, bx1, by1 = box
        if leader:
            (sxl, syl), (cx, cy) = _leader_ends(it, box)
            a(f'<line x1="{sxl:.1f}" y1="{syl:.1f}" x2="{cx:.1f}" y2="{cy:.1f}" stroke="{COLORS[key]}" '
              'stroke-width="1.5"/>')
        a(f'<rect x="{bx0 - 6:.1f}" y="{by0 - 3:.1f}" width="{bx1 - bx0 + 12:.1f}" height="{by1 - by0 + 6:.1f}" '
          f'rx="6" fill="{COLORS["bg"]}" fill-opacity="0.92" stroke="{COLORS[key]}" stroke-width="1.5"/>')
        a(f'<text x="{bx0:.1f}" y="{by0 + 14:.1f}" font-size="15" font-weight="700" fill="{COLORS["text"]}">'
          f'{escape(it["l1"])}</text>')
        a(f'<text x="{bx0:.1f}" y="{by0 + 31:.1f}" font-size="12.5" fill="{COLORS["text2"]}">'
          f'{escape(it["l2"])}</text>')
    a('</g>')
    a('</svg>')
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- Markdown

def render_md(front, prof_points, meta=None, source=None, slider=None):
    meta = meta or {}
    ticks = resolve_ticks(front, slider)
    lines = ["# Front Pareto: czas vs ruch", ""]
    info = [f"Front: **{_count(len(front), 'punkt', 'punkty', 'punktów')}**"]
    d = _meta_date(meta)
    if d:
        info.append(f"wygenerowano: {d}")
    if meta.get("pairs"):
        info.append(_count(len(meta["pairs"]), "para", "pary", "par") + " OD")
    variant = _variant_label(meta, slider)
    if variant:
        info.append(variant)
    if source:
        info.append(f"źródło profili: {source}")
    lines += [" · ".join(info), "", "![Front Pareto](front.svg)", "", "## Profile", ""]
    hdr = ["Profil", "Czas × vs KMK", "Śr. czas (min)", "Aktywne kcal", "Kroki",
           "walk.reluctance", "bicycle.reluctance", "access", "direct"]
    lines.append("| " + " | ".join(hdr) + " |")
    lines.append("|" + "|".join(["---"] + ["---:"] * 6 + ["---", "---"]) + "|")
    for key in PROFILE_KEYS:
        p = prof_points[key]
        w = main_weights(p.get("query"))
        row = [PROFILE_LABELS[key], _fmt(p.get("f_time_ratio")), _fmt(p.get("duration_min"), 1),
               _fmt_int(p.get("active_kcal")), _fmt_int(p.get("steps")),
               _fmt(w["walk.reluctance"]), _fmt(w["bicycle.reluctance"]), w["access"], w["direct"]]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "Czas × vs KMK = średni stosunek czasu przejazdu do najszybszej trasy komunikacją "
              "(KMK + pieszo) dla danej pary; < 1 oznacza trasę szybszą niż komunikacja; "
              "kcal = aktywne kalorie (pieszo MET 3,5, rower MET 7,0) dla 70 kg — szacunek.", ""]

    order = sorted(range(len(front)), key=lambda i: (_metric(front[i], "f_time_ratio") is None,
                                                     _metric(front[i], "f_time_ratio") or 0.0))
    if ticks:
        rank = {i: n for n, i in enumerate(order, 1)}
        distinct = len({(_fmt(t["point"].get("f_time_ratio")), _fmt(t["point"].get("active_kcal")))
                        for t in ticks})
        lines += ["## Suwak", "",
                  f"Suwak „czas ↔ ruch”: {_count(len(ticks), 'ząbek', 'ząbki', 'ząbków')}, "
                  f"{_count(distinct, 'różny punkt', 'różne punkty', 'różnych punktów')} frontu. "
                  "s = pozycja suwaka (0 = najszybciej, 1 = najwięcej ruchu); "
                  "# = numer w tabeli wszystkich punktów frontu.", "",
                  "| Ząbek | s | Czas × vs KMK | Śr. czas (min) | Aktywne kcal | Kroki | # |",
                  "|---:|---:|---:|---:|---:|---:|---:|"]
        for t in ticks:
            p = t["point"]
            r = rank.get(t["index"]) if isinstance(t["index"], int) else None
            lines.append(f"| {t['i']} | {_fmt(t['s'])} | {_fmt(p.get('f_time_ratio'))} | "
                         f"{_fmt(p.get('duration_min'), 1)} | {_fmt_int(p.get('active_kcal'))} | "
                         f"{_fmt_int(p.get('steps'))} | {r if r is not None else '—'} |")
        lines.append("")

    lines += ["## Wszystkie punkty frontu", "",
              "| # | Czas × vs KMK | Śr. czas (min) | Aktywne kcal | Kroki | access | direct | cv |",
              "|---:|---:|---:|---:|---:|---|---|---:|"]
    for n, i in enumerate(order, 1):
        p = front[i]
        w = main_weights(p.get("query"))
        lines.append(f"| {n} | {_fmt(p.get('f_time_ratio'))} | {_fmt(p.get('duration_min'), 1)} | "
                     f"{_fmt_int(p.get('active_kcal'))} | {_fmt_int(p.get('steps'))} | {w['access']} | "
                     f"{w['direct']} | {_fmt(p.get('cv'), 1)} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI

def build_report(front_path, profiles_path=None, out_dir=None, slider_path=None):
    with open(front_path, encoding="utf-8") as f:
        data = json.load(f)
    front = data.get("front") or []
    meta = data.get("meta") or {}
    if not front:
        raise ValueError(f"{front_path}: empty front")
    src_dir = os.path.dirname(os.path.abspath(front_path))
    if profiles_path is None:
        cand = os.path.join(src_dir, "profiles.json")
        profiles_path = cand if os.path.exists(cand) else None
    profiles = None
    if profiles_path:
        with open(profiles_path, encoding="utf-8") as f:
            profiles = json.load(f)
    if slider_path is None:
        cand = os.path.join(src_dir, "slider.json")
        slider_path = cand if os.path.exists(cand) else None
    slider = None
    if slider_path:
        with open(slider_path, encoding="utf-8") as f:
            slider = json.load(f)
    prof_points = resolve_profiles(front, profiles)
    out_dir = out_dir or src_dir
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "front.svg")
    md_path = os.path.join(out_dir, "front.md")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(render_svg(front, prof_points, meta, slider))
    source = os.path.basename(profiles_path) if profiles_path else "wybór automatyczny (kolano frontu)"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(front, prof_points, meta, source, slider))
    return svg_path, md_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render Pareto front report (SVG + Markdown).")
    ap.add_argument("front", help="path to front.json")
    ap.add_argument("--profiles", help="path to profiles.json (default: next to front.json, if present)")
    ap.add_argument("--slider", help="path to slider.json (default: next to front.json, if present)")
    ap.add_argument("--out", help="output directory (default: directory of front.json)")
    args = ap.parse_args(argv)
    svg, md = build_report(args.front, args.profiles, args.out, args.slider)
    print(f"wrote {svg}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
