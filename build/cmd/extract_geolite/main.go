// extract_geolite dumps GeoLite2-City reference data needed for the merge:
//  1. geolite_cn.json — per-province and per-city (zh -> en, geoname_id, lat/lon)
//     for mainland-China records only, keeping the most precise record per city.
//  2. geolite_networks.csv — every network with its umami triple
//     (country iso, subdivision iso, city en) for later diff verification.
//  3. prints summary stats to stdout.
package main

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/netip"
	"os"
	"sort"
	"strings"

	"github.com/oschwald/maxminddb-golang/v2"
)

type geoRecord struct {
	Country struct {
		ISOCode   string            `maxminddb:"iso_code"`
		GeonameID uint              `maxminddb:"geoname_id"`
		Names     map[string]string `maxminddb:"names"`
	} `maxminddb:"country"`
	Subdivisions []struct {
		ISOCode   string            `maxminddb:"iso_code"`
		GeonameID uint              `maxminddb:"geoname_id"`
		Names     map[string]string `maxminddb:"names"`
	} `maxminddb:"subdivisions"`
	City struct {
		GeonameID uint              `maxminddb:"geoname_id"`
		Names     map[string]string `maxminddb:"names"`
	} `maxminddb:"city"`
	Location struct {
		Latitude       float64 `maxminddb:"latitude"`
		Longitude      float64 `maxminddb:"longitude"`
		AccuracyRadius uint16  `maxminddb:"accuracy_radius"`
	} `maxminddb:"location"`
}

type cityInfo struct {
	En        string  `json:"en"`
	GeonameID uint    `json:"geoname_id"`
	Lat       float64 `json:"lat"`
	Lon       float64 `json:"lon"`
	Radius    uint16  `json:"radius"`
	Networks  int     `json:"networks"`
}

type provInfo struct {
	En        string `json:"en"`
	Zh        string `json:"zh"`
	GeonameID uint   `json:"geoname_id"`
}

type output struct {
	Provinces  map[string]provInfo            `json:"provinces"`
	Cities     map[string]cityInfo            `json:"cities"` // key: "<provISO>|<cityZhNormalized>"
	CitiesByEn map[string]cityInfo            `json:"cities_by_en"` // key: normalised en name
	Stats      map[string]int                `json:"stats"`
}

func normEn(s string) string {
	s = strings.ToLower(s)
	for _, r := range []string{"'", " ", ".", "-"} {
		s = strings.ReplaceAll(s, r, "")
	}
	s = strings.TrimSuffix(s, "city")
	s = strings.TrimSuffix(s, "shi")
	return s
}

func normCityZh(s string) string {
	s = strings.TrimSpace(s)
	s = strings.TrimSuffix(s, "市")
	s = strings.TrimSuffix(s, "县")
	s = strings.TrimSuffix(s, "区")
	return s
}

func main() {
	if len(os.Args) != 4 {
		fmt.Fprintf(os.Stderr, "usage: %s <GeoLite2-City.mmdb> <geolite_cn.json> <geolite_networks.csv>\n", os.Args[0])
		os.Exit(2)
	}
	dbPath, jsonPath, csvPath := os.Args[1], os.Args[2], os.Args[3]
	db, err := maxminddb.Open(dbPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer db.Close()

	out := output{Provinces: map[string]provInfo{}, Cities: map[string]cityInfo{}, CitiesByEn: map[string]cityInfo{}, Stats: map[string]int{}}
	cf, err := os.Create(csvPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer cf.Close()
	w := csv.NewWriter(cf)
	defer w.Flush()
	_ = w.Write([]string{"network", "country", "region", "city_en"})

	for res := range db.Networks(maxminddb.SkipEmptyValues()) {
		var rec geoRecord
		if err := res.Decode(&rec); err != nil {
			fmt.Fprintln(os.Stderr, "network decode:", err)
			os.Exit(1)
		}
		subnet := res.Prefix()
		out.Stats["networks_total"]++
		if subnet.Addr().Is6() {
			out.Stats["networks_v6"]++
		} else {
			out.Stats["networks_v4"]++
		}
		country := rec.Country.ISOCode
		region := ""
		if len(rec.Subdivisions) > 0 {
			region = rec.Subdivisions[0].ISOCode
		}
		cityEn := rec.City.Names["en"]
		_ = w.Write([]string{subnet.String(), country, region, cityEn})
		if country != "CN" {
			continue
		}
		out.Stats["networks_cn"]++
		if len(rec.Subdivisions) == 0 {
			out.Stats["cn_no_subdivision"]++
			continue
		}
		sub := rec.Subdivisions[0]
		provZh := sub.Names["zh-CN"]
		if _, ok := out.Provinces[sub.ISOCode]; !ok {
			out.Provinces[sub.ISOCode] = provInfo{En: sub.Names["en"], Zh: provZh, GeonameID: sub.GeonameID}
		}
		if cityEn == "" {
			out.Stats["cn_no_city"]++
			continue
		}
		// English-keyed map (also covers cities whose zh-CN name is missing
		// in GeoLite2, e.g. Taicang): keep the most precise record.
		enKey := normEn(cityEn)
		if enKey != "" {
			ecur, eok := out.CitiesByEn[enKey]
			if !eok || rec.Location.AccuracyRadius < ecur.Radius {
				out.CitiesByEn[enKey] = cityInfo{En: cityEn, GeonameID: rec.City.GeonameID, Lat: rec.Location.Latitude, Lon: rec.Location.Longitude, Radius: rec.Location.AccuracyRadius, Networks: ecur.Networks + 1}
			} else {
				ecur.Networks++
				out.CitiesByEn[enKey] = ecur
			}
		}
		cityZh := normCityZh(rec.City.Names["zh-CN"])
		if cityZh == "" {
			out.Stats["cn_city_no_zh"]++
			fmt.Fprintf(os.Stderr, "CN city without zh-CN: iso=%s en=%q geoname=%d lat=%v lon=%v\n", sub.ISOCode, cityEn, rec.City.GeonameID, rec.Location.Latitude, rec.Location.Longitude)
			continue
		}
		key := sub.ISOCode + "|" + cityZh
		cur, ok := out.Cities[key]
		if !ok || rec.Location.AccuracyRadius < cur.Radius || (rec.Location.AccuracyRadius == cur.Radius && cur.Lat == 0) {
			out.Cities[key] = cityInfo{En: cityEn, GeonameID: rec.City.GeonameID, Lat: rec.Location.Latitude, Lon: rec.Location.Longitude, Radius: rec.Location.AccuracyRadius, Networks: cur.Networks + 1}
		} else {
			cur.Networks++
			out.Cities[key] = cur
		}
	}
	out.Stats["cn_distinct_cities"] = len(out.Cities)
	out.Stats["cn_distinct_provinces"] = len(out.Provinces)
	jf, err := os.Create(jsonPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	enc := json.NewEncoder(jf)
	enc.SetIndent("", "  ")
	if err := enc.Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	jf.Close()
	keys := make([]string, 0, len(out.Stats))
	for k := range out.Stats {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		fmt.Printf("%s=%d\n", k, out.Stats[k])
	}
	_ = netip.Addr{}
}
