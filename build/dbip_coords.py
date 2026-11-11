#!/usr/bin/env python3
"""Build CN city coordinates from DB-IP Lite CSV (coordinates ONLY;
city assignment is never taken from DB-IP).

Keys are normalised (lowercase, no apostrophes/spaces) to match
merge_qqwry.py. Values are the median lat/lon of all DB-IP rows for that
(state, city) key.

Usage: dbip_coords.py <dbip-city-lite.csv.gz> <out.json>
"""
import csv
import gzip
import json
import sys
from collections import defaultdict


def norm(s):
    return s.lower().replace("'", "").replace(" ", "").replace(".", "").replace("-", "")


def main(csv_gz, out_json):
    by_state_city = defaultdict(list)
    city_states = defaultdict(set)
    n = 0
    with gzip.open(csv_gz, "rt", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            n += 1
            if len(row) < 8 or row[3] != "CN":
                continue
            state, city = norm(row[4]), norm(row[5])
            if not city:
                continue
            try:
                lat, lon = float(row[6]), float(row[7])
            except ValueError:
                continue
            if lat == 0 and lon == 0:
                continue
            by_state_city[(state, city)].append((lat, lon))
            city_states[city].add(state)

    def med(pairs):
        lats = sorted(p[0] for p in pairs)
        lons = sorted(p[1] for p in pairs)
        return [lats[len(lats) // 2], lons[len(lons) // 2]]

    out = {"by_state_city": {f"{s}|{c}": med(v) for (s, c), v in by_state_city.items()},
           "city_states": {c: sorted(ss) for c, ss in city_states.items()}}
    with open(out_json, "w") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("rows scanned", n, "CN (state,city) keys", len(out["by_state_city"]),
          "CN city keys", len(out["city_states"]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
