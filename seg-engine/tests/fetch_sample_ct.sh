#!/bin/bash
# Fetch a public contrast thorax CT DICOM series for local end-to-end pipeline
# testing (no login). Source: TCIA NSCLC-Radiomics, subject LUNG1-001
# (CC BY-NC 3.0 — research/testing only, do NOT redistribute or commit).
#
# Usage:  ./fetch_sample_ct.sh [DEST_DIR]   (default: /tmp/ctpe_test/dicom)
#
# Then:   python3 run_segment.py --series <DEST_DIR> --out /tmp/pe --no-seg
set -euo pipefail

DEST="${1:-/tmp/ctpe_test/dicom}"
SERIES_UID="1.3.6.1.4.1.32722.99.99.298991776521342375010861296712563382046"
API="https://services.cancerimagingarchive.net/nbia-api/services/v1/getImage"

mkdir -p "$DEST"
TMP_ZIP="$(mktemp -t ctseries).zip"
echo "Downloading TCIA NSCLC-Radiomics LUNG1-001 (contrast thorax CT, 134 slices)…"
curl -fSL --max-time 300 "${API}?SeriesInstanceUID=${SERIES_UID}" -o "$TMP_ZIP"
unzip -oq "$TMP_ZIP" -d "$DEST"
rm -f "$TMP_ZIP"
echo "Extracted $(ls "$DEST"/*.dcm 2>/dev/null | wc -l | tr -d ' ') DICOM files to $DEST"
