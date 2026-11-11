// extract_geocn dumps the IPv6 networks from GeoCN.mmdb that carry a
// division_code (GB/T 2260, 6 digits: PP + prefecture + county/district)
// and an ISP label. Only true IPv6 networks are emitted; the IPv4-mapped
// subtree (::ffff:0:0/96) is skipped because IPv4 stays qqwry's job.
//
// Usage: extract_geocn <GeoCN.mmdb> <out.tsv>
// Output TSV: prefix<TAB>division_code<TAB>isp<TAB>type
package main

import (
	"bufio"
	"fmt"
	"os"

	"github.com/oschwald/maxminddb-golang/v2"
)

type geocnRecord struct {
	DivisionCode int    `maxminddb:"division_code"`
	ISP          string `maxminddb:"isp"`
	Type         string `maxminddb:"type"`
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintf(os.Stderr, "usage: %s <GeoCN.mmdb> <out.tsv>\n", os.Args[0])
		os.Exit(2)
	}
	db, err := maxminddb.Open(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer db.Close()

	out, err := os.Create(os.Args[2])
	if err != nil {
		fmt.Fprintln(os.Stderr, "create:", err)
		os.Exit(1)
	}
	defer out.Close()
	w := bufio.NewWriter(out)
	defer w.Flush()

	v6, v4mapped, empty := 0, 0, 0
	for res := range db.Networks(maxminddb.SkipEmptyValues()) {
		prefix := res.Prefix()
		addr := prefix.Addr()
		if addr.Is4() || addr.Is4In6() {
			v4mapped++
			continue
		}
		var rec geocnRecord
		if err := res.Decode(&rec); err != nil {
			fmt.Fprintln(os.Stderr, "decode:", err)
			os.Exit(1)
		}
		if rec.DivisionCode == 0 {
			empty++
			continue
		}
		fmt.Fprintf(w, "%s\t%d\t%s\t%s\n", prefix.String(), rec.DivisionCode, rec.ISP, rec.Type)
		v6++
	}
	fmt.Printf("geocn ipv6 networks with division_code: %d (skipped ipv4-mapped: %d, empty: %d)\n", v6, v4mapped, empty)
}
