#!/usr/bin/env python3
"""Commit and push seat_state.json after a sweep, so seat results reach GitHub.

seats.yml has a "Persist seat state" step that does this, but that workflow can
never actually sweep -- tickets.fandango.com 403s datacenter IPs, so the sweep
only runs on a residential machine. Without this, every sweep result stayed on
that one PC and GitHub only ever heard about a sweep on a hit.

Safe to run after every sweep: it exits quietly when nothing changed, commits
only seat_state.json (never whatever else is dirty in the tree), and rebases
before pushing because the watcher workflow commits state.json on its own
schedule and will often have moved main underneath us.

A failure here must never fail the sweep -- the seat data is already on disk and
the next run retries. The caller ignores the exit code; it is returned only for
humans reading the log.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
TARGET = "seat_state.json"
BRANCH = "main"
# Distinct from odyssey-watch[bot] (the Actions committer) so it is obvious in
# the log which machine produced a given commit.
AUTHOR_NAME = "odyssey-seats[pc]"
AUTHOR_EMAIL = "odyssey-seats@users.noreply.github.com"
ATTEMPTS = 3


def git(*args, timeout=120):
    env = dict(os.environ)
    # Never block a headless scheduled run on a credential dialog: fail fast and
    # let the next sweep retry instead of hanging until the task time limit.
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


def main():
    if not (HERE / ".git").exists():
        return fail("not a git checkout; skipping")

    if git("diff", "--quiet", "--", TARGET).returncode == 0:
        print("publish: seat state unchanged; nothing to push")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    commit = git(
        "-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}",
        "commit", "-m", f"seats: sweep {stamp}", "--", TARGET,
    )
    if commit.returncode != 0:
        return fail("commit failed", commit)

    for attempt in range(1, ATTEMPTS + 1):
        pull = git("pull", "--rebase", "--autostash", "origin", BRANCH)
        if pull.returncode == 0:
            push = git("push", "origin", f"HEAD:{BRANCH}")
            if push.returncode == 0:
                print(f"publish: pushed seat state ({stamp})")
                return 0
            last = push
        else:
            last = pull
        if attempt < ATTEMPTS:
            time.sleep(5)

    # The commit stays local; the next sweep will carry it up.
    return fail(f"could not push after {ATTEMPTS} attempts (commit kept locally)", last)


if __name__ == "__main__":
    sys.exit(main())
