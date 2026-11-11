// Command build_mmdb builds GeoLite2-City-CN.mmdb.
//
// It loads the official GeoLite2-City.mmdb as the baseline tree, then
// inserts the qqwry-derived mainland-China CIDRs from merged_cidrs.jsonl
// (produced by build/merge_qqwry.py) on top, so every non-CN and every IPv6
// network stays byte-identical to GeoLite2 while mainland IPv4 gains
// city-level coverage. An optional second file, merged_ipv6.jsonl
// (produced by build/merge_ipv6.py from GeoCN + qqwry.ipdb), adds an IPv6
// overlay with a stricter rule: a CIDR is inserted ONLY where the original
// GeoLite2 record has country CN (or nothing at all) and NO subdivision and
// NO city, so GeoLite2's existing IPv6 cities (e.g. HB/Xiaogan) are never
// overwritten. IPv6 fills are listed in conflicts.csv as
// ipv6_city_added / ipv6_province_added.
//
// While inserting, it also compares each CIDR against the ORIGINAL GeoLite2
// record at the CIDR's start and midpoint IPs and writes conflicts.csv for
// every segment where the merge disagrees with GeoLite2 (city differs, city
// removed by a province-only qqwry record, province differs, country
// differs). Segments where the merge only ADDS a missing city/province are
// the intended improvement and are counted, not listed (except IPv6 fills,
// which are listed for audit).
//
// Usage:
//   build_mmdb <GeoLite2-City.mmdb> <geolite_cn.json> <merged_cidrs.jsonl>
//              <out.mmdb> <conflicts.csv> <build_stats.json> [merged_ipv6.jsonl]
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math/big"
	"net"
	"net/netip"
	"os"
	"strings"
	"time"

	"github.com/maxmind/mmdbwriter"
	"github.com/maxmind/mmdbwriter/mmdbtype"
	maxminddb "github.com/oschwald/maxminddb-golang/v2"
)

// ---------------------------------------------------------------- inputs

type province struct {
	En       string `json:"en"`
	Zh       string `json:"zh"`
	Geoname  int    `json:"geoname_id"`
}

type geoliteJSON struct {
	Provinces map[string]province `json:"provinces"`
}

type mergedRow struct {
	CIDR      string  `json:"cidr"`
	Prov      string  `json:"prov"`
	CityZh    string  `json:"city_zh"`
	CityEn    string  `json:"city_en"`
	GeonameID int     `json:"geoname_id"`
	Lat       float64 `json:"lat"`
	Lon       float64 `json:"lon"`
	Radius    int     `json:"radius"`
	Source    string  `json:"source"`
}

// ---------------------------------------------------------------- original GeoLite2 record (for conflict checks)

type origRec struct {
	Country struct {
		ISOCode string `maxminddb:"iso_code"`
	} `maxminddb:"country"`
	Subdivisions []struct {
		ISOCode string `maxminddb:"iso_code"`
	} `maxminddb:"subdivisions"`
	City struct {
		Names map[string]string `maxminddb:"names"`
	} `maxminddb:"city"`
}

func normEn(s string) string {
	s = strings.ToLower(s)
	s = strings.ReplaceAll(s, "'", "")
	s = strings.ReplaceAll(s, " ", "")
	s = strings.ReplaceAll(s, ".", "")
	s = strings.ReplaceAll(s, "-", "")
	s = strings.TrimSuffix(s, "city")
	s = strings.TrimSuffix(s, "shi")
	return s
}

func main() {
	if len(os.Args) != 7 && len(os.Args) != 8 {
		fmt.Fprintf(os.Stderr, "usage: %s <GeoLite2-City.mmdb> <geolite_cn.json> <merged_cidrs.jsonl> <out.mmdb> <conflicts.csv> <build_stats.json> [merged_ipv6.jsonl]\n", os.Args[0])
		os.Exit(2)
	}
	geolitePath, geoliteJSONPath, mergedPath, outPath, conflictsPath, statsPath := os.Args[1], os.Args[2], os.Args[3], os.Args[4], os.Args[5], os.Args[6]
	ipv6Path := ""
	if len(os.Args) == 8 {
		ipv6Path = os.Args[7]
	}
	started := time.Now()

	// --- province metadata (ISO -> en/zh/geoname_id) from the extraction
	geoBytes, err := os.ReadFile(geoliteJSONPath)
	if err != nil {
		fatal(err)
	}
	var geo geoliteJSON
	if err := json.Unmarshal(geoBytes, &geo); err != nil {
		fatal(err)
	}

	// --- original reader for conflict checks
	orig, err := maxminddb.Open(geolitePath)
	if err != nil {
		fatal(err)
	}
	defer orig.Close()

	// --- load the GeoLite2 tree as the baseline
	fmt.Println("loading baseline tree from", geolitePath, "...")
	tree, err := mmdbwriter.Load(geolitePath, mmdbwriter.Options{
		DatabaseType: "GeoLite2-City-CN",
		Description: map[string]string{
			"en": "City database: GeoLite2-City baseline with mainland China city coverage merged from qqwry (pure IP database)",
		},
	})
	if err != nil {
		fatal(err)
	}
	fmt.Printf("baseline loaded in %s\n", time.Since(started).Round(time.Second))

	// --- stream the merged CIDRs, insert, and check conflicts
	f, err := os.Open(mergedPath)
	if err != nil {
		fatal(err)
	}
	defer f.Close()
	cf, err := os.Create(conflictsPath)
	if err != nil {
		fatal(err)
	}
	cw := bufio.NewWriter(cf)
	fmt.Fprintln(cw, "network,checked_ip,kind,qqwry_province,qqwry_city_en,geolite2_country,geolite2_province,geolite2_city_en")

	recordCache := map[string]mmdbtype.Map{}
	stats := map[string]int{}
	conflictKinds := map[string]int{}
	flush := func() {
		if err := cw.Flush(); err != nil {
			fatal(err)
		}
	}
	defer flush()

	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
	inserted := 0
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var row mergedRow
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			fatal(fmt.Errorf("merged_cidrs.jsonl: %w", err))
		}
		_, ipnet, err := net.ParseCIDR(row.CIDR)
		if err != nil {
			fatal(fmt.Errorf("bad cidr %q: %w", row.CIDR, err))
		}
		key := row.Prov + "|" + row.CityZh + "|" + row.CityEn
		rec, ok := recordCache[key]
		if !ok {
			rec = buildRecord(geo.Provinces[row.Prov], row)
			recordCache[key] = rec
		}
		if err := tree.Insert(ipnet, rec); err != nil {
			fatal(fmt.Errorf("insert %s: %w", row.CIDR, err))
		}
		inserted++
		stats["inserted_by_source:"+row.Source]++

		// conflict check at the CIDR's start IP, then its midpoint IP
		ips := []netip.Addr{cidrStart(ipnet), cidrMid(ipnet)}
		seenKinds := map[string]bool{}
		for _, ip := range ips {
			kind, gCountry, gProv, gCity := checkConflict(orig, ip, row)
			if kind == "" {
				continue
			}
			if kind == "city_added" || kind == "province_added" {
				// intended improvement: count once per CIDR per kind
				if !seenKinds[kind] {
					seenKinds[kind] = true
					stats[kind]++
				}
				continue
			}
			if !seenKinds[kind] {
				seenKinds[kind] = true
				conflictKinds[kind]++
				fmt.Fprintf(cw, "%s,%s,%s,%s,%s,%s,%s,%s\n",
					row.CIDR, ip.String(), kind, row.Prov, row.CityEn,
					gCountry, gProv, gCity)
			}
		}
		stats["cidrs_checked"]++
		if inserted%20000 == 0 {
			fmt.Printf("inserted %d CIDRs (%s)\n", inserted, time.Since(started).Round(time.Second))
		}
	}
	if err := scanner.Err(); err != nil {
		fatal(err)
	}
	fmt.Printf("inserted %d CIDRs in %s\n", inserted, time.Since(started).Round(time.Second))

	// --- IPv6 overlay (optional): insert ONLY where GeoLite2 has no
	// subdivision and no city (and country CN or nothing). This is the
	// fill-gaps-only rule: GeoLite2's existing IPv6 cities are never
	// overwritten, so the 2409:8a4c:... Xiaogan regression point survives.
	if ipv6Path != "" {
		v6f, err := os.Open(ipv6Path)
		if err != nil {
			fatal(err)
		}
		defer v6f.Close()
		v6scanner := bufio.NewScanner(v6f)
		v6scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
		v6inserted, v6skipped := 0, 0
		for v6scanner.Scan() {
			line := strings.TrimSpace(v6scanner.Text())
			if line == "" {
				continue
			}
			var row mergedRow
			if err := json.Unmarshal([]byte(line), &row); err != nil {
				fatal(fmt.Errorf("merged_ipv6.jsonl: %w", err))
			}
			_, ipnet, err := net.ParseCIDR(row.CIDR)
			if err != nil {
				fatal(fmt.Errorf("bad cidr %q: %w", row.CIDR, err))
			}
			if ipnet.IP.To4() != nil {
				fatal(fmt.Errorf("ipv6 file contains ipv4 cidr %q", row.CIDR))
			}
			// fill-gaps-only: check the ORIGINAL GeoLite2 record at five
			// points of the CIDR (start, 1/4, midpoint, 3/4, last): a
			// large overlay CIDR must not silently overwrite GeoLite2
			// data sitting in a sub-range.
			skip := false
			skipWhy := ""
			var gCountry, gProv, gCity string
			for _, ip := range cidrPoints(ipnet) {
				var rec origRec
				if err := orig.Lookup(ip).Decode(&rec); err != nil {
					continue
				}
				gCountry = rec.Country.ISOCode
				gProv, gCity = "", ""
				if len(rec.Subdivisions) > 0 {
					gProv = rec.Subdivisions[0].ISOCode
				}
				if rec.City.Names != nil {
					gCity = rec.City.Names["en"]
				}
				if gCountry != "" && gCountry != "CN" {
					skip, skipWhy = true, "ipv6_skipped_non_cn"
					break
				}
				if gProv != "" || gCity != "" {
					skip, skipWhy = true, "ipv6_skipped_geolite_has_data"
					break
				}
			}
			if skip {
				stats[skipWhy]++
				v6skipped++
				continue
			}
			key := row.Prov + "|" + row.CityZh + "|" + row.CityEn
			rec, ok := recordCache[key]
			if !ok {
				rec = buildRecord(geo.Provinces[row.Prov], row)
				recordCache[key] = rec
			}
			if err := tree.Insert(ipnet, rec); err != nil {
				fatal(fmt.Errorf("insert %s: %w", row.CIDR, err))
			}
			v6inserted++
			inserted++
			stats["inserted_by_source:"+row.Source]++
			// IPv6 fills are listed in conflicts.csv for audit (unlike
			// IPv4 additions, which are only counted).
			kind := "ipv6_province_added"
			if row.CityEn != "" {
				kind = "ipv6_city_added"
			}
			conflictKinds[kind]++
			fmt.Fprintf(cw, "%s,%s,%s,%s,%s,%s,%s,%s\n",
				row.CIDR, cidrStart(ipnet).String(), kind, row.Prov, row.CityEn,
				gCountry, gProv, gCity)
			if v6inserted%10000 == 0 {
				fmt.Printf("inserted %d IPv6 CIDRs (%s)\n", v6inserted, time.Since(started).Round(time.Second))
			}
		}
		if err := v6scanner.Err(); err != nil {
			fatal(err)
		}
		stats["ipv6_inserted"] = v6inserted
		stats["ipv6_skipped"] = v6skipped
		fmt.Printf("ipv6 overlay: inserted %d, skipped %d (fill-gaps-only)\n", v6inserted, v6skipped)
	}

	// All conflict rows (IPv4 + IPv6) are written now; only then close
	// the file. (Closing it before the IPv6 loop used to make the
	// deferred flush fail with "file already closed".)
	flush()
	if err := cf.Close(); err != nil {
		fatal(err)
	}

	// --- write the tree
	out, err := os.Create(outPath)
	if err != nil {
		fatal(err)
	}
	bw := bufio.NewWriter(out)
	n, err := tree.WriteTo(bw)
	if err != nil {
		fatal(err)
	}
	if err := bw.Flush(); err != nil {
		fatal(err)
	}
	if err := out.Close(); err != nil {
		fatal(err)
	}
	fmt.Printf("wrote %s (%d bytes) in %s\n", outPath, n, time.Since(started).Round(time.Second))

	// --- self-check: reopen and verify metadata + a few lookups
	checks := selfCheck(outPath)
	for _, c := range checks {
		fmt.Println("self-check:", c)
	}

	// --- stats
	meta := map[string]any{
		"database_type":     "GeoLite2-City-CN",
		"inserted_cidrs":    inserted,
		"distinct_records":  len(recordCache),
		"conflict_kinds":    conflictKinds,
		"added_counts":      map[string]int{"city_added": stats["city_added"], "province_added": stats["province_added"]},
		"inserted_by_source": filterStats(stats, "inserted_by_source:"),
		"build_seconds":     time.Since(started).Seconds(),
		"output_bytes":      n,
		"self_checks":       checks,
	}
	sb, _ := json.MarshalIndent(meta, "", "  ")
	if err := os.WriteFile(statsPath, append(sb, '\n'), 0o644); err != nil {
		fatal(err)
	}
	fmt.Println("build stats:", statsPath)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "build_mmdb:", err)
	os.Exit(1)
}

func filterStats(stats map[string]int, prefix string) map[string]int {
	out := map[string]int{}
	for k, v := range stats {
		if strings.HasPrefix(k, prefix) {
			out[strings.TrimPrefix(k, prefix)] = v
		}
	}
	return out
}

// buildRecord shapes one merged row exactly the way umami reads it:
// country.iso_code, subdivisions[0].iso_code (bare ISO, e.g. GD),
// city.names.en (English/pinyin only), location lat/lon/accuracy_radius.
func buildRecord(prov province, row mergedRow) mmdbtype.Map {
	country := mmdbtype.Map{
		"geoname_id": mmdbtype.Uint32(1814991),
		"iso_code":   mmdbtype.String("CN"),
		"names": mmdbtype.Map{
			"en":    mmdbtype.String("China"),
			"zh-CN": mmdbtype.String("中国"),
		},
	}
	subdiv := mmdbtype.Map{
		"iso_code":   mmdbtype.String(row.Prov),
		"geoname_id": mmdbtype.Uint32(prov.Geoname),
		"names": mmdbtype.Map{
			"en":    mmdbtype.String(prov.En),
			"zh-CN": mmdbtype.String(prov.Zh),
		},
	}
	rec := mmdbtype.Map{
		"continent": mmdbtype.Map{
			"code":       mmdbtype.String("AS"),
			"geoname_id": mmdbtype.Uint32(6255147),
			"names": mmdbtype.Map{
				"en":    mmdbtype.String("Asia"),
				"zh-CN": mmdbtype.String("亚洲"),
			},
		},
		"country":            country,
		"registered_country": country,
		"subdivisions":       mmdbtype.Slice{subdiv},
		"location": mmdbtype.Map{
			"latitude":        mmdbtype.Float64(row.Lat),
			"longitude":       mmdbtype.Float64(row.Lon),
			"accuracy_radius": mmdbtype.Uint16(row.Radius),
			"time_zone":       mmdbtype.String("Asia/Shanghai"),
		},
	}
	if row.CityEn != "" {
		city := mmdbtype.Map{
			"names": mmdbtype.Map{
				"en": mmdbtype.String(row.CityEn),
			},
		}
		if row.CityZh != "" {
			city["names"].(mmdbtype.Map)["zh-CN"] = mmdbtype.String(row.CityZh)
		}
		if row.GeonameID > 0 {
			city["geoname_id"] = mmdbtype.Uint32(row.GeonameID)
		}
		rec["city"] = city
	}
	return rec
}

func cidrStart(ipnet *net.IPNet) netip.Addr {
	return netip.MustParseAddr(ipnet.IP.String())
}

func cidrMid(ipnet *net.IPNet) netip.Addr {
	ip := ipnet.IP.To4()
	if ip == nil {
		// IPv6 midpoint: start + 2^(127-ones).
		ones, _ := ipnet.Mask.Size()
		if ones >= 128 {
			return cidrStart(ipnet)
		}
		b := ipnet.IP.To16()
		// add 1 << (127-ones) to the 128-bit address
		bit := uint(127 - ones)
		byteIdx := 15 - int(bit/8)
		bitIdx := bit % 8
		carry := uint16(1) << bitIdx
		for i := byteIdx; i >= 0 && carry > 0; i-- {
			sum := uint16(b[i]) + carry
			b[i] = byte(sum)
			carry = sum >> 8
		}
		addr, ok := netip.AddrFromSlice(b)
		if !ok {
			return cidrStart(ipnet)
		}
		return addr
	}
	ones, _ := ipnet.Mask.Size()
	if ones >= 32 {
		return cidrStart(ipnet)
	}
	start := binary.BigEndian.Uint32(ip)
	mid := start + (1 << (31 - uint(ones)))
	out := make(net.IP, 4)
	binary.BigEndian.PutUint32(out, mid)
	return netip.MustParseAddr(out.String())
}

// cidrPoints returns five probe addresses spread over an IPv6 CIDR
// (start, 1/4, midpoint, 3/4, last) for the fill-gaps-only check.
func cidrPoints(ipnet *net.IPNet) []netip.Addr {
	ones, bits := ipnet.Mask.Size()
	if bits != 128 {
		return []netip.Addr{cidrStart(ipnet), cidrMid(ipnet)}
	}
	size := new(big.Int).Lsh(big.NewInt(1), uint(128-ones))
	base := new(big.Int).SetBytes(ipnet.IP.To16())
	fracs := []*big.Int{
		new(big.Int),
		new(big.Int).Rsh(new(big.Int).Set(size), 2),
		new(big.Int).Rsh(new(big.Int).Set(size), 1),
		new(big.Int).Mul(new(big.Int).Rsh(new(big.Int).Set(size), 2), big.NewInt(3)),
		new(big.Int).Sub(new(big.Int).Set(size), big.NewInt(1)),
	}
	out := make([]netip.Addr, 0, len(fracs))
	for _, f := range fracs {
		v := new(big.Int).Add(base, f)
		b := v.Bytes()
		var arr [16]byte
		copy(arr[16-len(b):], b)
		addr, ok := netip.AddrFromSlice(arr[:])
		if !ok {
			continue
		}
		out = append(out, addr)
	}
	return out
}

// checkConflict compares the original GeoLite2 record at ip with the merged
// row. It returns "" when the merge agrees with (or only improves on)
// GeoLite2 in a way that is not a conflict; "city_added"/"province_added"
// are improvements and are counted by the caller, not listed.
func checkConflict(orig *maxminddb.Reader, ip netip.Addr, row mergedRow) (kind, gCountry, gProv, gCity string) {
	var rec origRec // zeroed: Decode leaves it untouched when not found
	if err := orig.Lookup(ip).Decode(&rec); err != nil {
		return "", "", "", ""
	}
	gCountry = rec.Country.ISOCode
	if len(rec.Subdivisions) > 0 {
		gProv = rec.Subdivisions[0].ISOCode
	}
	if rec.City.Names != nil {
		gCity = rec.City.Names["en"]
	}
	if gCountry == "" {
		// GeoLite2 had nothing here at all; the merge only adds data.
		if row.CityEn != "" {
			return "city_added", "", "", ""
		}
		return "province_added", "", "", ""
	}
	if gCountry != "CN" {
		return "country_differs", gCountry, gProv, gCity
	}
	if gProv != "" && gProv != row.Prov {
		return "province_differs", gCountry, gProv, gCity
	}
	if gCity != "" && row.CityEn == "" {
		return "city_removed", gCountry, gProv, gCity
	}
	if gCity != "" && row.CityEn != "" && normEn(gCity) != normEn(row.CityEn) {
		return "city_differs", gCountry, gProv, gCity
	}
	if gCity == "" && row.CityEn != "" {
		return "city_added", gCountry, gProv, gCity
	}
	if gProv == "" && row.Prov != "" {
		return "province_added", gCountry, gProv, gCity
	}
	return "", gCountry, gProv, gCity
}

func selfCheck(path string) []string {
	var out []string
	db, err := maxminddb.Open(path)
	if err != nil {
		return []string{"reopen failed: " + err.Error()}
	}
	defer db.Close()
	md := db.Metadata
	out = append(out, fmt.Sprintf("database_type=%s ip_version=%d node_count=%d build_epoch=%d",
		md.DatabaseType, md.IPVersion, md.NodeCount, md.BuildEpoch))
	// IPv4 lookups must work (IPv4 aliasing on) and return the merged values.
	type check struct {
		ip, wantProv, wantCity string
	}
	for _, c := range []check{
		{"111.4.16.80", "HB", "Wuhan"},
		{"183.216.98.122", "JX", "Nanchang"},
		{"223.5.5.5", "ZJ", "Hangzhou"},
		{"192.161.160.202", "CA", "Los Angeles"},
		{"8.8.8.8", "", ""},
		// IPv6 overlay: GeoCN fill (GeoLite2 had country only), the
		// Xiaogan regression point (must survive: fill-gaps-only skips
		// it), a both-sources-agree case, and a no-data case.
		{"2409:8a38:28:5a50:2cb3:d356:ea83:44c0", "JX", "Nanchang"},
		{"2409:8a4c:ecd:b00:1497:11ff:fec1:eedb", "HB", "Xiaogan"},
		{"2409:6e16:fac3:1ee3:d91e:ebc0:aa65:d878", "ZJ", "Hangzhou"},
		{"2409:1bc8:7d20:82fd:2726:bc3f:5111:b698", "", ""},
	} {
		var rec origRec
		addr := netip.MustParseAddr(c.ip)
		if err := db.Lookup(addr).Decode(&rec); err != nil {
			out = append(out, fmt.Sprintf("%s lookup error: %v", c.ip, err))
			continue
		}
		prov, city := "", ""
		if len(rec.Subdivisions) > 0 {
			prov = rec.Subdivisions[0].ISOCode
		}
		if rec.City.Names != nil {
			city = rec.City.Names["en"]
		}
		status := "OK"
		if prov != c.wantProv || city != c.wantCity {
			status = fmt.Sprintf("MISMATCH want %s/%s", c.wantProv, c.wantCity)
		}
		out = append(out, fmt.Sprintf("%s -> %s/%s %s", c.ip, rec.Country.ISOCode+"-"+prov, city, status))
	}
	// ::ffff: aliased IPv4 lookup must give the same merged result.
	var rec origRec
	aliased := netip.MustParseAddr("::ffff:111.4.16.80")
	if err := db.Lookup(aliased).Decode(&rec); err != nil {
		out = append(out, "::ffff:111.4.16.80 lookup error: "+err.Error())
	} else {
		city := ""
		if rec.City.Names != nil {
			city = rec.City.Names["en"]
		}
		out = append(out, fmt.Sprintf("::ffff:111.4.16.80 -> %s/%s", rec.Country.ISOCode, city))
	}
	return out
}
