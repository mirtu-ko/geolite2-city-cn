#!/usr/bin/env python3
"""Parse qqwry.dat (GBK, classic or FW-normalised format) and emit the
mainland-China overlay as CIDRs.

Inputs:
  data/qqwry.dat            (qqwry.dat, GBK-encoded, either classic
                             "湖北省武汉市" style or FW "中国–湖北–武汉" style)
  work/geolite_cn.json      (from build/cmd/extract_geolite: GeoLite2 CN
                             provinces/cities with en names + coordinates)
Outputs:
  work/merged_cidrs.jsonl   one JSON object per CIDR:
      {cidr, prov, city_zh, city_en, geoname_id, lat, lon, radius}
  work/merge_stats.json     counts + the pinyin-fallback city list
Rules (task §4):
  - only mainland China (CN); HK/MO/TW are left to GeoLite2, never relabelled CN
  - province-only records keep country+province, city empty
  - municipalities (BJ/SH/TJ/CQ): province and city share the name
  - private/reserved IPv4 ranges are never written
  - city English names come from GeoLite2 first (same spelling/style),
    pinyin (toneless, capitalised, apostrophe rule) only as fallback
"""
import bisect
import ipaddress
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------- qqwry.dat
def int3(d, o):
    return d[o] + (d[o + 1] << 8) + (d[o + 2] << 16)

def int4(d, o):
    return d[o] + (d[o + 1] << 8) + (d[o + 2] << 16) + (d[o + 3] << 24)

def _get_addr(d, offset):
    mode = d[offset]
    if mode == 1:
        offset = int3(d, offset + 1)
        mode = d[offset]
    if mode == 2:
        off1 = int3(d, offset + 1)
        c = d[off1:d.index(b"\x00", off1)]
        offset += 4
    else:
        c = d[offset:d.index(b"\x00", offset)]
        offset += len(c) + 1
    if d[offset] == 2:
        offset = int3(d, offset + 1)
    p = d[offset:d.index(b"\x00", offset)]
    return c.decode("gb18030", errors="replace"), p.decode("gb18030", errors="replace")

def load_rir_allocations(path):
    """APNIC delegated stats -> sorted [(start_int, end_int, country)]."""
    allocs = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or "|" not in line:
                continue
            p = line.rstrip("\n").split("|")
            if len(p) < 7 or p[2] != "ipv4":
                continue
            try:
                s = int(ipaddress.IPv4Address(p[3]))
                c = int(p[4])
            except ValueError:
                continue
            allocs.append((s, s + c - 1, p[1]))
    allocs.sort()
    return allocs


def split_by_allocation(allocs, starts, start, end):
    """Split [start, end] into sub-ranges, each inside one RIR allocation.

    Yields (s, e, cc); cc is None for gaps (no allocation covers them).
    """
    cur = start
    while cur <= end:
        i = bisect.bisect_right(starts, cur) - 1
        if i < 0 or allocs[i][1] < cur:
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            gap_end = min(end, nxt - 1) if nxt is not None else end
            yield (cur, gap_end, None)
            cur = gap_end + 1
        else:
            _, e, cc = allocs[i]
            sub_end = min(end, e)
            yield (cur, sub_end, cc)
            cur = sub_end + 1


def parse_qqwry(path):
    """Yield (start_int, end_int, country_str, area_str) for every record."""
    d = open(path, "rb").read()
    first, last = int4(d, 0), int4(d, 4)
    n = (last - first) // 7 + 1
    for i in range(n):
        off = first + i * 7
        start = int4(d, off)
        rec_off = int3(d, off + 4)
        end = int4(d, rec_off)
        c, a = _get_addr(d, rec_off + 4)
        yield start, end, c, a

# ---------------------------------------------------------------- province table
# short name -> (ISO 3166-2, full zh, en). ISO codes are task §4.1, verbatim.
PROVINCES = {
    "北京": ("BJ", "北京市", "Beijing"), "天津": ("TJ", "天津市", "Tianjin"),
    "河北": ("HE", "河北省", "Hebei"), "山西": ("SX", "山西省", "Shanxi"),
    "内蒙古": ("NM", "内蒙古自治区", "Inner Mongolia"),
    "辽宁": ("LN", "辽宁省", "Liaoning"), "吉林": ("JL", "吉林省", "Jilin"),
    "黑龙江": ("HL", "黑龙江省", "Heilongjiang"),
    "上海": ("SH", "上海市", "Shanghai"), "江苏": ("JS", "江苏省", "Jiangsu"),
    "浙江": ("ZJ", "浙江省", "Zhejiang"), "安徽": ("AH", "安徽省", "Anhui"),
    "福建": ("FJ", "福建省", "Fujian"), "江西": ("JX", "江西省", "Jiangxi"),
    "山东": ("SD", "山东省", "Shandong"), "河南": ("HA", "河南省", "Henan"),
    "湖北": ("HB", "湖北省", "Hubei"), "湖南": ("HN", "湖南省", "Hunan"),
    "广东": ("GD", "广东省", "Guangdong"), "广西": ("GX", "广西壮族自治区", "Guangxi"),
    "海南": ("HI", "海南省", "Hainan"), "重庆": ("CQ", "重庆市", "Chongqing"),
    "四川": ("SC", "四川省", "Sichuan"), "贵州": ("GZ", "贵州省", "Guizhou"),
    "云南": ("YN", "云南省", "Yunnan"), "西藏": ("XZ", "西藏自治区", "Tibet"),
    "陕西": ("SN", "陕西省", "Shaanxi"), "甘肃": ("GS", "甘肃省", "Gansu"),
    "青海": ("QH", "青海省", "Qinghai"), "宁夏": ("NX", "宁夏回族自治区", "Ningxia"),
    "新疆": ("XJ", "新疆维吾尔自治区", "Xinjiang"),
}
# not merged into CN (task §3); returned as a sentinel to skip
SAR = {"台湾": "TW", "香港": "HK", "澳门": "MO"}
MUNICIPALITIES = {"BJ": "北京", "SH": "上海", "TJ": "天津", "CQ": "重庆"}
# province capital (zh) for province-only records and pinyin-fallback coords
CAPITALS = {
    "BJ": "北京", "TJ": "天津", "HE": "石家庄", "SX": "太原", "NM": "呼和浩特",
    "LN": "沈阳", "JL": "长春", "HL": "哈尔滨", "SH": "上海", "JS": "南京",
    "ZJ": "杭州", "AH": "合肥", "FJ": "福州", "JX": "南昌", "SD": "济南",
    "HA": "郑州", "HB": "武汉", "HN": "长沙", "GD": "广州", "GX": "南宁",
    "HI": "海口", "CQ": "重庆", "SC": "成都", "GZ": "贵阳", "YN": "昆明",
    "XZ": "拉萨", "SN": "西安", "GS": "兰州", "QH": "西宁", "NX": "银川",
    "XJ": "乌鲁木齐",
}

ETHNIC_MARKERS = ["藏族", "羌族", "彝族", "苗族", "土家族", "侗族", "回族",
                  "蒙古族", "朝鲜族", "哈萨克", "柯尔克孜", "傣族", "白族",
                  "布依族", "哈尼族", "壮族", "景颇族", "傈僳族", "水族",
                  "仡佬族", "毛南族", "京族", "塔吉克", "乌孜别克", "俄罗斯族",
                  "鄂温克族", "鄂伦春族", "达斡尔族", "锡伯族", "裕固族",
                  "东乡族", "保安族", "撒拉族", "土族", "仫佬族", "普米族",
                  "怒族", "基诺族", "德昂族", "独龙族", "赫哲族", "珞巴族",
                  "门巴族", "畲族", "高山族", "黎族", "纳西族",
                  # bare forms (names written without '族', e.g. '巴音郭楞蒙古自治州')
                  "蒙古", "藏", "羌", "彝", "苗", "土家", "侗", "回",
                  "朝鲜", "傣", "白", "布依", "哈尼", "壮", "景颇", "傈僳",
                  "水", "仡佬", "毛南", "京", "塔吉克", "乌孜别克"]
ZONE_SUFFIXES = ("高新技术产业开发区", "经济技术开发区", "经济开发区",
                 "高新区", "开发区", "工业园区", "经开区", "高新开发区")

def stem_prefecture(name):
    """'阿坝藏族羌族自治州' -> '阿坝'; '喀什地区' -> '喀什'; '锡林郭勒盟' -> '锡林郭勒'."""
    n = name.strip()
    for suf in ZONE_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    if "自治区" in n:  # e.g. '壮族自治区南宁市' -> '南宁市'
        n = n.split("自治区", 1)[1]
        if not n:
            return ""
    for suf in ("自治州", "自治县"):
        if suf in n:
            n = n.split(suf)[0]
            # strip ethnic markers from the END only, longest first
            # ('恩施土家族苗族' -> '恩施', '巴音郭楞蒙古' -> '巴音郭楞',
            #  '陵水黎族' -> '陵水' -- the '水' inside 陵水 must survive)
            changed = True
            while changed:
                changed = False
                for m in sorted(ETHNIC_MARKERS, key=len, reverse=True):
                    if n.endswith(m) and (m.endswith("族") or len(m) >= 2):
                        n = n[: -len(m)]
                        changed = True
                        break
            return n
    # '大兴安岭地区漠河县' -> the prefecture is before '地区'
    if "地区" in n:
        n = n.split("地区", 1)[0]
    # loop: '兴安盟市' -> strip 市, then 盟 -> '兴安'
    changed = True
    while changed:
        changed = False
        for suf in ("市", "县"):
            if n.endswith(suf) and len(n) > 1:
                n = n[: -len(suf)]
                changed = True
                break
        if n.endswith("区") and not n.endswith("林区") and len(n) > 1:
            n = n[:-1]
            changed = True
        for suf in ("地区", "盟"):
            if n.endswith(suf) and len(n) > len(suf):
                n = n[: -len(suf)]
                changed = True
                break
    return n

def split_prov_city(country):
    """Return (prov_iso, city_zh_or_None) for a mainland record, or None.

    Handles both qqwry spellings:
      FW:      '中国–湖北–武汉' / '中国–广东' / '中国–北京–北京–海淀区'
      classic: '湖北省武汉市' / '广东省' / '北京市海淀区' / '新疆喀什地区'
    HK/MO/TW -> None (left to GeoLite2, never CN).
    """
    s = country.strip()
    if not s or s in ("中国", "中国大陆"):
        return None
    parts = re.split(r"[–—\-]", s)
    if parts[0] == "中国":
        if len(parts) < 2:
            return None
        prov_name = parts[1].strip()
        if prov_name in SAR:
            return None
        if prov_name not in PROVINCES:
            return None
        iso = PROVINCES[prov_name][0]
        if iso in MUNICIPALITIES:
            return iso, MUNICIPALITIES[iso], ""
        if len(parts) < 3 or not parts[2].strip():
            return iso, None, ""
        raw = parts[2].split("/")[0].strip()
        city = stem_prefecture(raw)
        city = CITY_ALIASES.get(city, city)
        return iso, (city or None), raw
    # classic spelling (no '中国–' prefix)
    if s.startswith("台湾") or s in ("香港", "澳门"):
        return None
    m = re.match(r"^(内蒙古|广西|西藏|宁夏|新疆)(?:自治区)?(.*)$", s)
    if not m:
        m = re.match(r"^(.+?)省(.*)$", s)
    if not m:
        m = re.match(r"^(北京市|上海市|天津市|重庆市)(.*)$", s)
        if m:
            prov_name = m.group(1)[:-1]
            iso = PROVINCES[prov_name][0]
            return iso, MUNICIPALITIES[iso], ""
        return None
    prov_name, rest = m.group(1), m.group(2)
    if prov_name in SAR:
        return None
    if prov_name not in PROVINCES:
        return None
    iso = PROVINCES[prov_name][0]
    if iso in MUNICIPALITIES:
        return iso, MUNICIPALITIES[iso], ""
    if not rest:
        return iso, None, ""
    # rest like '武汉市', '武汉市江汉区', '喀什地区', '锡林郭勒盟'
    mm = re.match(r"^(.+?市|.+?地区|.+?盟|.+?自治州|.+?自治县)", rest)
    city_raw = mm.group(1) if mm else rest
    city = stem_prefecture(city_raw)
    city = CITY_ALIASES.get(city, city)
    return iso, (city or None), city_raw

RESERVED = [ipaddress.ip_network(x) for x in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.31.196.0/24", "192.52.193.0/24", "192.88.99.0/24",
    "192.168.0.0/16", "192.175.48.0/24", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "255.255.255.255/32",
)]

def is_reserved(start_int):
    ip = ipaddress.IPv4Address(start_int)
    return any(ip in net for net in RESERVED)

# Prefecture -> seat city (DB-IP coordinate lookup only; the displayed city
# name stays the prefecture name, e.g. 延边 keeps 'Yanbian').
# qqwry spellings that are not a plain city name (concatenated city+county,
# former city names, new-area names) -> the city to report.
CITY_ALIASES = {
    "临沂苍山县": "临沂", "青岛胶南": "青岛", "贵阳贵安新区": "贵阳",
}

SEAT_ALIASES = {
    "延边": "Yanji", "巴音郭楞": "Korla", "湘西": "Jishou",
    "黔东南": "Kaili", "西双版纳": "Jinghong", "博尔塔拉": "Bole",
    "甘孜": "Kangding", "红河": "Mengzi",
}

CITY_COORDS = {
    "吕梁": (37.52, 111.13), "齐齐哈尔": (47.35, 123.92), "伊犁": (43.92, 81.32),
    "漯河": (33.58, 114.02), "黔南": (26.26, 107.51), "遂宁": (30.53, 105.59),
    "塔城": (46.75, 82.98), "钦州": (21.98, 108.65), "双鸭山": (46.65, 131.16),
    "六盘水": (26.59, 104.83), "商洛": (33.87, 109.94), "文山": (23.37, 104.22),
    "黔西南": (25.09, 104.90), "海东": (36.50, 102.11), "锡林郭勒": (43.94, 116.09),
    "吐鲁番": (42.95, 89.19), "七台河": (45.77, 131.00), "德宏": (24.43, 98.58),
    "防城港": (21.61, 108.35), "阿勒泰": (47.85, 88.13), "兴安": (46.08, 122.07),
    "天门": (30.66, 113.16), "阿坝": (31.90, 102.22), "大兴安岭": (50.42, 124.12),
    "昌都": (31.14, 97.18), "海南": (36.29, 100.62), "山南": (29.24, 91.77),
    "阿拉善": (38.85, 105.67), "怒江": (27.72, 98.86), "克孜勒苏": (39.71, 76.17),
    "迪庆": (27.83, 99.71), "海西": (37.38, 97.37), "甘南": (34.98, 102.91),
    "海北": (36.96, 100.90), "黄南": (35.52, 102.02), "阿拉尔": (40.55, 81.28),
    "北屯": (47.35, 87.82), "图木舒克": (39.87, 79.07), "五家渠": (44.17, 87.54),
    "乐东": (18.74, 109.17), "澄迈": (19.74, 110.01), "琼中": (19.03, 109.84),
    "保亭": (18.64, 109.70), "屯昌": (19.35, 110.10), "东方": (19.10, 108.65),
    "阿里": (32.50, 80.10), "神农架林区": (31.75, 110.67), "陵水": (18.50, 110.04),
    "临高": (19.69, 109.69),
}

# ---------------------------------------------------------------- pinyin fallback
# Names where plain pinyin is wrong or non-obvious; checked against GeoLite2
# spellings and standard transliterations.
PINYIN_EXCEPTIONS = {
    "西安": "Xi'an", "延安": "Yan'an", "六安": "Lu'an", "瑞安": "Rui'an",
    "长安": "Chang'an", "盘安": "Pan'an", "兴安": "Xing'an",
    "喀什": "Kashgar", "和田": "Hotan", "阿克苏": "Aksu", "吐鲁番": "Turpan",
    "乌鲁木齐": "Urumqi", "克拉玛依": "Karamay", "伊犁": "Yili",
    "阿勒泰": "Altay", "塔城": "Tacheng", "博尔塔拉": "Bortala",
    "巴音郭楞": "Bayingolin", "克孜勒苏": "Kizilsu", "哈密": "Hami",
    "昌吉": "Changji", "石河子": "Shihezi", "阿拉尔": "Aral",
    "图木舒克": "Tumxuk", "五家渠": "Wujiaqu", "北屯": "Beitun",
    "铁门关": "Tiemenguan", "双河": "Shuanghe", "可克达拉": "Kokdala",
    "昆玉": "Kunyu", "胡杨河": "Huyanghe", "新星": "Xinxing",
    "白杨": "Baiyang", "霍尔果斯": "Khorgos",
    "呼和浩特": "Hohhot", "乌兰察布": "Ulanqab", "巴彦淖尔": "Bayannur",
    "鄂尔多斯": "Ordos", "呼伦贝尔": "Hulunbuir", "阿拉善": "Alxa",
    "锡林郭勒": "Xilingol", "锡林浩特": "Xilinhot", "二连浩特": "Erenhot",
    "满洲里": "Manzhouli", "阿尔山": "Arxan", "乌兰浩特": "Ulanhot",
    "霍林郭勒": "Huolinguole", "扎兰屯": "Zhalantun", "牙克石": "Yakeshi",
    "额尔古纳": "Ergun", "根河": "Genhe", "包头": "Baotou",
    "蚌埠": "Bengbu", "乐清": "Yueqing", "临安": "Lin'an", "淳安": "Chun'an",
    "雅安": "Ya'an", "淮安": "Huai'an", "泰安": "Tai'an", "马鞍山": "Ma'anshan",
    "哈尔滨": "Harbin",
    "拉萨": "Lhasa", "日喀则": "Shigatse", "昌都": "Qamdo",
    "林芝": "Nyingchi", "山南": "Shannan", "那曲": "Nagqu", "阿里": "Ngari",
    "大兴安岭": "Daxing'anling", "兴安盟": "Xing'an",
    "黔东南": "Qiandongnan", "黔南": "Qiannan", "黔西南": "Qianxinan",
    "阿坝": "Aba", "甘孜": "Garze", "凉山": "Liangshan",
    "恩施": "Enshi", "延边": "Yanbian", "大理": "Dali",
    "楚雄": "Chuxiong", "红河": "Honghe", "文山": "Wenshan",
    "西双版纳": "Xishuangbanna", "德宏": "Dehong", "怒江": "Nujiang",
    "迪庆": "Diqing", "临夏": "Linxia", "甘南": "Gannan",
    "海西": "Haixi", "玉树": "Yushu", "果洛": "Golog",
    "海南": "Hainan", "海北": "Haibei", "海东": "Haidong", "黄南": "Huangnan",
}

def pinyin_en(city_zh):
    from pypinyin import lazy_pinyin
    if city_zh in PINYIN_EXCEPTIONS:
        return PINYIN_EXCEPTIONS[city_zh]
    syls = lazy_pinyin(city_zh)
    out = ""
    for i, syl in enumerate(syls):
        if i and syl and syl[0] in "aoe" and out and out[-1] not in "aeiou'":
            # Xi'an / Yan'an / Lu'an rule: apostrophe before a/o/e-initial syllable
            # (only when the previous syllable ends in a consonant, e.g. xi+an)
            out += "'"
        out += syl.capitalize() if i == 0 else syl
        # capitalise each syllable's first letter for readability: XiAn is wrong,
        # pinyin place names are written as one word with only the first capital,
        # except the apostrophe case (Xi'an). So keep the rest lower-case.
    # The loop above capitalised only the first syllable; fix: first letter upper.
    return out[0].upper() + out[1:] if out else city_zh

def main(qqwry_path, geolite_json, out_jsonl, stats_path, dbip_json=None,
         rir_path=None):
    dbip = {"by_state_city": {}, "city_states": {}}
    if dbip_json:
        dbip = json.load(open(dbip_json, encoding="utf-8"))
    iso_to_en = {v[0]: v[2] for v in PROVINCES.values()}
    geo = json.load(open(geolite_json, encoding="utf-8"))
    cities = geo["cities"]          # key "ISO|cityZh" -> {en, geoname_id, lat, lon, radius}
    cities_by_en = geo.get("cities_by_en", {})  # key normalised en -> same
    provinces = geo["provinces"]    # ISO -> {en, zh, geoname_id}

    def norm_en(name):
        n = name.lower().replace("'", "").replace(" ", "").replace(".", "").replace("-", "")
        for suf in ("city", "shi"):
            if n.endswith(suf):
                n = n[: -len(suf)]
        return n
    # province capital coordinates (from GeoLite2 city map; fallback: median of its cities)
    capital_coords = {}
    for iso, cap in CAPITALS.items():
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
            capital_coords[iso] = (34.7732, 113.722)  # GeoLite2 CN default, last resort
    # Pass 1: parse all records once, collecting the clean prefecture names
    # (raw city part ended with 市/地区/盟/自治州/自治县/县, e.g. '乌兰察布市').
    # Pass 2 then truncates qqwry concatenations like '雅安名山' (Ya'an +
    # Mingshan district) or '呼伦贝尔莫力达瓦旗' (Hulunbuir + Morin Dawa
    # banner) to the longest known prefecture city in the same province.
    # (GeoLite2 alone cannot supply these names: it has no 乌兰察布/呼伦贝尔.)
    rir_allocs, rir_starts = [], []
    if rir_path:
        rir_allocs = load_rir_allocations(rir_path)
        rir_starts = [a[0] for a in rir_allocs]
        print(f"rir_allocations={len(rir_allocs)} from {rir_path}", file=sys.stderr)

    records = []
    clean_names = defaultdict(set)
    stats = Counter()
    for start, end, country, _area in parse_qqwry(qqwry_path):
        stats["qqwry_records"] += 1
        if is_reserved(start):
            stats["skipped_reserved"] += 1
            continue
        parsed = split_prov_city(country)
        if parsed is None:
            stats["skipped_non_cn_mainland"] += 1
            continue
        iso, city_zh, raw = parsed
        stats["cn_records"] += 1
        stats["cn_addresses"] += end - start + 1
        # RIR guard: only overlay sub-ranges the APNIC delegated file
        # allocates to CN. qqwry mislabels ~500 ranges (foreign cloud/CDN
        # space as 北京, South/Southeast Asian space as 马鞍山, TW ranges
        # as mainland cities); without this guard they would overwrite
        # correct GeoLite2 overseas records and break §5.3 (0 differences).
        for s0, e0, cc in split_by_allocation(rir_allocs, rir_starts, start, end):
            if cc != "CN":
                stats["skipped_rir_not_cn"] += 1
                stats["skipped_rir_not_cn_addresses"] += e0 - s0 + 1
                continue
            records.append((s0, e0, iso, city_zh))
        if city_zh and raw.strip().endswith(("市", "地区", "盟", "自治州", "自治县")):
            clean_names[iso].add(city_zh)

    known_cities = defaultdict(set)
    for k in cities:
        iso_k, zh_k = k.split("|", 1)
        known_cities[iso_k].add(zh_k)
    for iso_k, names in clean_names.items():
        known_cities[iso_k].update(names)
    # static prefecture list derived from the classic qqwry spellings
    # (build/prefecture_cities.json): covers prefectures GeoLite2 lacks,
    # e.g. 安庆/玉溪/呼伦贝尔/乌兰察布, so their concatenations truncate.
    pref_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "prefecture_cities.json")
    if os.path.exists(pref_path):
        with open(pref_path) as fh:
            for iso_k, names in json.load(fh)["cities"].items():
                known_cities[iso_k].update(names)
    known_cities = {k: sorted(v, key=len, reverse=True)
                    for k, v in known_cities.items()}

    def truncate_to_known_city(iso, city_zh):
        if city_zh is None:
            return None
        if f"{iso}|{city_zh}" in cities:
            return city_zh
        for cand in known_cities.get(iso, []):
            if len(cand) >= 2 and city_zh.startswith(cand) and len(city_zh) > len(cand):
                return cand
        return city_zh

    # cross-province city lookup (only when the zh name is unique in GeoLite2)
    by_city = defaultdict(list)
    for k, v in cities.items():
        by_city[k.split("|", 1)[1]].append((k.split("|", 1)[0], v))

    groups = defaultdict(list)   # (iso, city_zh) -> list of (start, end)
    city_meta = {}               # (iso, city_zh) -> {en, geoname_id, lat, lon, radius, source}
    pinyin_fallback = Counter()  # city_zh -> address count
    for start, end, iso, city_zh in records:
        city_zh = truncate_to_known_city(iso, city_zh)
        groups[(iso, city_zh)].append((start, end))
        if (iso, city_zh) in city_meta:
            continue
        if city_zh is None:
            lat, lon = capital_coords[iso]
            city_meta[(iso, None)] = {"en": "", "geoname_id": 0,
                                      "lat": lat, "lon": lon, "radius": 250,
                                      "source": "province-capital"}
            stats["province_only_groups"] += 1
            continue
        hit = cities.get(f"{iso}|{city_zh}")
        if hit:
            city_meta[(iso, city_zh)] = {"en": hit["en"], "geoname_id": hit["geoname_id"],
                                         "lat": hit["lat"], "lon": hit["lon"],
                                         "radius": hit["radius"], "source": "geolite2"}
            stats["city_geolite2_hit"] += 1
            continue
        uniq = by_city.get(city_zh, [])
        if len(uniq) == 1:
            v = uniq[0][1]
            city_meta[(iso, city_zh)] = {"en": v["en"], "geoname_id": v["geoname_id"],
                                         "lat": v["lat"], "lon": v["lon"],
                                         "radius": v["radius"], "source": "geolite2-other-province"}
            stats["city_geolite2_cross_province"] += 1
            continue
        en = pinyin_en(city_zh)
        # recover real coordinates from GeoLite2 by English name when the
        # Chinese name is missing there (e.g. Taicang) or the city is absent
        # under its zh name; only the spelling comes from pinyin.
        by_en = cities_by_en.get(norm_en(en))
        if by_en:
            city_meta[(iso, city_zh)] = {"en": by_en["en"], "geoname_id": by_en["geoname_id"],
                                         "lat": by_en["lat"], "lon": by_en["lon"],
                                         "radius": by_en["radius"],
                                         "source": "pinyin+geolite2-coords"}
            stats["city_pinyin_fallback"] += 1
            stats["city_coords_from_geolite2_en"] += 1
            continue
        # DB-IP Lite coordinates (coordinates only; assignment stays qqwry).
        # State-qualified first: 'Yiyang' is both 益阳 (Hunan) and 宜阳 (Henan).
        prov_en_norm = norm_en(iso_to_en[iso])
        city_norm = norm_en(SEAT_ALIASES.get(city_zh, en))
        dbip_xy = dbip["by_state_city"].get(f"{prov_en_norm}|{city_norm}")
        if dbip_xy is None and len(dbip["city_states"].get(city_norm, [])) == 1:
            only_state = dbip["city_states"][city_norm][0]
            dbip_xy = dbip["by_state_city"].get(f"{only_state}|{city_norm}")
        if dbip_xy:
            city_meta[(iso, city_zh)] = {"en": en, "geoname_id": 0,
                                         "lat": dbip_xy[0], "lon": dbip_xy[1],
                                         "radius": 50, "source": "pinyin+dbip-coords"}
            stats["city_pinyin_fallback"] += 1
            stats["city_coords_from_dbip"] += 1
            continue
        if city_zh in CITY_COORDS:
            lat, lon = CITY_COORDS[city_zh]
            city_meta[(iso, city_zh)] = {"en": en, "geoname_id": 0,
                                         "lat": lat, "lon": lon, "radius": 100,
                                         "source": "pinyin+hand-coords"}
            stats["city_pinyin_fallback"] += 1
            stats["city_coords_hand"] += 1
            continue
        lat, lon = capital_coords[iso]
        city_meta[(iso, city_zh)] = {"en": en, "geoname_id": 0,
                                     "lat": lat, "lon": lon, "radius": 250,
                                     "source": "pinyin"}
        stats["city_pinyin_fallback"] += 1

    # aggregate: merge adjacent ranges per group, then summarise to CIDRs
    n_cidr = 0
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for (iso, city_zh), ranges in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
            ranges.sort()
            merged = []
            for s, e in ranges:
                if merged and s <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            meta = city_meta[(iso, city_zh)]
            if meta["source"] == "pinyin":
                pinyin_fallback[city_zh or ""] += sum(e - s + 1 for s, e in merged)
            for s, e in merged:
                for net in ipaddress.summarize_address_range(
                        ipaddress.IPv4Address(s), ipaddress.IPv4Address(e)):
                    f.write(json.dumps({
                        "cidr": str(net), "prov": iso,
                        "city_zh": city_zh or "", "city_en": meta["en"],
                        "geoname_id": meta["geoname_id"],
                        "lat": meta["lat"], "lon": meta["lon"],
                        "radius": meta["radius"], "source": meta["source"],
                    }, ensure_ascii=False) + "\n")
                    n_cidr += 1
    stats["cidrs"] = n_cidr
    stats["groups"] = len(groups)
    stats["pinyin_fallback_cities"] = sorted(pinyin_fallback.items(),
                                             key=lambda kv: -kv[1])
    stats["cn_addresses_by_province"] = {}
    json.dump(dict(stats), open(stats_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    for k in sorted(stats):
        if k not in ("pinyin_fallback_cities", "cn_addresses_by_province"):
            print(f"{k}={stats[k]}")
    print("pinyin_fallback_cities:")
    for name, addrs in stats["pinyin_fallback_cities"][:40]:
        print(f"  {name}: {addrs} addresses")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
         sys.argv[5] if len(sys.argv) > 5 else None,
         sys.argv[6] if len(sys.argv) > 6 else None)
