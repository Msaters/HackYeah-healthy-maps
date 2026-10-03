#!/usr/bin/env python3
"""Marks every KMK trip as bikes_allowed=1 in the GTFS zips.

KMK rules allow carrying a bicycle on trams and buses for free (with a valid ticket, when there is
room), but ZTP's GTFS has no bikes_allowed column, so OTP never plans "bike on board" trips.
Run after download.sh, then rebuild the graph.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

OTP_DIR = Path(__file__).parent


def patch(path: Path) -> int:
    with zipfile.ZipFile(path) as zin:
        members = {name: zin.read(name) for name in zin.namelist()}

    rows = list(csv.DictReader(io.StringIO(members["trips.txt"].decode("utf-8-sig"))))
    fields = list(rows[0].keys())
    if "bikes_allowed" not in fields:
        fields.append("bikes_allowed")
    for row in rows:
        row["bikes_allowed"] = "1"

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    members["trips.txt"] = out.getvalue().encode("utf-8")

    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in members.items():
            zout.writestr(name, data)
    tmp.replace(path)
    return len(rows)


if __name__ == "__main__":
    for name in sys.argv[1:] or ["krk-a.gtfs.zip", "krk-t.gtfs.zip"]:
        print(f"{name}: {patch(OTP_DIR / name)} trips marked bikes_allowed=1")
