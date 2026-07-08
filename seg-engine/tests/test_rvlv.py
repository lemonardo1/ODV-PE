"""NumPy-only unit tests for rvlv.py. Run: python3 -m pytest, or python3 test_rvlv.py"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rvlv  # noqa: E402


def _box(shape, z, ys, xs):
    """Build a 3-D mask with a filled box on slice(s) z over the y/x ranges."""
    m = np.zeros(shape, dtype=np.uint8)
    m[z, ys[0]:ys[1], xs[0]:xs[1]] = 1
    return m


def test_volume_ratio_counts_voxels():
    spacing = (2.0, 1.0, 1.0)  # 2 mm^3 per voxel
    rv = np.zeros((4, 10, 10), np.uint8)
    lv = np.zeros((4, 10, 10), np.uint8)
    rv[1, 0:4, 0:5] = 1   # 20 voxels
    lv[1, 0:2, 0:5] = 1   # 10 voxels
    ratio, rv_ml, lv_ml = rvlv.rv_lv_volume_ratio(rv, lv, spacing)
    assert abs(ratio - 2.0) < 1e-9
    assert abs(rv_ml - 20 * 2.0 / 1000.0) < 1e-9
    assert abs(lv_ml - 10 * 2.0 / 1000.0) < 1e-9


def test_volume_ratio_empty_lv_raises():
    spacing = (1.0, 1.0, 1.0)
    rv = np.ones((2, 4, 4), np.uint8)
    lv = np.zeros((2, 4, 4), np.uint8)
    try:
        rvlv.rv_lv_volume_ratio(rv, lv, spacing)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_axial_minor_axis_diameter_of_rectangle():
    # A 20 (y) x 6 (x) rectangle at 1mm spacing: minor axis ~ 6 mm.
    spacing = (3.0, 1.0, 1.0)
    m = np.zeros((3, 40, 40), np.uint8)
    m[1, 10:30, 10:16] = 1  # 20 x 6
    diam = rvlv._minor_axis_diameter_mm(m[1], (spacing[1], spacing[2]))
    # PCA minor-axis extent of a 6-px-wide band ~ 5 mm (span of pixel centres).
    assert 4.0 <= diam <= 7.0


def test_axial_ratio_reference_slice_is_rv_max():
    spacing = (1.0, 1.0, 1.0)
    shape = (5, 40, 40)
    rv = np.zeros(shape, np.uint8)
    lv = np.zeros(shape, np.uint8)
    # RV widest on slice 3
    rv[2, 10:20, 10:30] = 1
    rv[3, 5:30, 10:34] = 1   # largest area
    # LV present on slice 3
    lv[3, 12:22, 12:20] = 1
    res = rvlv.compute(rv, lv, spacing, method="length")
    assert res.reference_slice == 3
    assert res.rv_measure > 0 and res.lv_measure > 0
    assert res.rv_lv_ratio > 1.0  # RV wider than LV here


def test_lv_fallback_when_absent_on_reference_slice():
    spacing = (1.0, 1.0, 1.0)
    shape = (5, 40, 40)
    rv = np.zeros(shape, np.uint8)
    lv = np.zeros(shape, np.uint8)
    rv[4, 5:35, 5:35] = 1     # RV max on slice 4
    lv[1, 10:20, 10:18] = 1   # LV only on slice 1
    res = rvlv.compute(rv, lv, spacing, method="length")
    assert res.reference_slice == 4
    assert res.lv_measure > 0  # fell back to LV's own slice


def test_classify_threshold():
    c, _ = rvlv.classify(1.2, threshold=1.0)
    assert c == "rv_strain_suggested"
    c, _ = rvlv.classify(0.8, threshold=1.0)
    assert c == "no_rv_strain_by_ct"
    # Boundary is inclusive.
    c, _ = rvlv.classify(1.0, threshold=1.0)
    assert c == "rv_strain_suggested"


def test_compute_volume_method_result_shape():
    spacing = (1.0, 1.0, 1.0)
    rv = np.ones((2, 4, 4), np.uint8)
    lv = np.ones((2, 4, 4), np.uint8)
    res = rvlv.compute(rv, lv, spacing, method="volume", threshold=1.0)
    d = res.to_dict()
    assert d["method"] == "volume"
    assert abs(d["rv_lv_ratio"] - 1.0) < 1e-9
    assert d["reference_slice"] is None
    assert "NOT a clinical diagnosis" in d["disclaimer"]


def test_unknown_method_raises():
    spacing = (1.0, 1.0, 1.0)
    m = np.ones((2, 4, 4), np.uint8)
    try:
        rvlv.compute(m, m, spacing, method="area")  # type: ignore[arg-type]
        assert False, "expected ValueError"
    except ValueError:
        pass


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
