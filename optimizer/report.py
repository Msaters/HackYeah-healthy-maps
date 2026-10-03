"""Report for an NSGA-II run: Pareto front chart (SVG) + profile table (Markdown).

Usage:
    python3 -m optimizer.report PATH/front.json [--profiles PATH/profiles.json] [--out DIR]

Writes ``front.svg`` and ``front.md`` into ``--out`` (default: the directory of
front.json). Profiles come from ``--profiles``, else ``profiles.json`` next to
front.json, else they are picked from the front with :func:`pick_profiles`.

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
}
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


def _place_labels(items, obstacles, bounds):
    """Greedy placement of label boxes around anchor points.

    items: list of dicts with x, y (anchor), w, h, r (marker radius).
    obstacles: list of boxes (x0, y0, x1, y1) to avoid (markers, legend).
    Returns list of (box, text_anchor_x, baseline_y, needs_leader).
    """
    placed = []
    results = []
    bx0, by0, bx1, by1 = bounds
    dists = (8, 22, 40, 64, 96, 140)
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


# ---------------------------------------------------------------- SVG

def render_svg(front, prof_points, meta=None):
    meta = meta or {}
    pw = W - M_LEFT - M_RIGHT
    ph = H - M_TOP - M_BOTTOM
    px0, py0 = M_LEFT, M_TOP

    shown = [p for p in front if _plottable(p)]
    prof_shown = {k: p for k, p in prof_points.items() if _plottable(p)}
    all_pts = shown + list(prof_shown.values())
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
    a(f'<text x="{px0 + 12}" y="{py0 + 20}" font-size="12" fill="{COLORS["muted"]}">'
      f'{HINT}</text>')
    hint_box = (px0 + 8, py0 + 6, px0 + 12 + _text_w(HINT, 12), py0 + 26)

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
    placed = _place_labels(items, obstacles, (px0 + 4, py0 + 4, px0 + pw - 4, py0 + ph - 4))

    for it in items:
        key = it["key"]
        for n, extra in enumerate(it["keys"][1:], 1):  # outer rings for merged profiles
            a(f'<circle cx="{it["x"]:.1f}" cy="{it["y"]:.1f}" r="{9 + 4.5 * n:.1f}" fill="none" '
              f'stroke="{COLORS[extra]}" stroke-width="3"/>')
        a(f'<circle cx="{it["x"]:.1f}" cy="{it["y"]:.1f}" r="9" fill="{COLORS[key]}" '
          f'stroke="{COLORS["bg"]}" stroke-width="2.5"/>')
    a('<g class="labels">')
    for it, (box, leader) in zip(items, placed):
        key = it["key"]
        bx0, by0, bx1, by1 = box
        if leader:
            # Connect the marker edge to the nearest point on the label box.
            cx = min(max(it["x"], bx0), bx1)
            cy = min(max(it["y"], by0), by1)
            dx, dy = cx - it["x"], cy - it["y"]
            dl = math.hypot(dx, dy) or 1
            ro = 11 + 4.5 * (len(it["keys"]) - 1)
            sxl, syl = it["x"] + dx / dl * ro, it["y"] + dy / dl * ro
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

def render_md(front, prof_points, meta=None, source=None):
    meta = meta or {}
    lines = ["# Front Pareto: czas vs ruch", ""]
    info = [f"Front: **{_count(len(front), 'punkt', 'punkty', 'punktów')}**"]
    d = _meta_date(meta)
    if d:
        info.append(f"wygenerowano: {d}")
    if meta.get("pairs"):
        info.append(_count(len(meta["pairs"]), "para", "pary", "par") + " OD")
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

    lines += ["## Wszystkie punkty frontu", "",
              "| # | Czas × vs KMK | Śr. czas (min) | Aktywne kcal | Kroki | access | direct | cv |",
              "|---:|---:|---:|---:|---:|---|---|---:|"]
    order = sorted(range(len(front)), key=lambda i: (_metric(front[i], "f_time_ratio") is None,
                                                     _metric(front[i], "f_time_ratio") or 0.0))
    for n, i in enumerate(order, 1):
        p = front[i]
        w = main_weights(p.get("query"))
        lines.append(f"| {n} | {_fmt(p.get('f_time_ratio'))} | {_fmt(p.get('duration_min'), 1)} | "
                     f"{_fmt_int(p.get('active_kcal'))} | {_fmt_int(p.get('steps'))} | {w['access']} | "
                     f"{w['direct']} | {_fmt(p.get('cv'), 1)} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI

def build_report(front_path, profiles_path=None, out_dir=None):
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
    prof_points = resolve_profiles(front, profiles)
    out_dir = out_dir or src_dir
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "front.svg")
    md_path = os.path.join(out_dir, "front.md")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(render_svg(front, prof_points, meta))
    source = os.path.basename(profiles_path) if profiles_path else "wybór automatyczny (kolano frontu)"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(front, prof_points, meta, source))
    return svg_path, md_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render Pareto front report (SVG + Markdown).")
    ap.add_argument("front", help="path to front.json")
    ap.add_argument("--profiles", help="path to profiles.json (default: next to front.json, if present)")
    ap.add_argument("--out", help="output directory (default: directory of front.json)")
    args = ap.parse_args(argv)
    svg, md = build_report(args.front, args.profiles, args.out)
    print(f"wrote {svg}\nwrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
