#!/usr/bin/env bash
# One-click reproducible build of GeoLite2-City-CN.mmdb.
#
# What it does:
#   1. downloads the sources into data/ (reuses local copies when present and
#      verifies them against build/SOURCES.sha256)
#   2. extracts the GeoLite2 province/city tables (build/cmd/extract_geolite)
#   3. merges qqwry mainland records into CIDRs (build/merge_qqwry.py),
#      guarded by the APNIC delegated-allocation file
#   3b. merges the IPv6 overlay (GeoCN primary, qqwry.ipdb province
#      fallback) into CIDRs (build/merge_ipv6.py), RIR-guarded
#   4. builds the mmdb with GeoLite2 as baseline (build/cmd/build_mmdb);
#      the IPv6 overlay is fill-gaps-only and never overwrites GeoLite2
#   5. runs the §5.1/§5.2/§5.3 verification (needs node; skipped with a
#      warning when node is absent)
#   6. writes SHA256SUMS for the deliverables
#
# Requirements: Go >= 1.24 (tested with 1.25.4), Python 3.12 with pypinyin,
# curl, node >= 20 (verification only). The Go build loads the whole
# GeoLite2 tree into memory; allow ~2 GB free.
#
# Idempotent: re-running reuses downloaded sources (hash-checked) and
# rebuilds the outputs. Rebuilds differ from the shipped file only in
# build_epoch (the build timestamp inside the mmdb metadata).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GEOLITE_URL="https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-City.mmdb"
# qqwry.dat: metowolf's weekly re-build from the current CZ88 CZDB
# (the FW27623 mirror froze at 2024-09-25 when CZ88 discontinued .dat).
QQWRY_URL="https://github.com/metowolf/qqwry.dat/releases/latest/download/qqwry.dat"
# IPv6 overlay sources: GeoCN.mmdb (district-level codes, primary) and
# metowolf's qqwry.ipdb (same CZ88 data as qqwry.dat, IPv4+IPv6; the
# province fallback where GeoCN has no data).
IPDB_URL="https://cdn.jsdelivr.net/npm/qqwry.ipdb/qqwry.ipdb"
GEOCN_URL="https://github.com/ljxi/GeoCN/releases/download/v26.4.19/GeoCN.mmdb"
DBIP_URL="https://download.db-ip.com/free/dbip-city-lite-2026-11.csv.gz"
RIR_URL="https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"
SOURCES_SHA="build/SOURCES.sha256"

mkdir -p data work build

# --- download a source if missing; verify against the recorded hash when
# the file already exists locally (the P3TERX "latest" URL is rolling, so a
# fresh download on a new machine records its hash for the next run).
fetch() {
  local url="$1" dest="$2"
  if [ -f "$dest" ]; then
    if [ -f "$SOURCES_SHA" ] && grep -q "  $dest\$" "$SOURCES_SHA"; then
      (cd "$ROOT" && sha256sum -c --quiet <(grep "  $dest\$" "$SOURCES_SHA") \
        && echo "ok: $dest (hash matches $SOURCES_SHA)") \
        || { echo "ERROR: $dest does not match $SOURCES_SHA; delete it to re-download" >&2; exit 1; }
    else
      echo "ok: $dest (present, no recorded hash to check)"
    fi
    return 0
  fi
  echo "downloading $url -> $dest"
  curl -fsSL -o "$dest" "$url"
  if [ -f "$SOURCES_SHA" ]; then
    grep -v "  $dest\$" "$SOURCES_SHA" > "$SOURCES_SHA.tmp" || true
    mv "$SOURCES_SHA.tmp" "$SOURCES_SHA"
  fi
  (cd "$ROOT" && sha256sum "$dest" >> "$SOURCES_SHA")
  echo "recorded hash in $SOURCES_SHA"
}

fetch "$GEOLITE_URL" data/GeoLite2-City.mmdb
fetch "$QQWRY_URL" data/qqwry.dat
fetch "$DBIP_URL" data/dbip-city-lite.csv.gz
fetch "$RIR_URL" data/delegated-apnic-latest
fetch "$IPDB_URL" data/qqwry.ipdb
fetch "$GEOCN_URL" data/GeoCN.mmdb

# --- tool discovery: prefer the project's venv and a local Go install
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi
if ! command -v go >/dev/null 2>&1 && [ -x "$HOME/go/bin/go" ]; then
  export PATH="$HOME/go/bin:$PATH"
fi

# --- Python deps (merge script needs pypinyin only)
"$PY" -c "import pypinyin" 2>/dev/null || "$PY" -m pip install "pypinyin==0.55.0"

# --- Go tools (pinned in build/go.mod: mmdbwriter v1.2.0,
# maxminddb-golang/v2 v2.1.1)
export GOFLAGS=-mod=mod GOPROXY=https://proxy.golang.org,direct GOSUMDB=off
go -C build build -o extract_geolite ./cmd/extract_geolite/
go -C build build -o build_mmdb ./cmd/build_mmdb/
go -C build build -o extract_geocn ./cmd/extract_geocn/
go -C build build -o walk_ipdb ./cmd/walk_ipdb/

# --- step 1: GeoLite2 province/city tables
./build/extract_geolite data/GeoLite2-City.mmdb work/geolite_cn.json work/geolite_networks.csv

# --- step 2: qqwry -> merged CIDRs (RIR-guarded)
# DB-IP Lite coordinates are prepared once and cached in work/; rebuild them
# only when missing.
if [ ! -f work/dbip_cn_coords.json ]; then
  "$PY" build/dbip_coords.py data/dbip-city-lite.csv.gz work/dbip_cn_coords.json work/geolite_cn.json
fi
"$PY" build/merge_qqwry.py \
  data/qqwry.dat work/geolite_cn.json work/merged_cidrs.jsonl work/merge_stats.json \
  work/dbip_cn_coords.json data/delegated-apnic-latest

# --- step 2b: IPv6 overlay CIDRs (GeoCN primary, qqwry.ipdb fallback).
# The last argument is the operator-scope directory; "none" disables the
# BGP operator-list filter (measured: those lists cover only 9-29% of the
# big-three /16s, so as a hard filter they drop most real home-broadband
# space; the RIR guard is the scope control instead).
./build/extract_geocn data/GeoCN.mmdb work/geocn_v6.tsv
./build/walk_ipdb data/qqwry.ipdb work/ipdb_v6.tsv
"$PY" build/merge_ipv6.py \
  work/geocn_v6.tsv work/ipdb_v6.tsv work/geolite_cn.json \
  work/merged_ipv6.jsonl work/merge_ipv6_stats.json \
  work/dbip_cn_coords.json data/delegated-apnic-latest none

# --- step 3: build the mmdb (baseline load takes ~3 min, ~1.4 GB RAM)
GOMEMLIMIT=5GiB ./build/build_mmdb \
  data/GeoLite2-City.mmdb work/geolite_cn.json work/merged_cidrs.jsonl \
  GeoLite2-City-CN.mmdb conflicts.csv work/build_stats.json \
  work/merged_ipv6.jsonl

# --- step 4: verification (§5.1/§5.2/§5.3), needs node + the maxmind package
if command -v node >/dev/null 2>&1; then
  if [ ! -d work/node_verify/node_modules/maxmind ]; then
    (cd work/node_verify && npm install --no-audit --no-fund maxmind@5.0.8)
  fi
  "$PY" work/gen_verify_samples.py
  node work/node_verify/verify.js \
    GeoLite2-City-CN.mmdb data/GeoLite2-City.mmdb \
    work/verify_samples.json work/verify_results.json
else
  echo "WARNING: node not found; skipping verification (run it later with node work/node_verify/verify.js)" >&2
fi

# --- step 4b: IPv6 overlay verification (102 samples, needs maxminddb)
"$PY" work/ipv6_verify.py \
  GeoLite2-City-CN.mmdb data/GeoLite2-City.mmdb work/ipv6_verify_results.json

# --- step 5: checksums of the deliverables
sha256sum GeoLite2-City-CN.mmdb conflicts.csv README.md \
  build/build.sh build/merge_qqwry.py build/merge_ipv6.py \
  build/prefecture_cities.json build/division_cities.json \
  build/cmd/build_mmdb/main.go build/cmd/extract_geolite/main.go \
  build/cmd/extract_geocn/main.go build/cmd/walk_ipdb/main.go \
  > SHA256SUMS
echo
echo "done. deliverables: GeoLite2-City-CN.mmdb, conflicts.csv, README.md, SHA256SUMS"
