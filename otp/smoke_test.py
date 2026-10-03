#!/usr/bin/env python3
"""Smoke test for the local OTP server: runs our candidate queries and prints a summary.

Usage: python3 otp/smoke_test.py [--url http://localhost:8080] [--arrive 2026-10-05T09:00]
Standard library only.
"""
import argparse
import json
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

PLACES = {
    "nowa_huta": (50.0717, 20.0373, "Plac Centralny"),
    "agh": (50.0663, 19.9232, "AGH"),
    "rynek": (50.0617, 19.9373, "Rynek Główny"),
    "czerwone_maki": (50.0153, 19.8930, "P+R Czerwone Maki"),
}

QUERY = """
query Plan($from: PlanLabeledLocationInput!, $to: PlanLabeledLocationInput!,
           $arriveBy: OffsetDateTime!, $modes: PlanModesInput, $prefs: PlanPreferencesInput) {
  planConnection(origin: $from, destination: $to, dateTime: { latestArrival: $arriveBy },
                 modes: $modes, preferences: $prefs, first: 3) {
    routingErrors { code description }
    edges { node {
      start end duration walkDistance elevationGained
      legs { mode duration distance realTime rentedBike route { shortName } }
    } }
  }
}"""

# name, from, to, modes, preferences
SCENARIOS = [
    ("K1 komunikacja", "nowa_huta", "agh",
     {"transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}}, None),
    ("K2 rower całość", "nowa_huta", "agh",
     {"direct": ["BICYCLE"], "directOnly": True},
     {"street": {"bicycle": {"optimization": {"type": "SAFE_STREETS"}}}}),
    ("K3 bike&ride", "nowa_huta", "agh",
     {"transit": {"access": ["BICYCLE_PARKING"], "egress": ["WALK"]}, "transitOnly": True},
     {"street": {"bicycle": {"reluctance": 1.0}}}),
    ("K5 pieszo całość", "rynek", "agh",
     {"direct": ["WALK"], "directOnly": True}, None),
    ("K6 KMK + więcej chodzenia", "nowa_huta", "agh",
     {"transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}},
     {"street": {"walk": {"reluctance": 0.8, "speed": 1.45}}}),
    ("P+R Czerwone Maki → Rynek KMK", "czerwone_maki", "rynek",
     {"transit": {"access": ["WALK"], "egress": ["WALK"], "transfer": ["WALK"]}}, None),
]


def loc(key):
    lat, lon, label = PLACES[key]
    return {"label": label, "location": {"coordinate": {"latitude": lat, "longitude": lon}}}


def post(url, variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(f"{url}/otp/gtfs/v1", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def describe(it):
    parts = []
    for leg in it["legs"]:
        mode = leg["mode"]
        if leg.get("route"):
            mode += f" {leg['route']['shortName']}"
        if leg.get("rentedBike"):
            mode += " (rental)"
        parts.append(f"{mode} {round(leg['duration'] / 60)}min")
    return " → ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--arrive", default="2026-10-05T09:00", help="local Kraków time")
    args = ap.parse_args()
    arrive = datetime.fromisoformat(args.arrive).replace(tzinfo=ZoneInfo("Europe/Warsaw"))
    print(f"Przyjazd najpóźniej: {arrive.isoformat()}\n")

    failed = 0
    for name, a, b, modes, prefs in SCENARIOS:
        try:
            res = post(args.url, {"from": loc(a), "to": loc(b), "arriveBy": arrive.isoformat(),
                                  "modes": modes, "prefs": prefs})
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"✗ {name}: {e}")
            failed += 1
            continue
        if "errors" in res:
            print(f"✗ {name}: GraphQL {res['errors'][0]['message']}")
            failed += 1
            continue
        pc = res["data"]["planConnection"]
        edges = pc["edges"]
        errs = ", ".join(e["code"] for e in pc["routingErrors"])
        print(f"{'✓' if edges else '✗'} {name}: {len(edges)} tras" + (f"  [{errs}]" if errs else ""))
        failed += 0 if edges else 1
        for e in edges:
            it = e["node"]
            end = datetime.fromisoformat(it["end"]).strftime("%H:%M")
            rt = "na żywo" if any(l["realTime"] for l in it["legs"]) else "rozkład"
            print(f"    {end}  {round(it['duration'] / 60)} min  pieszo {round(it['walkDistance'])} m  "
                  f"↑{round(it['elevationGained'] or 0)} m  {rt}  |  {describe(it)}")
        print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
