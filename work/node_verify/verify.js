// Verification for GeoLite2-City-CN.mmdb: spec §5.1, §5.2, §5.3.
//
// Usage: node verify.js <merged.mmdb> <original.mmdb> <verify_samples.json> <out.json>
//
// §5.1  load + lookup 111.4.16.80, metadata ip_version, file size
// §5.2  11 spec IPs: result vs the spec table AND vs the verified ground truth
// §5.3  mainland city rate (merged vs original, target >=90%)
//       overseas: merged vs original must be 0 differences (named + 20k sample)
//       IPv6: merged vs original must be 0 differences (5k sample)
const fs = require("fs");
const maxmind = require("maxmind");

const [mergedPath, origPath, samplesPath, outPath] = process.argv.slice(2);

function triple(r) {
  if (!r) return { country: "", region: "", city: "" };
  return {
    country: r.country?.iso_code ?? r.registered_country?.iso_code ?? "",
    region: r.subdivisions?.[0]?.iso_code ?? "",
    city: r.city?.names?.en ?? "",
  };
}
const key = (t) => `${t.country}|${t.region}|${t.city}`;

async function main() {
  const merged = await maxmind.open(mergedPath);
  const orig = await maxmind.open(origPath);
  const samples = JSON.parse(fs.readFileSync(samplesPath, "utf8"));
  const result = { s51: {}, s52: [], s53: {} };

  // ---- §5.1
  const size = fs.statSync(mergedPath).size;
  const probe = merged.get("111.4.16.80");
  result.s51 = {
    file_bytes: size,
    file_mb: +(size / 1048576).toFixed(1),
    size_ok_40_100mb: size >= 40 * 1048576 && size <= 100 * 1048576,
    ip_version: merged.metadata.ipVersion,
    database_type: merged.metadata.databaseType,
    node_count: merged.metadata.nodeCount,
    probe_111_4_16_80: probe ?? null,
  };

  // ---- §5.2: spec table vs verified ground truth (three independent
  // sources: GeoLite2, qqwry classic 2022, qqwry FW 2024, ip2region).
  // The spec table is wrong on 6 of its 11 rows; the build follows the
  // evidence, so both comparisons are reported.
  const spec52 = [
    ["111.4.16.80", "CN", "GD", "Guangzhou"],
    ["39.155.0.39", "CN", "GD", "Guangzhou"],
    ["183.7.199.179", "CN", "GD", "Guangzhou"],
    ["116.179.33.137", "CN", "BJ", "Jinrongjie"],
    ["183.216.98.122", "CN", "JX", "Nanchang"],
    ["58.243.157.254", "CN", "AH", "Hefei"],
    ["223.5.5.5", "CN", "ZJ", "Hangzhou"],
    ["2409:8a38:28:5a50:2cb3:d356:ea83:44c0", "CN", "BJ", "Beijing"],
    ["2409:8a4c:ecd:b00:1497:11ff:fec1:eedb", "CN", "HB", "Xiaogan"],
    ["192.161.160.202", "US", "CA", "Los Angeles"],
    ["8.8.8.8", "US", "", ""],
  ];
  const truth52 = {
    "111.4.16.80": ["CN", "HB", "Wuhan"],
    "39.155.0.39": ["CN", "NM", "Chifeng"],
    "183.7.199.179": ["CN", "GD", "Shantou"],
    "116.179.33.137": ["CN", "SX", "Yangquan"],
    "183.216.98.122": ["CN", "JX", "Nanchang"],
    "58.243.157.254": ["CN", "AH", "Bengbu"],
    "223.5.5.5": ["CN", "ZJ", "Hangzhou"],
    // v2: the IPv6 overlay (GeoCN primary) now fills this address.
    // GeoCN division_code 360102 = 江西南昌. Other sources disagree
    // (qqwry.ipdb 陕西, ip2region 广东广州, DB-IP 北京金荣街), so this
    // is GeoCN's value as the agreed primary source, not an
    // independently verified ground truth; it replaces the v1
    // country-only assertion (GeoLite2 had CN only here).
    "2409:8a38:28:5a50:2cb3:d356:ea83:44c0": ["CN", "JX", "Nanchang"],
    "2409:8a4c:ecd:b00:1497:11ff:fec1:eedb": ["CN", "HB", "Xiaogan"],
    "192.161.160.202": ["US", "CA", "Los Angeles"],
    "8.8.8.8": ["US", "", ""],
  };
  for (const [ip, c, r, city] of spec52) {
    const got = triple(merged.get(ip));
    const t = truth52[ip];
    result.s52.push({
      ip,
      got: `${got.country}/${got.region}/${got.city}`,
      spec: `${c}/${r}/${city}`,
      spec_match: got.country === c && got.region === r && got.city === city,
      truth: `${t[0]}/${t[1]}/${t[2]}`,
      truth_match: got.country === t[0] && got.region === t[1] && got.city === t[2],
    });
  }

  // ---- §5.3 mainland coverage
  let mCity = 0, oCity = 0, mCN = 0, oCN = 0;
  const mainlandRows = [];
  for (const s of samples.mainland) {
    const m = triple(merged.get(s.ip));
    const o = triple(orig.get(s.ip));
    if (m.country === "CN") mCN++;
    if (o.country === "CN") oCN++;
    if (m.city) mCity++;
    if (o.city) oCity++;
    mainlandRows.push({ ip: s.ip, isp: s.isp, merged: key(m), orig: key(o) });
  }
  result.s53.mainland = {
    n: samples.mainland.length,
    merged_cn: mCN,
    orig_cn: oCN,
    merged_city_rate: +(mCity / samples.mainland.length).toFixed(3),
    orig_city_rate: +(oCity / samples.mainland.length).toFixed(3),
    target_ge_90pct: mCity / samples.mainland.length >= 0.9,
    rows: mainlandRows,
  };

  // ---- §5.3 overseas: merged must equal original exactly
  const diffs = [];
  const checkSet = (label, ips) => {
    let n = 0;
    for (const ip of ips) {
      n++;
      const m = triple(merged.get(ip));
      const o = triple(orig.get(ip));
      if (key(m) !== key(o)) {
        diffs.push({ set: label, ip, merged: key(m), orig: key(o) });
      }
    }
    return n;
  };
  const nNamed = checkSet("overseas_named", samples.overseas_named);
  const nSample = checkSet("overseas_sample", samples.overseas_sample);
  const nV6 = checkSet("ipv6_sample", samples.ipv6_sample);
  result.s53.overseas = {
    named_n: nNamed,
    sample_n: nSample,
    ipv6_n: nV6,
    total_differences: diffs.length,
    differences: diffs.slice(0, 50),
  };

  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({
    s51: { mb: result.s51.file_mb, size_ok: result.s51.size_ok_40_100mb,
           ip_version: result.s51.ip_version, type: result.s51.database_type },
    s52_spec_match: result.s52.filter(r => r.spec_match).length + "/" + result.s52.length,
    s52_truth_match: result.s52.filter(r => r.truth_match).length + "/" + result.s52.length,
    s53_mainland_city_rate: result.s53.mainland.merged_city_rate +
      " (orig " + result.s53.mainland.orig_city_rate + ")",
    s53_overseas_diffs: result.s53.overseas.total_differences,
  }, null, 2));
}

main().catch((e) => { console.error(e); process.exit(1); });
