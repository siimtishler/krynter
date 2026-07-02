#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$PROJECT_ROOT/data/cadastre.gpkg"
OUTPUT="$PROJECT_ROOT/data/cadastre_vector_tiles"

if ! command -v ogr2ogr >/dev/null 2>&1; then
  echo "ogr2ogr is required. Install GDAL locally or run: make docker-vector-tiles" >&2
  exit 1
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "Cadastre source GeoPackage not found: $SOURCE" >&2
  exit 1
fi

if [[ -d "$OUTPUT" ]] && find "$OUTPUT" -type f -name '*.pbf' -print -quit | grep -q .; then
  echo "Cadastre vector tiles already exist: $OUTPUT"
  exit 0
fi

tmp_output="${OUTPUT}.tmp.$$"
rm -rf "$tmp_output"
trap 'rm -rf "$tmp_output"' EXIT

echo "Building cadastre vector tiles from data/cadastre.gpkg"

ogr2ogr \
  -f MVT "$tmp_output" "$SOURCE" \
  -nln tallinn_parcels \
  -dsco MINZOOM=10 \
  -dsco MAXZOOM=18 \
  -dsco SIMPLIFICATION=0 \
  -dsco SIMPLIFICATION_MAX_ZOOM=0

rm -rf "$OUTPUT"
mv "$tmp_output" "$OUTPUT"
trap - EXIT

echo "Cadastre vector tiles built: $OUTPUT"
