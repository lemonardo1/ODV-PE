# seg-engine — TotalSegmentator RV/LV strain (one-shot)

Transient (non-server) Python engine spawned by the Swift app to segment cardiac
chambers and compute the RV/LV strain metric for a DICOM series. All local; the
series never leaves the machine. Runs once per study and exits (no resident model).

## Files

| File | Role |
|------|------|
| `rvlv.py` | Pure-NumPy RV/LV metric + classification. No heavy deps → unit-tested. |
| `run_segment.py` | Orchestrator: TotalSegmentator → masks → `rvlv.compute` → binary DICOM SEG + `metrics.json`. |
| `download_task.py` | Downloads TotalSegmentator weights for one task (plugin-store install). |
| `requirements.txt` | Engine venv deps (torch + TotalSegmentator + DICOM/NIfTI I/O). |
| `tests/test_rvlv.py` | NumPy-only tests for `rvlv.py` (`python3 tests/test_rvlv.py`). |

## Run

```bash
# one-time, into the dedicated engine venv
pip install -r requirements.txt

# heartchambers_highres is license-gated (FREE for academic/non-commercial use).
# Without it you get `KeyError: 'license_number'` from TotalSegmentator.
#   1) request a license: https://backend.totalsegmentator.com/license-academic/
#      (or the form at https://totalsegmentator.com)
#   2) register once:
totalseg_set_license -l aca_XXXXXXXXXXXX
#   3) download the task weights:
python3 download_task.py --task heartchambers_highres

# per study
python3 run_segment.py \
  --series /path/to/dicom_series \
  --out    /path/to/output \
  --method length            # or: volume
  # --no-seg                 # metrics only (fast; use during accuracy validation)
```

Outputs `<out>/metrics.json` and (unless `--no-seg`) `<out>/segmentation.dcm`
(binary DICOM SEG referencing the source instances — the viewer overlays it).

`metrics.json` fields: `rv_lv_ratio`, `method`, `threshold`, `classification`,
`recommendation`, `rv_measure`/`lv_measure` (mm for length, mL for volume),
`reference_slice`, `disclaimer`, `task`, `seg_path`.

## RV/LV method

- **length** (default, guideline-aligned): maximal RV minor-axis diameter and the
  LV minor-axis diameter on the *same* axial slice (the RV-widest slice). Minor
  axis estimated via PCA of the chamber pixels — an automatic proxy for the manual
  endocardium-to-septum measurement.
- **volume**: RV cavity volume / LV cavity volume from voxel counts.

Default threshold `1.0` (axial RV/LV ≥ 1.0 ~ adverse outcome in acute PE); keep it
configurable and cite the source when fixing it for a study.

## ⚠️ Validation gate (plan Phase 1.5)

`rvlv.py` is unit-tested, but the **full pipeline is not yet validated on real
CTPA data**. Before study use, confirm on a PE cohort:
1. TotalSegmentator `heartchambers_highres` segments RV/LV correctly on
   pulmonary-arterial-phase contrast (train-time contrast differs).
2. The automatic RV/LV value agrees with manual measurement.
3. SEG slice correspondence is correct (mask ↔ source instance ordering).

Use `--no-seg` for the accuracy sweep (skips SEG export, only needs the ratio).
