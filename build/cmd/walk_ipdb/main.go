// walk_ipdb enumerates every record in an IPIP.net-format .ipdb file by
// walking its binary trie, and emits the IPv6 records as TSV.
//
// The .ipdb layout (from the format and the ipdb-go reader): 4-byte
// big-endian metadata length, JSON metadata (node_count, fields,
// languages), then the body: nodeCount nodes of 8 bytes each (two 4-byte
// big-endian child pointers), then data records (2-byte big-endian length
// + tab-separated fields). A child pointer < nodeCount is another node;
// >= nodeCount is a data pointer (offset = value - nodeCount into the
// data section). IPv6 search starts at node 0; the IPv4 subtree hangs
// under the ::ffff:0:0/96 prefix and is skipped here.
//
// Usage: walk_ipdb <file.ipdb> <out.tsv>
// Output TSV: prefix<TAB>country_name<TAB>region_name<TAB>city_name
//             <TAB>district_name<TAB>owner_domain<TAB>isp_domain
//             <TAB>country_code<TAB>continent_code
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net/netip"
	"os"
	"strings"
)

type metaData struct {
	Build     int64          `json:"build"`
	IPVersion uint16         `json:"ip_version"`
	Languages map[string]int `json:"languages"`
	NodeCount int            `json:"node_count"`
	TotalSize int            `json:"total_size"`
	Fields    []string       `json:"fields"`
}

type walker struct {
	body      []byte
	nodeCount int
	fields    []string
	langOff   int
}

func (w *walker) readNode(node, index int) int {
	off := node*8 + index*4
	return int(binary.BigEndian.Uint32(w.body[off : off+4]))
}

// resolve turns a data pointer (>= nodeCount) into its field values.
func (w *walker) resolve(node int) []string {
	resolved := node - w.nodeCount + w.nodeCount*8
	size := int(binary.BigEndian.Uint16(w.body[resolved : resolved+2]))
	payload := string(w.body[resolved+2 : resolved+2+size])
	parts := strings.Split(payload, "\t")
	if w.langOff+len(w.fields) > len(parts) {
		return nil
	}
	return parts[w.langOff : w.langOff+len(w.fields)]
}

type frame struct {
	node  int
	depth int
	hi    uint64
	lo    uint64
}

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintf(os.Stderr, "usage: %s <file.ipdb> <out.tsv>\n", os.Args[0])
		os.Exit(2)
	}
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "read:", err)
		os.Exit(1)
	}
	if len(raw) < 4 {
		fmt.Fprintln(os.Stderr, "file too small")
		os.Exit(1)
	}
	metaLen := int(binary.BigEndian.Uint32(raw[0:4]))
	var meta metaData
	if err := json.Unmarshal(raw[4:4+metaLen], &meta); err != nil {
		fmt.Fprintln(os.Stderr, "meta:", err)
		os.Exit(1)
	}
	off, ok := meta.Languages["CN"]
	if !ok {
		fmt.Fprintln(os.Stderr, "no CN language in ipdb")
		os.Exit(1)
	}
	w := &walker{body: raw[4+metaLen:], nodeCount: meta.NodeCount, fields: meta.Fields, langOff: off}
	fmt.Fprintf(os.Stderr, "ipdb build=%d node_count=%d fields=%v\n", meta.Build, meta.NodeCount, meta.Fields)

	out, err := os.Create(os.Args[2])
	if err != nil {
		fmt.Fprintln(os.Stderr, "create:", err)
		os.Exit(1)
	}
	defer out.Close()
	bw := bufio.NewWriter(out)
	defer bw.Flush()

	// Depth-first walk of the IPv6 trie. The IPv4 subtree root sits at
	// depth 96 with prefix ::ffff:0:0/96 (hi=0, lo=0x0000ffff00000000);
	// never descend into it.
	stack := []frame{{node: 0, depth: 0}}
	leaves, v4skipped, eqNodeCount := 0, 0, 0
	for len(stack) > 0 {
		fr := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		for bit := 0; bit <= 1; bit++ {
			child := w.readNode(fr.node, bit)
			hi, lo := fr.hi, fr.lo
			if fr.depth < 64 {
				if bit == 1 {
					hi |= 1 << (63 - uint(fr.depth))
				}
			} else {
				if bit == 1 {
					lo |= 1 << (127 - uint(fr.depth))
				}
			}
			nd := fr.depth + 1
			if nd == 96 && hi == 0 && lo == 0x0000ffff00000000 {
				v4skipped++
				continue
			}
			if child >= w.nodeCount {
				if child == w.nodeCount {
					eqNodeCount++
				}
				fields := w.resolve(child)
				if fields == nil {
					continue
				}
				var b [16]byte
				binary.BigEndian.PutUint64(b[0:8], hi)
				binary.BigEndian.PutUint64(b[8:16], lo)
				prefix := netip.PrefixFrom(netip.AddrFrom16(b), nd)
				fmt.Fprintf(bw, "%s\t%s\n", prefix.String(), strings.Join(fields, "\t"))
				leaves++
				continue
			}
			if nd >= 128 {
				fmt.Fprintf(os.Stderr, "node at depth 128, skipping\n")
				continue
			}
			stack = append(stack, frame{node: child, depth: nd, hi: hi, lo: lo})
		}
	}
	fmt.Printf("ipdb ipv6 leaves: %d (ipv4 subtree skipped: %d, child==nodeCount: %d)\n", leaves, v4skipped, eqNodeCount)
}
