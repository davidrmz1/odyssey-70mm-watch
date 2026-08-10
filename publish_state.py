#!/usr/bin/env python3
"""Commit and push a state file after a scan, so results reach GitHub.

Usage:
    python publish_state.py seat_state.json "seats: sweep"
    python publish_state.py state.json      "state: horizon update"

Both scans now run on this PC rather than in Actions -- seat maps because
tickets.fandango.com 403s datacenter IPs, and the date scan because GitHub
dropped ~83% of its scheduled runs (measured 2026-08-10: 40 runs in 55h against
~239 expected, worst gap 5.9h). Nothing in Actions commits these files anymore,
so the runner has to.

Safe after every scan: exits quietly when nothing changed, commits only the one
named file so an unrelated dirty tree is never swept in, and rebases before
pushing because the two scans run on independent schedules and race each other.

A failure here must never fail the scan -- the data is already on disk and the
next run retries. Callers ignore the exit code; it is for humans reading the log.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
BRANCH = "main"
# Distinct from odyssey-watch[bot] (the old Actions committer) so it is obvious
# in the log which machine produced a given commit.
AUTHOR_NAME = "odyssey-seats[pc]"
AUTHOR_EMAIL = "odyssey-seats@users.noreply.github.com"
ATTEMPTS = 3


def git(*args, timeout=120):
    env = dict(os.environ)
    # Never block a headless scheduled run on a credential dialog: fail fast and
    # let the next run retry instead of hanging until the task time limit.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GCM_INTERACTIVE", "never")
    return subprocess.run(
        ["git", *args], cwd=HERE, capture_output=True, text=True,
        timeout=timeout, env=env,
    )


def fail(msg, result=None):
    print(f"publish: {msg}")
    if result is not None:
        for stream in (result.stdout, result.stderr):
            if stream and stream.strip():
                print("  " + stream.strip().replace("\n", "\n  "))
    return 1


def main(argv):
    target = argv[1] if len(argv) > 1 else "seat_state.json"
    prefix = argv[2] if len(argv) > 2 else "state: update"

    if not (HERE / ".git").exists():
        return fail("not a git checkout; skipping")
    if not (HERE / target).exists():
        return fail(f"{target} does not exist; skipping")

    if git("diff", "--quiet", "--", target).returncode == 0:
        print(f"publish: {target} unchanged; nothing to push")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    commit = git(
        "-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}",
        "commit", "-m", f"{prefix} {stamp}", "--", target,
    )
    if commit.returncode != 0:
        return fail("commit failed", commit)

    for attempt in range(1, ATTEMPTS + 1):
        pull = git("pull", "--rebase", "--autostash", "origin", BRANCH)
        if pull.returncode == 0:
            push = git("push", "origin", f"HEAD:{BRANCH}")
            if push.returncode == 0:
                print(f"publish: pushed {target} ({stamp})")
                return 0
            last = push
        else:
            last = pull
        if attempt < ATTEMPTS:
            time.sleep(5)

    # The commit stays local; the next run will carry it up.
    return fail(f"could not push after {ATTEMPTS} attempts (commit kept locally)", last)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
