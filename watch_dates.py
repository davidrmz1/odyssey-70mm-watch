#!/usr/bin/env python3
"""Run the showtime (new-dates) scan locally and alert via the bot.

Why this runs on the PC instead of Actions: the schedule was configured for
every 15 min, but GitHub delivered ~17% of it -- measured 2026-08-10, 40 runs in
55h against ~239 expected, worst gap 5.9h. Task Scheduler does not drop runs, so
the PC is now authoritative and watch.yml's cron is disabled.

Unlike the seat sweep this needs no residential IP; it moved purely for
reliability.

Alerting goes through notify_issue.create_issue(kind="dates"), which dispatches
alert.yml so github-actions[bot] opens the issue. An issue opened with this
machine's own credential would be authored by the recipient and notify nobody.

Exit codes mirror odyssey_watch.py: 0 nothing new, 10 hit alerted,
2 every request failed, 3 hit found but the alert could not be sent.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
HITS_PATH = HERE / "hits.json"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "frontier"
    if mode not in ("frontier", "full"):
        print(f"unknown mode {mode!r}; expected frontier or full")
        return 1

    # --notify is deliberately omitted: the SMTP secrets live in Actions, not
    # here, and email is a secondary channel. The bot-dispatched issue is the
    # real alert.
    scan = subprocess.run(
        [sys.executable, str(HERE / "odyssey_watch.py"), "--mode", mode, "--days", "60"],
        cwd=HERE, text=True,
    )
    code = scan.returncode
    print(f"--- odyssey_watch exit {code} ---")

    if code == 2:
        print("ALL DATE REQUESTS FAILED - endpoint may have changed; state untouched")
        return 2
    if code != 10:
        return code

    try:
        hits = json.loads(HITS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read hits.json: {exc}")
        return 3
    if not hits:
        return 0

    import notify_issue
    ok, detail = notify_issue.create_issue(hits, kind="dates")
    print(f"notify(dates): {'ok' if ok else 'FAILED'} - {detail}")
    # Found new showtimes but could not tell anyone - must not look clean.
    return 10 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
