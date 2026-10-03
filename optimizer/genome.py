"""Genome of OTP routing weights: x in [0,1]^DIM -> planConnection GraphQL variables.

decode(x, variant) returns {"modes": PlanModesInput, "preferences": PlanPreferencesInput},
ready to be sent as `$modes` / `$prefs` (see otp/smoke_test.py).

Variants (the user's "[mam rower]" tick):
  "bike" - full genome: access WALK / BICYCLE / BICYCLE_PARKING, direct none / WALK / BICYCLE;
  "walk" - no bicycle at all: access, egress and transfer are WALK, direct none / WALK,
           no `preferences.street.bicycle`. Bicycle genes and the access gene are inactive
           (see active_mask / canonical). Two extra walk-only genes (walk.boardCost,
           walk.safetyFactor) widen the otherwise tiny walk front; they are inactive for "bike"
           and never emitted there, so the bike query is unchanged.
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
    # Walk-variant levers (appended last so the first 10 genes keep their indices). Probe on
    # OTP 2.10: boardCost x walk.reluctance gives 5-6 different pedestrian routes per pair
    # where walk.reluctance alone saturates at 1-2.
    {"name": "walk.boardCost", "type": "int", "range": (0, 1800), "scale": "lin", "unit": "s"},
    {"name": "walk.safetyFactor", "type": "float", "range": (0.0, 1.0), "scale": "lin"},
]
DIM = len(GENES)
IDX = {g["name"]: i for i, g in enumerate(GENES)}

# Speeds are user traits, not route preferences: kcal = MET x time, so a speed gene would let
# the GA "buy" calories by slowing the user down. Fixed to otp/router-config.json defaults;
# the backend may override them with the user's own speed.
FIXED_WALK_SPEED = 1.33  # m/s
FIXED_BIKE_SPEED = 4.5   # m/s

VARIANTS = ("bike", "walk")
# Category overrides per variant; genes not listed use GENES[i]["categories"].
VARIANT_CATEGORIES = {
    "bike": {},
    "walk": {"access": ["WALK"], "direct": [None, "WALK"]},
}
# Genes that exist only in the "walk" variant (inactive for "bike").
WALK_ONLY_GENES = ("walk.boardCost", "walk.safetyFactor")
# Genes that have no effect on decode() in a variant.
INACTIVE_GENES = {
    "bike": WALK_ONLY_GENES,
    "walk": ("bicycle.reluctance", "bicycle.triangle.safety", "bicycle.triangle.flatness",
             "bicycle.triangle.time", "access"),
}
CANONICAL_FILL = 0.5  # value of inactive genes in canonical()

# Anchor K1: OTP default weights, plain transit (walk access, no direct leg).
# Triangle weights are raw (normalized together -> ~1/3 each); bicycle values matter for "bike" only.
ANCHOR_VALUES = {
    "walk.reluctance": 2.0,
    "bicycle.reluctance": 2.0,
    "bicycle.triangle.safety": 1 / 3,
    "bicycle.triangle.flatness": 1 / 3,
    "bicycle.triangle.time": 1 / 3,
    "transit.board.waitReluctance": 1.0,
    "transit.transfer.cost": 0,
    "BUS.cost.reluctance": 1.0,
    "access": "WALK",
    "direct": None,
    "walk.boardCost": 600,      # OTP default
    "walk.safetyFactor": 1.0,   # OTP default
}

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


def _check_variant(variant):
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}, expected one of {VARIANTS}")


def _categories(gene, variant):
    return VARIANT_CATEGORIES[variant].get(gene["name"], gene["categories"])


def _cat(gene, v, variant="bike"):
    cats = _categories(gene, variant)
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


def _values(x, variant="bike"):
    """Decoded scalar values keyed by gene name (triangle as one dict)."""
    _check_variant(variant)
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
            out[g["name"]] = _cat(g, x[i], variant)
    t = IDX["bicycle.triangle.safety"]
    out["triangle"] = _triangle(x[t:t + 3])
    return out


def active_mask(variant="bike"):
    """Boolean array (DIM,): True for genes that influence decode(x, variant)."""
    _check_variant(variant)
    mask = np.ones(DIM, dtype=bool)
    for name in INACTIVE_GENES[variant]:
        mask[IDX[name]] = False
    return mask


def canonical(x, variant="bike"):
    """Copy of x with inactive genes set to CANONICAL_FILL (stable cache key / dedupe)."""
    x = np.array(x, dtype=float)
    if x.shape != (DIM,):
        raise ValueError(f"genome must have shape ({DIM},), got {x.shape}")
    x[~active_mask(variant)] = CANONICAL_FILL
    return x


def _encode_value(gene, val, variant):
    """Inverse of decoding for one gene (categories -> middle of their interval)."""
    if gene["type"] == "cat":
        cats = _categories(gene, variant)
        return (cats.index(val) + 0.5) / len(cats)
    if gene["type"] == "weight":
        return float(val)
    lo, hi = gene["range"]
    if gene.get("scale") == "log":
        return math.log(val / lo) / math.log(hi / lo)
    return (val - lo) / (hi - lo)


def encode_anchor(variant="bike"):
    """Genome of the anchor K1 (ANCHOR_VALUES), in canonical form for the variant."""
    _check_variant(variant)
    x = np.array([_encode_value(g, ANCHOR_VALUES[g["name"]], variant) for g in GENES])
    return canonical(clip(x), variant)


def decode(x, variant="bike"):
    """Genome -> {"modes": PlanModesInput, "preferences": PlanPreferencesInput}."""
    v = _values(x, variant)
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
    street = {"walk": {"reluctance": v["walk.reluctance"], "speed": FIXED_WALK_SPEED}}
    if variant == "walk":
        street["walk"]["boardCost"] = v["walk.boardCost"]
        street["walk"]["safetyFactor"] = v["walk.safetyFactor"]
    if variant == "bike":
        street["bicycle"] = {
            "reluctance": v["bicycle.reluctance"],
            "speed": FIXED_BIKE_SPEED,
            "optimization": {"triangle": v["triangle"]},
        }
    preferences = {
        "street": street,
        "transit": {
            "board": {"waitReluctance": v["transit.board.waitReluctance"]},
            "transfer": {"cost": v["transit.transfer.cost"]},
        },
    }
    return {"modes": modes, "preferences": preferences}


def describe(x, variant="bike"):
    """Short human-readable summary of a genome."""
    v = _values(x, variant)
    t = v["triangle"]
    direct = v["direct"] or "brak"
    bike = (f"rower rel {v['bicycle.reluctance']:.2f} @{FIXED_BIKE_SPEED:.2f} m/s "
            f"(bezp {t['safety']:.2f}/płasko {t['flatness']:.2f}/czas {t['time']:.2f}) | "
            if variant == "bike" else "bez roweru | ")
    walk_extra = (f"wejście do pojazdu +{v['walk.boardCost']} s, bezpieczeństwo pieszo "
                  f"{v['walk.safetyFactor']:.2f} | " if variant == "walk" else "")
    return (f"dojazd {v['access']}, direct {direct} | "
            f"pieszo rel {v['walk.reluctance']:.2f} @{FIXED_WALK_SPEED:.2f} m/s | "
            f"{bike}"
            f"{walk_extra}"
            f"czekanie {v['transit.board.waitReluctance']:.2f}, "
            f"przesiadka +{v['transit.transfer.cost']} s, autobus ×{v['BUS.cost.reluctance']:.2f}")


if __name__ == "__main__":
    import json
    g = random_genome(np.random.default_rng(0))
    print(describe(g))
    print(json.dumps(decode(g), indent=2))
