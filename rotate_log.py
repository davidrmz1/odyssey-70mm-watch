#!/usr/bin/env python3
"""Trim a log file that has grown past a size cap, keeping the newest lines.

The retired Mac runner did this; the Windows runners did not, so seat_check.log
and watch_dates.log grew without bound (~20 MB/year between them at the current
cadence). This is the same behaviour, shared by both.

Usage:
    python rotate_log.py seat_check.log [max_bytes] [keep_lines]
"""

import sys
from pathlib import Path

DEFAULT_MAX_BYTES = 1_000_000
DEFAULT_KEEP_LINES = 2000


def main(argv):
    if len(argv) < 2:
        print("usage: rotate_log.py <logfile> [max_bytes] [keep_lines]")
        return 1

    path = Path(argv[1])
    max_bytes = int(argv[2]) if len(argv) > 2 else DEFAULT_MAX_BYTES
    keep_lines = int(argv[3]) if len(argv) > 3 else DEFAULT_KEEP_LINES

    if not path.exists() or path.stat().st_size <= max_bytes:
        return 0

    try:
        # errors="replace": a log truncated mid-character must not crash the
        # rotation and take the whole run down with it.
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
        kept = lines[-keep_lines:]
        path.write_text(
            f"[log rotated; kept last {len(kept)} lines]\n" + "".join(kept),
            encoding="utf-8",
        )
        print(f"rotated {path.name}: kept last {len(kept)} lines")
    except OSError as exc:
        print(f"rotate_log: could not rotate {path.name}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
