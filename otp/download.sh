#!/usr/bin/env bash
# Downloads static inputs for the OTP graph into otp/ (the OTP base directory).
# Realtime feeds (GTFS-RT, GBFS) are NOT downloaded - OTP polls them, see router-config.json.
set -euo pipefail
cd "$(dirname "$0")"

# Kraków bounding box (lon_min,lat_min,lon_max,lat_max) with a small margin
BBOX="19.75,49.95,20.25,50.15"

echo "== OSM Małopolska (~200 MB)"
curl -fL --retry 3 -o malopolskie-latest.osm.pbf \
  https://download.geofabrik.de/europe/poland/malopolskie-latest.osm.pbf

if command -v osmium >/dev/null; then
  echo "== Cropping OSM to Kraków (faster build, less RAM)"
  osmium extract -b "$BBOX" malopolskie-latest.osm.pbf -o krakow.osm.pbf --overwrite
  rm malopolskie-latest.osm.pbf
else
  echo "!! osmium not found (apt install osmium-tool) - using the whole voivodeship"
  mv malopolskie-latest.osm.pbf krakow.osm.pbf
fi

echo "== GTFS KMK (ZTP server is slow - be patient)"
# The server sometimes drops the connection mid-transfer, so resume (-C -) and verify the archive.
for f in A T; do
  out="krk-$(echo $f | tr A-Z a-z).gtfs.zip"
  for attempt in 1 2 3 4 5; do
    curl -fL -C - --retry 5 --retry-delay 5 -o "$out" "https://gtfs.ztp.krakow.pl/GTFS_KRK_$f.zip" || true
    unzip -tq "$out" >/dev/null 2>&1 && break
    echo "!! $out incomplete, retrying ($attempt)"; sleep 5
  done
  unzip -tq "$out" >/dev/null || { echo "!! $out still broken - download it manually"; exit 1; }
done

echo "== Elevation: Copernicus DEM 30 m (4 tiles around Kraków)"
for t in N49_00_E019 N49_00_E020 N50_00_E019 N50_00_E020; do
  curl -fL --retry 3 -o "dem_${t}.tif" \
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_${t}_00_DEM/Copernicus_DSM_COG_10_${t}_00_DEM.tif"
done

echo "== Marking KMK trips as bikes allowed"
python3 patch_gtfs_bikes.py

ls -lh *.pbf *.zip *.tif
