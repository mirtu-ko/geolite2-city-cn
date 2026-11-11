#!/usr/bin/env python3
"""Generate verification sample sets for the merged mmdb (§5.3 of the spec).

Outputs work/verify_samples.json:
  mainland: 60 IPv4 addresses sampled from qqwry CN city records,
            stratified 20 each by ISP area (移动/联通/电信), random IP inside
            the record range. Expected: city rate >= 90% in the merged DB.
  overseas_named: 24 well-known overseas IPs (one per region where possible).
  overseas_sample: 20000 first-addresses of non-CN GeoLite2 IPv4 networks,
            deterministic seed. Expected: merged == original on all of them.
  ipv6_sample: 5000 first-addresses of GeoLite2 IPv6 networks (CN + non-CN).
            Expected: merged == original on all of them (nothing IPv6 inserted).
"""
import json
import random
import sys

import ipaddress

random.seed(20261111)
ROOT = "/home/hatch/workspace/umami-geo-cn"
QQWRY_TSV = f"{ROOT}/work/qqwry_fw.tsv"
GEOLITE_CSV = f"{ROOT}/work/geolite_networks.csv"


def rand_ip_in(start, end):
    return str(ipaddress.IPv4Address(random.randint(start, end)))


def main():
    # ---- mainland: stratified by ISP area field
    buckets = {"移动": [], "联通": [], "电信": []}
    with open(QQWRY_TSV) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            start, end, country, area = int(parts[0]), int(parts[1]), parts[2], parts[3]
            if not country.startswith("中国–") or "–" not in country[3:]:
                continue  # province-only record (no city part)
            city_part = country.split("–")[2] if country.count("–") >= 2 else ""
            if not city_part:
                continue
            for isp in buckets:
                if isp in area:
                    buckets[isp].append((start, end))
                    break
    mainland = []
    for isp, recs in buckets.items():
        random.shuffle(recs)
        for start, end in recs[:20]:
            mainland.append({"ip": rand_ip_in(start, end), "isp": isp})
    print("mainland samples:", len(mainland),
          {k: len([m for m in mainland if m["isp"] == k]) for k in buckets})

    # ---- overseas + ipv6: first address of sampled GeoLite2 networks
    overseas, ipv6 = [], []
    with open(GEOLITE_CSV) as f:
        for line in f:
            net, country, region, city = line.rstrip("\n").split(",", 3)
            try:
                n = ipaddress.ip_network(net)
            except ValueError:
                continue
            if n.version == 4 and country not in ("CN", ""):
                overseas.append(str(n.network_address))
            elif n.version == 6:
                ipv6.append(str(n.network_address))
    random.shuffle(overseas)
    random.shuffle(ipv6)
    overseas_sample = overseas[:20000]
    ipv6_sample = ipv6[:5000]
    print("overseas networks:", len(overseas), "-> sample", len(overseas_sample))
    print("ipv6 networks:", len(ipv6), "-> sample", len(ipv6_sample))

    # NOTE: 114.114.114.114 / 180.76.76.76 / 119.29.29.29 / 140.205.19.6 /
    # 223.5.5.5 / 139.196.1.1 / 47.100.1.1 are mainland-China DNS/cloud IPs
    # and must NOT be in the overseas list (they were, by mistake, in v1).
    named = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9",
             "192.161.160.202", "208.67.222.222", "77.88.8.8",
             "54.231.1.1", "13.107.21.200",
             "104.16.1.1", "172.67.1.1", "185.60.216.35", "151.101.1.140",
             "198.51.100.1", "203.0.113.1", "193.108.88.1"]
    out = {
        "mainland": mainland,
        "overseas_named": named,
        "overseas_sample": overseas_sample,
        "ipv6_sample": ipv6_sample,
    }
    with open(f"{ROOT}/work/verify_samples.json", "w") as f:
        json.dump(out, f)
    print("wrote work/verify_samples.json")


if __name__ == "__main__":
    main()
