#!/usr/bin/env python3
"""Merge IPv6 overlay CIDRs for GeoLite2-City-CN.mmdb.

Sources (both already extracted to TSV):
  - GeoCN.mmdb (extract_geocn): IPv6 networks with a GB/T 2260
    division_code (district level) + ISP. This is the PRIMARY source:
    where it has data it usually reaches city level.
  - qqwry.ipdb (walk_ipdb, metowolf, same CZ88 data as qqwry.dat):
    IPv6 records with country/region/city. FALLBACK only: it fills
    ranges GeoCN does not cover, mostly at province level.

Rules (agreed with the user):
  1. GeoCN wins wherever it has data; ipdb fills only the gaps.
  2. Only mainland-China provinces (HK/MO/TW never merged into CN).
  3. RIR guard: only sub-ranges the APNIC delegated file allocates to CN.
  4. Operator scope: only ranges inside the big-three ISPs' + CERNET's
     IPv6 lists (gaoyifan/china-operator-ip, daily BGP-based).
  5. City names resolve to EN/coords with the same machinery as
     merge_qqwry.py (GeoLite2 city table first, pinyin fallback after);
     district codes are truncated to prefecture level (city only, never
     district, per task §4). The build step (build_mmdb) additionally
     only inserts where GeoLite2 has no subdivision and no city, so
     GeoLite2's existing IPv6 cities (e.g. HB/Xiaogan) are never
     overwritten; this script only prepares the candidate CIDRs.

Usage:
  merge_ipv6.py <geocn_v6.tsv> <ipdb_v6.tsv> <geolite_cn.json>
      <out.jsonl> <stats.json> <dbip_cn_coords.json>
      <delegated-apnic-latest> <operator6-dir>
"""
import bisect
import ipaddress
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_qqwry as mq

# 2-digit GB/T 2260 province prefix -> ISO 3166-2 (task §4.1)
PROV_CODE2 = {
    "11": "BJ", "12": "TJ", "13": "HE", "14": "SX", "15": "NM",
    "21": "LN", "22": "JL", "23": "HL", "31": "SH", "32": "JS",
    "33": "ZJ", "34": "AH", "35": "FJ", "36": "JX", "37": "SD",
    "41": "HA", "42": "HB", "43": "HN", "44": "GD", "45": "GX",
    "46": "HI", "50": "CQ", "51": "SC", "52": "GZ", "53": "YN",
    "54": "XZ", "61": "SN", "62": "GS", "63": "QH", "64": "NX",
    "65": "XJ",
}


def load_rir_allocations_v6(path):
    """APNIC delegated stats, IPv6 only -> sorted [(start, end, country)]."""
    allocs = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or "|" not in line:
                continue
            p = line.rstrip("\n").split("|")
            if len(p) < 7 or p[2] != "ipv6":
                continue
            try:
                net = ipaddress.IPv6Network(f"{p[3]}/{p[4]}")
            except ValueError:
                continue
            allocs.append((int(net.network_address), int(net.broadcast_address), p[1]))
    allocs.sort()
    return allocs


def load_operator_intervals(d):
    """Union of the big-three + CERNET IPv6 CIDR lists -> sorted, merged."""
    ivs = []
    for name in ("chinanet6.txt", "unicom6.txt", "cmcc6.txt", "cernet6.txt"):
        path = os.path.join(d, name)
        if not os.path.exists(path):
            print(f"WARNING: operator list missing: {path}", file=sys.stderr)
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    net = ipaddress.IPv6Network(line)
                except ValueError:
                    continue
                ivs.append((int(net.network_address), int(net.broadcast_address)))
    ivs.sort()
    merged = []
    for s, e in ivs:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def inside(intervals, starts, x):
    """True if integer x lies inside one of the sorted (start, end) intervals."""
    i = bisect.bisect_right(starts, x) - 1
    return i >= 0 and intervals[i][1] >= x


def main(geocn_tsv, ipdb_tsv, geolite_json, out_jsonl, stats_path,
         dbip_json, rir_path, operator_dir):
    stats = Counter()
    # --- division-code table: 4-digit prefecture code -> city zh name
    div_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "division_cities.json")
    division_cities = json.load(open(div_path, encoding="utf-8"))["cities"]

    # --- GeoCN rows: (start, end, iso, city_zh|None)
    geocn = []
    with open(geocn_tsv) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 2:
                continue
            try:
                net = ipaddress.IPv6Network(p[0])
            except ValueError:
                continue
            code = p[1].strip()
            stats["geocn_rows"] += 1
            if len(code) < 2 or code[:2] not in PROV_CODE2:
                stats["geocn_bad_code"] += 1
                continue
            iso = PROV_CODE2[code[:2]]
            city = None
            if not code.endswith("0000") and len(code) >= 4:
                name = division_cities.get(code[:4])
                if name:
                    city = mq.stem_prefecture(name)
                else:
                    stats["geocn_unknown_prefecture"] += 1
            if city is None and iso in mq.MUNICIPALITIES:
                city = mq.MUNICIPALITIES[iso]
            geocn.append((int(net.network_address), int(net.broadcast_address),
                          iso, city))
    # --- ipdb rows: (start, end, iso, city_zh|None), CN mainland only
    ipdb = []
    with open(ipdb_tsv) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 4:
                continue
            stats["ipdb_rows"] += 1
            country, region, city_raw = p[1], p[2], p[3]
            if country != "中国" or region not in mq.PROVINCES:
                continue
            try:
                net = ipaddress.IPv6Network(p[0])
            except ValueError:
                continue
            iso = mq.PROVINCES[region][0]
            city = mq.stem_prefecture(city_raw) if city_raw else None
            if city is None and iso in mq.MUNICIPALITIES:
                city = mq.MUNICIPALITIES[iso]
            ipdb.append((int(net.network_address), int(net.broadcast_address),
                         iso, city))
    stats["geocn_cn_rows"] = len(geocn)
    stats["ipdb_cn_rows"] = len(ipdb)
    print(f"geocn rows: {len(geocn)}, ipdb CN rows: {len(ipdb)}")

    # --- guards
    rir = load_rir_allocations_v6(rir_path)
    rir_starts = [a[0] for a in rir]
    ops = []
    if operator_dir and os.path.isdir(operator_dir):
        ops = load_operator_intervals(operator_dir)
    op_starts = [a[0] for a in ops]
    print(f"rir ipv6 allocations: {len(rir)}, operator intervals: {len(ops)}"
          + (" (operator scope OFF: RIR guard only)" if not ops else ""))

    # --- atomic segmentation: cut at every boundary of every interval set,
    # so each atomic segment is homogeneous for source, RIR and operator scope.
    cuts = set()
    for src in (geocn, ipdb, rir, ops):
        for s, e, *_ in src:
            cuts.add(s)
            cuts.add(e + 1)
    cuts = sorted(cuts)
    geocn_starts = [g[0] for g in sorted(geocn)]
    ipdb_starts = [g[0] for g in sorted(ipdb)]
    geocn_sorted = sorted(geocn)
    ipdb_sorted = sorted(ipdb)

    def lookup(intervals, starts, x):
        i = bisect.bisect_right(starts, x) - 1
        if i < 0 or intervals[i][1] < x:
            return None
        return intervals[i]

    kept = []  # (start, end, iso, city, origin)
    for a, b in zip(cuts, cuts[1:]):
        e = b - 1
        if a > e:
            continue
        g = lookup(geocn_sorted, geocn_starts, a)
        if g is not None:
            iso, city, origin = g[2], g[3], "geocn"
        else:
            d = lookup(ipdb_sorted, ipdb_starts, a)
            if d is None:
                continue
            iso, city, origin = d[2], d[3], "ipdb"
        # RIR guard: must be allocated to CN
        r = lookup(rir, rir_starts, a)
        if r is None or r[2] != "CN":
            stats["dropped_rir_not_cn"] += 1
            continue
        # operator scope (only when lists were supplied): must be inside
        # big-three/CERNET space
        if ops and not inside(ops, op_starts, a):
            stats["dropped_outside_operator_scope"] += 1
            continue
        kept.append((a, e, iso, city, origin))
    stats["atomic_kept"] = len(kept)

    # --- group by (iso, city), merge adjacent, summarise to CIDRs
    groups = defaultdict(list)
    for s, e, iso, city, origin in kept:
        groups[(iso, city)].append((s, e, origin))
    print(f"groups: {len(groups)}")

    # --- city EN/coords resolution (same chain as merge_qqwry.py)
    dbip = {"by_state_city": {}, "city_states": {}}
    if dbip_json and os.path.exists(dbip_json):
        dbip = json.load(open(dbip_json, encoding="utf-8"))
    iso_to_en = {v[0]: v[2] for v in mq.PROVINCES.values()}
    geo = json.load(open(geolite_json, encoding="utf-8"))
    cities = geo["cities"]
    cities_by_en = geo.get("cities_by_en", {})

    def norm_en(name):
        n = name.lower().replace("'", "").replace(" ", "").replace(".", "").replace("-", "")
        for suf in ("city", "shi"):
            if n.endswith(suf):
                n = n[: -len(suf)]
        return n

    capital_coords = {}
    for iso, cap in mq.CAPITALS.items():
        c = cities.get(f"{iso}|{cap}")
        if c:
            capital_coords[iso] = (c["lat"], c["lon"])
            continue
        lats = [v["lat"] for k, v in cities.items() if k.startswith(iso + "|")]
        lons = [v["lon"] for k, v in cities.items() if k.startswith(iso + "|")]
        if lats:
            lats.sort(); lons.sort()
            capital_coords[iso] = (lats[len(lats) // 2], lons[len(lons) // 2])
        else:
            capital_coords[iso] = (34.7732, 113.722)

    by_city = defaultdict(list)
    for k, v in cities.items():
        by_city[k.split("|", 1)[1]].append((k.split("|", 1)[0], v))

    def resolve(iso, city_zh, origin):
        """-> {en, geoname_id, lat, lon, radius, source}"""
        if city_zh is None:
            lat, lon = capital_coords[iso]
            return {"en": "", "geoname_id": 0, "lat": lat, "lon": lon,
                    "radius": 250, "source": origin + "-province"}
        hit = cities.get(f"{iso}|{city_zh}")
        if hit:
            return {"en": hit["en"], "geoname_id": hit["geoname_id"],
                    "lat": hit["lat"], "lon": hit["lon"],
                    "radius": hit["radius"], "source": origin}
        uniq = by_city.get(city_zh, [])
        if len(uniq) == 1:
            v = uniq[0][1]
            return {"en": v["en"], "geoname_id": v["geoname_id"],
                    "lat": v["lat"], "lon": v["lon"],
                    "radius": v["radius"], "source": origin + "+geolite2-xprov"}
        en = mq.pinyin_en(city_zh)
        by_en = cities_by_en.get(norm_en(en))
        if by_en:
            return {"en": by_en["en"], "geoname_id": by_en["geoname_id"],
                    "lat": by_en["lat"], "lon": by_en["lon"],
                    "radius": by_en["radius"],
                    "source": origin + "+pinyin-geolite2-coords"}
        prov_en_norm = norm_en(iso_to_en[iso])
        city_norm = norm_en(mq.SEAT_ALIASES.get(city_zh, en))
        dbip_xy = dbip["by_state_city"].get(f"{prov_en_norm}|{city_norm}")
        if dbip_xy is None and len(dbip["city_states"].get(city_norm, [])) == 1:
            only_state = dbip["city_states"][city_norm][0]
            dbip_xy = dbip["by_state_city"].get(f"{only_state}|{city_norm}")
        if dbip_xy:
            return {"en": en, "geoname_id": 0, "lat": dbip_xy[0],
                    "lon": dbip_xy[1], "radius": 50,
                    "source": origin + "+pinyin-dbip-coords"}
        if city_zh in mq.CITY_COORDS:
            lat, lon = mq.CITY_COORDS[city_zh]
            return {"en": en, "geoname_id": 0, "lat": lat, "lon": lon,
                    "radius": 100, "source": origin + "+pinyin-hand-coords"}
        lat, lon = capital_coords[iso]
        return {"en": en, "geoname_id": 0, "lat": lat, "lon": lon,
                "radius": 250, "source": origin + "+pinyin"}

    n_cidr = 0
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for (iso, city_zh), ranges in sorted(
                groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
            ranges.sort()
            merged = []
            for s, e, origin in ranges:
                if merged and s <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e, origin])
            # dominant origin for the group's source label
            origin = Counter(o for _, _, o in ranges).most_common(1)[0][0]
            meta = resolve(iso, city_zh, origin)
            if city_zh is None:
                stats["province_only_groups"] += 1
            elif meta["source"].startswith("geocn"):
                stats["city_groups_geocn"] += 1
            else:
                stats["city_groups_ipdb"] += 1
            for s, e, _ in merged:
                for net in ipaddress.summarize_address_range(
                        ipaddress.IPv6Address(s), ipaddress.IPv6Address(e)):
                    f.write(json.dumps({
                        "cidr": str(net), "prov": iso,
                        "city_zh": city_zh or "", "city_en": meta["en"],
                        "geoname_id": meta["geoname_id"],
                        "lat": meta["lat"], "lon": meta["lon"],
                        "radius": meta["radius"], "source": meta["source"],
                        "origin": origin,
                    }, ensure_ascii=False) + "\n")
                    n_cidr += 1
    stats["cidrs"] = n_cidr
    stats["groups"] = len(groups)
    json.dump(dict(stats), open(stats_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    for k in sorted(stats):
        print(f"{k}={stats[k]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
         sys.argv[6] if len(sys.argv) > 6 else None,
         sys.argv[7] if len(sys.argv) > 7 else None,
         sys.argv[8] if len(sys.argv) > 8 else None)
