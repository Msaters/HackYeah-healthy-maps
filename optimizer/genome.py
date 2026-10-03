"""Genome of OTP routing weights: x in [0,1]^DIM -> planConnection GraphQL variables.

decode(x) returns {"modes": PlanModesInput, "preferences": PlanPreferencesInput},
ready to be sent as `$modes` / `$prefs` (see otp/smoke_test.py).
Standard library + numpy only.
"""
import math

import numpy as np

# Each gene: name (GraphQL path), type, range / categories, scale.
#   float  -> lo + x*(hi-lo)            (scale "lin")
#              lo * (hi/lo)**x           (scale "log")
#   int    -> round(lo + x*(hi-lo))
#   weight -> raw triangle weight, normalized together with the other two to sum 1
#   cat    -> categories[min(floor(x*k), k-1)]
GENES = [
    {"name": "walk.reluctance", "type": "float", "range": (0.5, 5.0), "scale": "log"},
    {"name": "bicycle.reluctance", "type": "float", "range": (0.5, 5.0), "scale": "log"},
    {"name": "bicycle.triangle.safety", "type": "weight", "range": (0.0, 1.0), "scale": "norm"},
    {"name": "bicycle.triangle.flatness", "type": "weight", "range": (0.0, 1.0), "scale": "norm"},
    {"name": "bicycle.triangle.time", "type": "weight", "range": (0.0, 1.0), "scale": "norm"},
    {"name": "transit.board.waitReluctance", "type": "float", "range": (0.5, 2.0), "scale": "lin"},
    {"name": "transit.transfer.cost", "type": "int", "range": (0, 600), "scale": "lin", "unit": "s"},
    {"name": "BUS.cost.reluctance", "type": "float", "range": (0.8, 3.0), "scale": "lin"},
    {"name": "access", "type": "cat", "categories": ["WALK", "BICYCLE", "BICYCLE_PARKING"],
     "scale": "cat"},
    {"name": "direct", "type": "cat", "categories": [None, "WALK", "BICYCLE"], "scale": "cat"},
]
DIM = len(GENES)
IDX = {g["name"]: i for i, g in enumerate(GENES)}

# Speeds are user traits, not route preferences: kcal = MET x time, so a speed gene would let
# the GA "buy" calories by slowing the user down. Fixed to otp/router-config.json defaults;
# the backend may override them with the user's own speed.
FIXED_WALK_SPEED = 1.33  # m/s
FIXED_BIKE_SPEED = 4.5   # m/s

DIGITS = 3      # rounding of float values -> stable queries for the cache
TRI_EPS = 1e-6  # keeps the triangle defined when all three raw weights are 0


def random_genome(rng):
    """Uniform random genome; rng is a numpy Generator."""
    return rng.random(DIM)


def clip(x):
    return np.clip(np.asarray(x, dtype=float), 0.0, 1.0)


def _float(gene, v):
    lo, hi = gene["range"]
    if gene["scale"] == "log":
        val = lo * (hi / lo) ** v
    else:
        val = lo + v * (hi - lo)
    return float(min(max(round(float(val), DIGITS), lo), hi))


def _cat(gene, v):
    cats = gene["categories"]
    return cats[min(int(math.floor(float(v) * len(cats))), len(cats) - 1)]


def _triangle(raw):
    """Normalize three raw weights to sum 1, rounded to DIGITS with exact sum (largest remainder)."""
    w = np.asarray(raw, dtype=float) + TRI_EPS
    w = w / w.sum()
    scale = 10 ** DIGITS
    units = np.floor(w * scale).astype(int)
    for i in np.argsort(-(w * scale - units))[: scale - units.sum()]:
        units[i] += 1
    vals = [int(u) / scale for u in units]
    # Guard against float drift: put any residue into the last component.
    vals[2] = round(1.0 - vals[0] - vals[1], DIGITS)
    return {"safety": vals[0], "flatness": vals[1], "time": vals[2]}


def _values(x):
    """Decoded scalar values keyed by gene name (triangle as one dict)."""
    x = clip(x)
    if x.shape != (DIM,):
        raise ValueError(f"genome must have shape ({DIM},), got {x.shape}")
    out = {}
    for i, g in enumerate(GENES):
        if g["type"] == "float":
            out[g["name"]] = _float(g, x[i])
        elif g["type"] == "int":
            lo, hi = g["range"]
            out[g["name"]] = int(round(lo + float(x[i]) * (hi - lo)))
        elif g["type"] == "cat":
            out[g["name"]] = _cat(g, x[i])
    t = IDX["bicycle.triangle.safety"]
    out["triangle"] = _triangle(x[t:t + 3])
    return out


def decode(x):
    """Genome -> {"modes": PlanModesInput, "preferences": PlanPreferencesInput}."""
    v = _values(x)
    access = v["access"]
    street_leg = "BICYCLE" if access == "BICYCLE" else "WALK"
    modes = {
        "transit": {
            "access": [access],
            "egress": [street_leg],
            "transfer": [street_leg],
            "transit": [{"mode": "TRAM"},
                        {"mode": "BUS", "cost": {"reluctance": v["BUS.cost.reluctance"]}}],
        },
    }
    if v["direct"] is None:
        # OTP adds a WALK direct itinerary by default; "none" must be forced.
        modes["transitOnly"] = True
    else:
        modes["direct"] = [v["direct"]]
    preferences = {
        "street": {
            "walk": {"reluctance": v["walk.reluctance"], "speed": FIXED_WALK_SPEED},
            "bicycle": {
                "reluctance": v["bicycle.reluctance"],
                "speed": FIXED_BIKE_SPEED,
                "optimization": {"triangle": v["triangle"]},
            },
        },
        "transit": {
            "board": {"waitReluctance": v["transit.board.waitReluctance"]},
            "transfer": {"cost": v["transit.transfer.cost"]},
        },
    }
    return {"modes": modes, "preferences": preferences}


def describe(x):
    """Short human-readable summary of a genome."""
    v = _values(x)
    t = v["triangle"]
    direct = v["direct"] or "brak"
    return (f"dojazd {v['access']}, direct {direct} | "
            f"pieszo rel {v['walk.reluctance']:.2f} @{FIXED_WALK_SPEED:.2f} m/s | "
            f"rower rel {v['bicycle.reluctance']:.2f} @{FIXED_BIKE_SPEED:.2f} m/s "
            f"(bezp {t['safety']:.2f}/płasko {t['flatness']:.2f}/czas {t['time']:.2f}) | "
            f"czekanie {v['transit.board.waitReluctance']:.2f}, "
            f"przesiadka +{v['transit.transfer.cost']} s, autobus ×{v['BUS.cost.reluctance']:.2f}")


if __name__ == "__main__":
    import json
    g = random_genome(np.random.default_rng(0))
    print(describe(g))
    print(json.dumps(decode(g), indent=2))
