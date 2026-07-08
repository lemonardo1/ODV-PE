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

    try:
        # TotalSegmentator ships a downloader that fetches only the weights for a task.
        from totalsegmentator.download_pretrained_weights import (
            download_pretrained_weights as _download,
        )
        from totalsegmentator.map_to_binary import class_map_5_parts  # noqa: F401

        log(f"Downloading weights for task '{args.task}'…")
        # The CLI 'totalseg_download_weights -t <task>' wraps this; call it directly.
        from totalsegmentator.config import setup_totalseg  # noqa: F401
        import subprocess

        # Prefer the official CLI entry point for correct task->weight mapping.
        rc = subprocess.call(
            [sys.executable, "-m", "totalsegmentator.bin.totalseg_download_weights",
             "-t", args.task]
        )
        if rc != 0:
            log(f"ERROR: weight download exited with code {rc}")
            return rc
        log(f"Weights for '{args.task}' are ready.")
        return 0
    except ImportError as e:
        log(f"ERROR: TotalSegmentator not installed in this environment: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
