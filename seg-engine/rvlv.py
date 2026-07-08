"""RV/LV strain metrics from ventricle segmentation masks.

Pure-NumPy computation, deliberately kept free of torch / DICOM / TotalSegmentator
dependencies so it can be unit-tested in isolation (see tests/test_rvlv.py) and
reused by run_segment.py.

Conventions
-----------
- Masks are 3-D NumPy arrays indexed ``[z, y, x]`` (axial slices along axis 0),
  non-zero = chamber.
- ``spacing`` is ``(sz, sy, sx)`` in millimetres, matching the array axes.
- The right/left ventricle are passed as separate boolean masks.

Two ratio methods are provided:
- ``volume``: RV cavity volume / LV cavity volume (voxel counts x voxel volume).
- ``length`` (default, guideline-aligned): the maximal RV minor-axis diameter and
  the LV minor-axis diameter measured on the *same* axial slice — the slice where
  the RV is largest — mirroring the axial RV/LV diameter ratio used in CT PE
  reporting. The minor-axis diameter is estimated per slice via PCA of the
  foreground pixels (extent along the 2nd principal axis), which is a reproducible
  automatic proxy for the hand-drawn endocardium-to-septum measurement.

NOTE: the length method is an automated approximation of the clinical hand
measurement and must be validated against manual measurements on a PE/CTPA
cohort before study use (plan Phase 1.5).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

import numpy as np

Method = Literal["length", "volume"]

# Default axial RV/LV ratio threshold associated with adverse outcomes in acute PE.
# Kept configurable; cite the guideline/source used when setting it for a study.
DEFAULT_THRESHOLD = 1.0


@dataclass
class RVLVResult:
    rv_lv_ratio: float
    method: Method
    threshold: float
    classification: str
    recommendation: str
    # Supporting measurements (units documented per field)
    rv_measure: float          # mL (volume) or mm (length)
    lv_measure: float          # mL (volume) or mm (length)
    reference_slice: int | None  # axial index used for the length method
    disclaimer: str = (
        "Research/educational decision support only. NOT a clinical diagnosis. "
        "Automated RV/LV measurement must be reviewed by a qualified radiologist."
    )

    def to_dict(self) -> dict:
        return asdict(self)


def voxel_volume_mm3(spacing: tuple[float, float, float]) -> float:
    sz, sy, sx = spacing
    return float(sz) * float(sy) * float(sx)


def chamber_volume_ml(mask: np.ndarray, spacing: tuple[float, float, float]) -> float:
    """Chamber cavity volume in millilitres (cm^3)."""
    voxels = int(np.count_nonzero(mask))
    return voxels * voxel_volume_mm3(spacing) / 1000.0


def _minor_axis_diameter_mm(slice_mask: np.ndarray, spacing_yx: tuple[float, float]) -> float:
    """Estimate the minor-axis diameter (mm) of a 2-D chamber slice via PCA.

    Foreground pixel (y, x) coordinates are scaled to millimetres, centred, and
    projected onto their principal axes; the diameter is the extent along the
    second (minor) principal axis. Returns 0.0 for empty/degenerate slices.
    """
    ys, xs = np.nonzero(slice_mask)
    if ys.size < 2:
        return 0.0
    sy, sx = spacing_yx
    pts = np.column_stack((ys.astype(np.float64) * sy, xs.astype(np.float64) * sx))
    pts -= pts.mean(axis=0)
    # Covariance eigen-decomposition; eigvecs columns are principal axes.
    cov = np.cov(pts, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)  # ascending eigenvalues
    minor_axis = eigvecs[:, 0]              # smallest eigenvalue -> minor axis
    proj = pts @ minor_axis
    return float(proj.max() - proj.min())


def _axial_area(mask: np.ndarray) -> np.ndarray:
    """Per-axial-slice foreground pixel counts (axis 0 = z)."""
    return np.count_nonzero(mask, axis=(1, 2))


def rv_lv_volume_ratio(
    rv_mask: np.ndarray, lv_mask: np.ndarray, spacing: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Return (ratio, rv_ml, lv_ml). ratio is RV volume / LV volume."""
    rv_ml = chamber_volume_ml(rv_mask, spacing)
    lv_ml = chamber_volume_ml(lv_mask, spacing)
    if lv_ml <= 0.0:
        raise ValueError("LV volume is zero; cannot compute RV/LV volume ratio")
    return rv_ml / lv_ml, rv_ml, lv_ml


def rv_lv_axial_ratio(
    rv_mask: np.ndarray, lv_mask: np.ndarray, spacing: tuple[float, float, float]
) -> tuple[float, float, float, int]:
    """Guideline-aligned axial RV/LV diameter ratio.

    Returns (ratio, rv_diam_mm, lv_diam_mm, reference_slice_index).

    The reference slice is the axial slice where the RV cavity area is maximal;
    both ventricle minor-axis diameters are measured on that same slice. If the
    LV is absent on that slice, the LV diameter falls back to its own maximum.
    """
    if not np.any(rv_mask):
        raise ValueError("RV mask is empty; cannot compute axial RV/LV ratio")
    if not np.any(lv_mask):
        raise ValueError("LV mask is empty; cannot compute axial RV/LV ratio")

    spacing_yx = (spacing[1], spacing[2])
    ref = int(np.argmax(_axial_area(rv_mask)))

    rv_diam = _minor_axis_diameter_mm(rv_mask[ref], spacing_yx)
    lv_diam = _minor_axis_diameter_mm(lv_mask[ref], spacing_yx)

    if lv_diam <= 0.0:
        # LV not present on the RV-reference slice: use the LV's own widest slice.
        lv_ref = int(np.argmax(_axial_area(lv_mask)))
        lv_diam = _minor_axis_diameter_mm(lv_mask[lv_ref], spacing_yx)

    if lv_diam <= 0.0:
        raise ValueError("LV diameter is zero; cannot compute axial RV/LV ratio")

    return rv_diam / lv_diam, rv_diam, lv_diam, ref


def classify(ratio: float, threshold: float = DEFAULT_THRESHOLD) -> tuple[str, str]:
    """Rule-based classification + guideline-framed recommendation."""
    if ratio >= threshold:
        return (
            "rv_strain_suggested",
            f"RV/LV ratio {ratio:.2f} >= {threshold:.2f}: CT signs of right ventricular "
            "strain. Consider risk stratification (e.g. biomarkers, echocardiography) "
            "per institutional acute-PE pathway. Confirm measurement on the source images.",
        )
    return (
        "no_rv_strain_by_ct",
        f"RV/LV ratio {ratio:.2f} < {threshold:.2f}: no CT ratio evidence of right "
        "ventricular strain. Interpret alongside the full clinical picture.",
    )


def compute(
    rv_mask: np.ndarray,
    lv_mask: np.ndarray,
    spacing: tuple[float, float, float],
    method: Method = "length",
    threshold: float = DEFAULT_THRESHOLD,
) -> RVLVResult:
    """Compute the RV/LV metric and classification for the given masks."""
    if method == "volume":
        ratio, rv_measure, lv_measure = rv_lv_volume_ratio(rv_mask, lv_mask, spacing)
        ref_slice = None
    elif method == "length":
        ratio, rv_measure, lv_measure, ref_slice = rv_lv_axial_ratio(rv_mask, lv_mask, spacing)
    else:
        raise ValueError(f"Unknown method: {method!r} (expected 'length' or 'volume')")

    classification, recommendation = classify(ratio, threshold)
    return RVLVResult(
        rv_lv_ratio=round(ratio, 4),
        method=method,
        threshold=threshold,
        classification=classification,
        recommendation=recommendation,
        rv_measure=round(rv_measure, 3),
        lv_measure=round(lv_measure, 3),
        reference_slice=ref_slice,
    )
