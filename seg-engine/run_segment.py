#!/usr/bin/env python3
"""One-shot cardiac-chamber segmentation + RV/LV strain metric for a DICOM series.

Invoked by the Swift app as a transient subprocess (NOT a long-running server),
so no model stays resident between runs. All processing is local; the DICOM
series never leaves the machine.

Pipeline
--------
  DICOM series dir
    -> TotalSegmentator (task: heartchambers_highres) -> per-structure NIfTI masks
    -> RV / LV ventricle masks (+ reference geometry)
    -> rvlv.compute(...) -> RV/LV ratio, classification, recommendation
    -> binary DICOM SEG (referencing source SOP instances)  [unless --no-seg]
    -> <out>/metrics.json

Usage
-----
  python3 run_segment.py --series <DICOM dir> --out <dir> \
      [--task heartchambers_highres] [--method length|volume] [--threshold 1.0] [--no-seg]

Exit code 0 on success; non-zero on failure (message on stderr, and an
``error`` field written to metrics.json when possible).

Heavy dependencies (torch, TotalSegmentator, SimpleITK, highdicom, pydicom) are
imported lazily so that --help and argument validation work without them.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import rvlv

# TotalSegmentator heartchambers_highres output filenames (v2).
RV_LABELS = ("heart_ventricle_right",)
LV_LABELS = ("heart_ventricle_left",)


def log(msg: str) -> None:
    """Progress line on stdout (the Swift side streams and displays these)."""
    print(msg, flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cardiac RV/LV strain segmentation (one-shot).")
    p.add_argument("--series", required=True, help="Path to the source DICOM series directory")
    p.add_argument("--out", required=True, help="Output directory (created if missing)")
    p.add_argument("--task", default="heartchambers_highres", help="TotalSegmentator task")
    p.add_argument("--method", default="length", choices=["length", "volume"],
                   help="RV/LV ratio method (default: length / axial diameter)")
    p.add_argument("--threshold", type=float, default=rvlv.DEFAULT_THRESHOLD,
                   help="RV/LV ratio threshold for strain classification")
    p.add_argument("--no-seg", action="store_true",
                   help="Skip DICOM SEG export (compute metrics only — useful for validation)")
    p.add_argument("--fast", action="store_true", help="Pass --fast to TotalSegmentator")
    return p.parse_args(argv)


def run_totalsegmentator(series_dir: Path, seg_out: Path, task: str, fast: bool) -> None:
    """Run TotalSegmentator on the DICOM series, writing per-structure NIfTI to seg_out."""
    from totalsegmentator.python_api import totalsegmentator

    log(f"Running TotalSegmentator task={task} (fast={fast})…")
    totalsegmentator(
        input=str(series_dir),
        output=str(seg_out),
        task=task,
        fast=fast,
        ml=False,            # separate file per structure (not a multilabel image)
        quiet=True,
    )
    log("TotalSegmentator finished.")


def _load_axial_mask(nifti_path: Path):
    """Load a NIfTI mask reoriented to [z(axial), y, x] with spacing (sz, sy, sx) mm."""
    import nibabel as nib

    img = nib.as_closest_canonical(nib.load(str(nifti_path)))  # RAS: axes (R, A, S)
    data = (img.get_fdata() > 0.5).astype("uint8")
    zx, zy, zz = img.header.get_zooms()[:3]
    # RAS (x=R, y=A, z=S) -> [z=S(axial), y=A, x=R]
    data = data.transpose(2, 1, 0)
    spacing = (float(zz), float(zy), float(zx))
    return data, spacing


def _first_existing(seg_out: Path, labels: tuple[str, ...]) -> Path:
    for name in labels:
        candidate = seg_out / f"{name}.nii.gz"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"None of the expected masks {labels} were produced in {seg_out}. "
        "Check that the task segments cardiac ventricles."
    )


def export_dicom_seg(series_dir: Path, seg_out: Path, out_path: Path) -> str:
    """Export RV+LV as a binary DICOM SEG referencing the source instances.

    Uses SimpleITK to read the source series in a geometry consistent with the
    TotalSegmentator output, and highdicom to write a native binary SEG that the
    viewer's DICOMAnnotationObject reader can overlay.

    Returns the written path (str). Slice correspondence between the resampled
    masks and the source instances must be validated on a real cohort (Phase 1.5).
    """
    import numpy as np
    import SimpleITK as sitk
    import highdicom as hd
    import pydicom

    reader = sitk.ImageSeriesReader()
    dicom_files = reader.GetGDCMSeriesFileNames(str(series_dir))
    if not dicom_files:
        raise FileNotFoundError(f"No DICOM series found in {series_dir}")
    reader.SetFileNames(dicom_files)
    ref_image = reader.Execute()  # geometry reference; slices in file order

    source_datasets = [pydicom.dcmread(f) for f in dicom_files]

    def resample_mask_to_ref(nifti_path: Path) -> np.ndarray:
        mask = sitk.ReadImage(str(nifti_path))
        mask = sitk.Resample(
            mask, ref_image, sitk.Transform(), sitk.sitkNearestNeighbor, 0,
            mask.GetPixelID(),
        )
        # SimpleITK array is [z, y, x] matching the source slice order.
        return (sitk.GetArrayFromImage(mask) > 0).astype(np.uint8)

    rv = resample_mask_to_ref(_first_existing(seg_out, RV_LABELS))
    lv = resample_mask_to_ref(_first_existing(seg_out, LV_LABELS))

    # Stack as a 2-segment labelmap: segment 1 = RV, segment 2 = LV.
    seg_descriptions = [
        hd.seg.SegmentDescription(
            segment_number=1, segment_label="RV cavity",
            segmented_property_category=hd.sr.CodedConcept("T-D0050", "SRT", "Tissue"),
            segmented_property_type=hd.sr.CodedConcept("T-32602", "SRT", "Right ventricle"),
            algorithm_type=hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC,
            algorithm_identification=hd.AlgorithmIdentificationSequence(
                name="TotalSegmentator", version="2", family=hd.sr.CodedConcept(
                    "123456", "99LOCAL", "Deep learning segmentation")),
        ),
        hd.seg.SegmentDescription(
            segment_number=2, segment_label="LV cavity",
            segmented_property_category=hd.sr.CodedConcept("T-D0050", "SRT", "Tissue"),
            segmented_property_type=hd.sr.CodedConcept("T-32502", "SRT", "Left ventricle"),
            algorithm_type=hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC,
            algorithm_identification=hd.AlgorithmIdentificationSequence(
                name="TotalSegmentator", version="2", family=hd.sr.CodedConcept(
                    "123456", "99LOCAL", "Deep learning segmentation")),
        ),
    ]

    # highdicom expects pixel_array shape (frames, rows, cols) per segment via a
    # combined label image: 0=bg, 1=RV, 2=LV.
    label = np.zeros_like(rv, dtype=np.uint8)
    label[rv > 0] = 1
    label[lv > 0] = 2

    seg = hd.seg.Segmentation(
        source_images=source_datasets,
        pixel_array=label,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=seg_descriptions,
        series_instance_uid=hd.UID(),
        series_number=9901,
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer="ODV-PE",
        manufacturer_model_name="TotalSegmentator heartchambers_highres",
        software_versions="2",
        device_serial_number="ODV-PE-seg-engine",
    )
    seg.save_as(str(out_path))
    return str(out_path)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    series_dir = Path(args.series)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "metrics.json"

    def fail(message: str) -> int:
        log(f"ERROR: {message}")
        try:
            metrics_path.write_text(json.dumps({"error": message}, indent=2))
        except Exception:  # noqa: BLE001
            pass
        return 1

    if not series_dir.is_dir():
        return fail(f"Series directory not found: {series_dir}")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            seg_out = Path(tmp) / "seg"
            seg_out.mkdir(parents=True, exist_ok=True)

            run_totalsegmentator(series_dir, seg_out, args.task, args.fast)

            rv_mask, spacing = _load_axial_mask(_first_existing(seg_out, RV_LABELS))
            lv_mask, _ = _load_axial_mask(_first_existing(seg_out, LV_LABELS))

            log(f"Computing RV/LV ratio (method={args.method})…")
            result = rvlv.compute(rv_mask, lv_mask, spacing,
                                  method=args.method, threshold=args.threshold)

            payload = result.to_dict()
            payload["task"] = args.task
            payload["source_series_dir"] = str(series_dir)

            if not args.no_seg:
                seg_path = out_dir / "segmentation.dcm"
                log("Exporting binary DICOM SEG…")
                payload["seg_path"] = export_dicom_seg(series_dir, seg_out, seg_path)
            else:
                log("Skipping DICOM SEG export (--no-seg).")

            metrics_path.write_text(json.dumps(payload, indent=2))
            log(f"Wrote {metrics_path}")
            log(f"RESULT ratio={payload['rv_lv_ratio']} class={payload['classification']}")
        return 0
    except Exception as e:  # noqa: BLE001
        return fail(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
