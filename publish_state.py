#!/usr/bin/env python3
"""Commit and push a state file after a scan, so results reach GitHub.

Usage:
    python publish_state.py --file seat_state.json --message "seats: sweep" \
                            --heartbeat seats
    python publish_state.py --file state.json --message "state: horizon update"

Both scans now run on this PC rather than in Actions -- seat maps because
tickets.fandango.com 403s datacenter IPs, and the date scan because GitHub
dropped ~83% of its scheduled runs (measured 2026-08-10: 40 runs in 55h against
~239 expected, worst gap 5.9h). Nothing in Actions commits these files anymore,
so the runner has to.

--heartbeat writes heartbeat_<source>.json with the current UTC time and commits
it alongside. That file is the liveness signal deadman.yml watches. It has to be
separate from the state file because a state file only changes when the data
changes, so "no recent commit" would not distinguish a dead PC from a quiet one.
Each source gets its own heartbeat file so two runners committing at the same
time touch different paths and cannot conflict.

Safe after every scan: exits quietly when nothing changed, commits only the
named paths so an unrelated dirty tree is never swept in, and rebases before
pushing because the scans run on independent schedules and race each other.

A failure here must never fail the scan -- the data is already on disk and the
next run retries. Callers ignore the exit code; it is for humans reading the log.
"""

import argparse
import json
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


def write_heartbeat(source, stamp):
    path = HERE / f"heartbeat_{source}.json"
    path.write_text(json.dumps({"source": source, "utc": stamp}, indent=2) + "\n")
    return path.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="state file to publish")
    ap.add_argument("--message", default="state: update", help="commit message prefix")
    ap.add_argument("--heartbeat", help="also stamp heartbeat_<source>.json")
    ap.add_argument("--min-interval", type=int, default=0, metavar="MIN",
                    help="skip publishing if the last publish was under MIN "
                         "minutes ago (keeps fast poll loops from flooding git)")
    args = ap.parse_args()

    if not (HERE / ".git").exists():
        return fail("not a git checkout; skipping")

    now = datetime.now(timezone.utc)

    # The heartbeat changes on every run by design, so at a 5-minute sweep it
    # would produce ~288 commits a day. Throttle publishing, not detection:
    # alerts dispatch straight to alert.yml and never wait on this.
    marker = HERE / f"last_publish_{args.heartbeat or Path(args.file).stem}.txt"
    if args.min_interval > 0 and marker.exists():
        try:
            last = datetime.strptime(marker.read_text().strip(), "%Y-%m-%dT%H:%M:%SZ") \
                           .replace(tzinfo=timezone.utc)
            age_min = (now - last).total_seconds() / 60
            if age_min < args.min_interval:
                print(f"publish: last publish {age_min:.0f} min ago "
                      f"(< {args.min_interval}); skipping")
                return 0
        except ValueError:
            pass  # unreadable marker: fall through and publish

    stamp = now.strftime("%Y-%m-%dT%H:%MZ")

    targets = []
    if (HERE / args.file).exists():
        if git("diff", "--quiet", "--", args.file).returncode != 0:
            targets.append(args.file)
    else:
        print(f"publish: {args.file} does not exist; skipping it")

    # The heartbeat always changes, so it always gets committed. That is the
    # point: it proves the runner ran, even on a sweep that changed nothing.
    if args.heartbeat:
        targets.append(write_heartbeat(args.heartbeat, stamp))

    if not targets:
        print(f"publish: {args.file} unchanged; nothing to push")
        return 0

    # Stage first: `git commit -- <path>` refuses a path git has never seen, so
    # a brand-new heartbeat file would never get its first commit.
    add = git("add", "--", *targets)
    if add.returncode != 0:
        return fail("git add failed", add)

    commit = git(
        "-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}",
        "commit", "-m", f"{args.message} {stamp}", "--", *targets,
    )
    if commit.returncode != 0:
        return fail("commit failed", commit)

    for attempt in range(1, ATTEMPTS + 1):
        pull = git("pull", "--rebase", "--autostash", "origin", BRANCH)
        if pull.returncode == 0:
            push = git("push", "origin", f"HEAD:{BRANCH}")
            if push.returncode == 0:
                marker.write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                print(f"publish: pushed {', '.join(targets)} ({stamp})")
                return 0
            last = push
        else:
            # A half-finished rebase would leave REBASE_HEAD and a dirty index,
            # breaking every later run. Always put the tree back.
            git("rebase", "--abort")
            last = pull
        if attempt < ATTEMPTS:
            time.sleep(5)

    # The commit stays local; the next run will carry it up.
    return fail(f"could not push after {ATTEMPTS} attempts (commit kept locally)", last)


if __name__ == "__main__":
    sys.exit(main())
