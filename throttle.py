#!/usr/bin/env python3
"""Circuit breaker for the seat sweep.

At the poll rates this project now runs, the real danger is not one refused
request -- it is continuing to hammer through a soft rate-limit until the block
becomes permanent. tickets.fandango.com already 403s datacenter IPs, and the
whole system depends on this residential IP staying accepted.

So: when a sweep comes back mostly 403/429, back off exponentially and skip
sweeps until the window expires. Any clean sweep resets it. State lives in
throttle.json (gitignored) so a restart does not forget an active backoff.

Backoff ladder, doubling from 5 minutes to a 2-hour cap. Two hours is the old
interval, so even fully tripped the watcher is no worse than it was before.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "throttle.json"

LADDER_MIN = [5, 10, 20, 40, 80, 120]
# Fraction of a sweep that must be refused before we treat it as a block rather
# than a handful of odd showtimes.
TRIP_RATIO = 0.5
MIN_SAMPLE = 4


def _load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(d):
    STATE.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")


def blocked_until():
    """Datetime we may resume, or None."""
    raw = _load().get("blocked_until")
    if not raw:
        return None
    try:
        until = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return until if until > datetime.now(timezone.utc) else None


def should_skip():
    until = blocked_until()
    if not until:
        return False, ""
    mins = (until - datetime.now(timezone.utc)).total_seconds() / 60
    return True, f"backing off after refusals; resuming in {mins:.0f} min"


def record(blocked_count, total):
    """Feed a sweep's outcome in. Returns (tripped_now, detail)."""
    d = _load()
    if total < MIN_SAMPLE or blocked_count / max(total, 1) < TRIP_RATIO:
        if d.get("strikes"):
            _save({"strikes": 0})
        return False, "ok"

    strikes = int(d.get("strikes", 0))
    wait = LADDER_MIN[min(strikes, len(LADDER_MIN) - 1)]
    until = datetime.now(timezone.utc) + timedelta(minutes=wait)
    _save({
        "strikes": strikes + 1,
        "blocked_until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_ratio": round(blocked_count / total, 2),
    })
    return True, (f"{blocked_count}/{total} refused; backing off {wait} min "
                  f"(strike {strikes + 1})")


def reset():
    if STATE.exists():
        _save({"strikes": 0})
