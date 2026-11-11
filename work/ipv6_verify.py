#!/usr/bin/env python3
"""Verify the IPv6 overlay in the built GeoLite2-City-CN.mmdb.

Queries the 102 IPv6 samples (work/ipv6_samples.json) against the merged
mmdb and reports, per stratum, how many gained a province / a city versus
the original GeoLite2. Also asserts the two spec IPv6s and the Xiaogan
regression point.

Usage: ipv6_verify.py <merged.mmdb> <orig GeoLite2.mmdb> <out.json>
"""
import json
import sys
from collections import Counter, defaultdict

import maxminddb

SPEC = {
    "2409:8a38:28:5a50:2cb3:d356:ea83:44c0": ("JX", "Nanchang"),
    "2409:8a4c:ecd:b00:1497:11ff:fec1:eedb": ("HB", "Xiaogan"),
}


def triple(rec):
    if not rec:
        return ("", "", "")
    c = (rec.get("country") or {}).get("iso_code", "")
    subs = rec.get("subdivisions") or []
    r = (subs[0] or {}).get("iso_code", "") if subs else ""
    city = ((rec.get("city") or {}).get("names") or {}).get("en", "")
    return (c, r, city)


def main(merged_path, orig_path, out_path):
    samples = json.load(open("work/ipv6_samples.json"))
    merged = maxminddb.open_database(merged_path)
    orig = maxminddb.open_database(orig_path)
    stats = defaultdict(lambda: Counter())
    rows = []
    for s in samples:
        ip, st = s["ip"], s["stratum"]
        mc, mr, mct = triple(merged.get(ip))
        oc, orr, oct_ = triple(orig.get(ip))
        stats[st]["n"] += 1
        if mr:
            stats[st]["prov"] += 1
        if mct:
            stats[st]["city"] += 1
        if mr and not orr:
            stats[st]["prov_added"] += 1
        if mct and not oct_:
            stats[st]["city_added"] += 1
        if orr and mr != orr:
            stats[st]["prov_changed"] += 1
        if oct_ and mct != oct_:
            stats[st]["city_changed"] += 1
        rows.append({"ip": ip, "stratum": st,
                     "merged": [mc, mr, mct], "orig": [oc, orr, oct_]})
    print(f"{'stratum':12s} {'n':>3s} {'prov':>4s} {'city':>4s} {'prov+':>5s} {'city+':>5s} {'prov!':>5s} {'city!':>5s}")
    tot = Counter()
    for st in ["spec", "unicom", "mobile", "telecom", "other-cn", "geolite-city"]:
        c = stats[st]
        print(f"{st:12s} {c['n']:3d} {c['prov']:4d} {c['city']:4d} {c['prov_added']:5d} {c['city_added']:5d} {c['prov_changed']:5d} {c['city_changed']:5d}")
        for k in ("n", "prov", "city", "prov_added", "city_added",
                  "prov_changed", "city_changed"):
            tot[k] += c[k]
    print(f"{'TOTAL':12s} {tot['n']:3d} {tot['prov']:4d} {tot['city']:4d} {tot['prov_added']:5d} {tot['city_added']:5d} {tot['prov_changed']:5d} {tot['city_changed']:5d}")
    print()
    ok = True
    for ip, (want_prov, want_city) in SPEC.items():
        mc, mr, mct = triple(merged.get(ip))
        good = (mr == want_prov and mct == want_city)
        ok = ok and good
        print(f"spec {ip} -> {mc}/{mr}/{mct} (want {want_prov}/{want_city}) {'OK' if good else 'MISMATCH'}")
    # no IPv6 province/city may ever be overwritten: prov_changed/city_changed must be 0
    if tot["prov_changed"] or tot["city_changed"]:
        print("FAIL: an existing GeoLite2 IPv6 province/city was overwritten")
        ok = False
    else:
        print("OK: no existing GeoLite2 IPv6 province/city overwritten (fill-gaps-only holds)")
    json.dump({"per_stratum": {k: dict(v) for k, v in stats.items()},
               "total": dict(tot), "spec_ok": ok, "rows": rows},
              open(out_path, "w"), ensure_ascii=False, indent=1)
    print("wrote", out_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
