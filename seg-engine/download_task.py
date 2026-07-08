#!/usr/bin/env python3
"""Download TotalSegmentator weights for a specific task (one-shot).

Called by the Swift plugin store when the user installs a segmentation task.
Only model weights are downloaded (from TotalSegmentator's official servers) —
no patient data leaves the machine. Progress is streamed on stdout.

Usage:
  python3 download_task.py --task heartchambers_highres
  python3 download_task.py --list        # print known task ids and exit
"""

from __future__ import annotations

import argparse
import sys

# Tasks exposed by the plugin store (id -> human label). Extend as needed.
KNOWN_TASKS = {
    "heartchambers_highres": "Cardiac chambers (RV/LV) — high resolution",
    "total": "Total body (all default structures)",
    "lung_vessels": "Lung vessels and airways",
}

# Subtasks gated behind a (free, academic) TotalSegmentator license number.
# Registered once via `totalseg_set_license -l <license>`.
LICENSE_REQUIRED_TASKS = {"heartchambers_highres", "lung_vessels"}


def log(msg: str) -> None:
    print(msg, flush=True)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Download TotalSegmentator task weights.")
    p.add_argument("--task", help="Task id (see --list)")
    p.add_argument("--list", action="store_true", help="List known task ids and exit")
    args = p.parse_args(argv)

    if args.list:
        for tid, label in KNOWN_TASKS.items():
            log(f"{tid}\t{label}")
        return 0

    if not args.task:
        log("ERROR: --task is required (or use --list)")
        return 2
    if args.task not in KNOWN_TASKS:
        log(f"ERROR: unknown task '{args.task}'. Known: {', '.join(KNOWN_TASKS)}")
        return 2

    import importlib.util
    import shutil
    import subprocess
    from pathlib import Path

    if importlib.util.find_spec("totalsegmentator") is None:
        log("ERROR: TotalSegmentator is not installed in this environment. "
            "Run: pip install -r requirements.txt")
        return 1

    # Use the official console script (stable across versions) rather than
    # importing internal modules, whose paths change between releases.
    exe = shutil.which("totalseg_download_weights")
    if exe is None:
        candidate = Path(sys.executable).with_name("totalseg_download_weights")
        exe = str(candidate) if candidate.exists() else None
    if exe is None:
        log("ERROR: 'totalseg_download_weights' console script not found next to "
            f"{sys.executable}. Is TotalSegmentator installed in this venv?")
        return 1

    log(f"Downloading weights for task '{args.task}'… (weights only; no patient data)")
    try:
        rc = subprocess.call([exe, "-t", args.task])
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {type(e).__name__}: {e}")
        return 1
    if rc != 0:
        log(f"ERROR: weight download exited with code {rc}")
        if args.task in LICENSE_REQUIRED_TASKS:
            log("")
            log(f"'{args.task}' is a license-protected TotalSegmentator model.")
            log("It is FREE for non-commercial / academic use, but needs a one-time")
            log("license number:")
            log("  1) Request one: https://backend.totalsegmentator.com/license-academic/")
            log("     (or the form linked from https://totalsegmentator.com)")
            log("  2) Register it:  totalseg_set_license -l aca_XXXXXXXXXXXX")
            log("  3) Re-run this download.")
        return rc
    log(f"Weights for '{args.task}' are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
