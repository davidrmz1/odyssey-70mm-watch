#!/usr/bin/env python3
"""Watch Regal Irvine Spectrum for newly-released IMAX 70mm showtimes of The Odyssey.

Data source: Fandango's internal theater-showtimes JSON. The public site renders
showtimes client-side, and regmovies.com / imax.com both return 403 to non-browser
clients, so this endpoint is the only headless-readable source.

Alerts on EVENING showtimes only (start 17:00-21:30). Morning and afternoon shows
are tracked in state but never alerted on.

Modes:
    --mode frontier   near-term days + the far edge of the booking horizon (cheap)
    --mode full       every day in the next --days window (thorough)
    --baseline        record current state, alert on nothing

Notification is by email (see notify.py); --notify enables it.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

THEATER = "AABTB"  # Regal Irvine Spectrum
MOVIE_TITLE_MATCH = "odyssey"
FORMAT_70MM = "IMAX 70MM"

# Evenings only: start no earlier than 5:00pm, no later than 9:30pm.
LATEST_START = (21, 30)
EVENING_FROM = (17, 0)
AFTERNOON_FROM = (12, 0)

ENDPOINT = "https://www.fandango.com/napi/theaterMovieShowtimes/{theater}?startDate={date}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.fandango.com/",  # required; without it the API 403s
}

HERE = Path(__file__).parent
STATE_PATH = HERE / "state.json"
LASTRUN_PATH = HERE / "last_run.txt"  # gitignored; keeps state.json diff-free


def fetch_day(day):
    url = ENDPOINT.format(theater=THEATER, date=day.isoformat())
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_ticketing_date(raw):
    """'2026-08-07+19:15' -> (date, (hour, minute)). The '+HH:MM' is a
    time-of-day, not a UTC offset."""
    day_part, _, time_part = raw.partition("+")
    d = datetime.strptime(day_part, "%Y-%m-%d").date()
    hh, _, mm = time_part.partition(":")
    return d, (int(hh), int(mm))


def band(hm):
    if hm > LATEST_START:
        return "too_late"
    if hm >= EVENING_FROM:
        return "evening"
    if hm >= AFTERNOON_FROM:
        return "afternoon"
    return "morning"


def extract_70mm(payload):
    """Yield one dict per IMAX 70mm showtime found in a day's payload."""
    vm = payload.get("viewModel") or {}
    for movie in vm.get("movies") or []:
        if MOVIE_TITLE_MATCH not in (movie.get("title") or "").lower():
            continue
        for variant in movie.get("variants") or []:
            for group in variant.get("amenityGroups") or []:
                for st in group.get("showtimes") or []:
                    formats = {f.get("filterName") for f in st.get("filmFormat") or []}
                    if FORMAT_70MM not in formats:
                        continue
                    raw = st.get("ticketingDate")
                    if not raw:
                        continue
                    d, hm = parse_ticketing_date(raw)
                    yield {
                        "key": f"{d.isoformat()}T{hm[0]:02d}:{hm[1]:02d}",
                        "date": d.isoformat(),
                        "time": f"{hm[0]:02d}:{hm[1]:02d}",
                        "display": st.get("date"),
                        "band": band(hm),
                        "status": st.get("type"),  # 'available' = listed/on sale
                        "expired": bool(st.get("expired")),
                        "showtime_id": st.get("id"),
                        "url": st.get("ticketingJumpPageURL"),
                    }


def days_to_scan(mode, days, known_horizon):
    """Which dates to request this run.

    'full' walks the whole window. 'frontier' walks the next week (catches shows
    added to existing dates) plus the far edge of the horizon (catches a run
    extension), which is ~25 requests instead of ~60.
    """
    today = date.today()
    if mode == "full":
        return [today + timedelta(days=i) for i in range(days)]

    wanted = {today + timedelta(days=i) for i in range(7)}
    if known_horizon:
        edge = datetime.strptime(known_horizon, "%Y-%m-%d").date()
        wanted |= {edge + timedelta(days=i) for i in range(-1, 21)}
    else:
        wanted |= {today + timedelta(days=i) for i in range(days)}
    return sorted(d for d in wanted if d >= today)


def scan(dates, verbose=False):
    found = {}
    errors = []
    for day in dates:
        try:
            payload = fetch_day(day)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            errors.append((day.isoformat(), str(exc)))
            continue
        except json.JSONDecodeError as exc:
            errors.append((day.isoformat(), f"bad json: {exc}"))
            continue
        if payload.get("error"):
            errors.append((day.isoformat(), payload.get("errorMessage") or payload["error"]))
            continue
        for show in extract_70mm(payload):
            found[show["key"]] = show
        if verbose:
            print(f"  scanned {day}", file=sys.stderr)
        time.sleep(0.35)  # be polite to the endpoint
    return found, errors


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("frontier", "full"), default="full")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--notify", action="store_true", help="send email on a hit")
    ap.add_argument("--test-notify", action="store_true",
                    help="send a labelled test email and exit; scans nothing")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.test_notify:
        import notify
        ok, detail = notify.send_test()
        print(f"test notify: {'sent' if ok else 'FAILED'} - {detail}")
        return 0 if ok else 3

    stamp = datetime.now().isoformat(timespec="seconds")
    state = load_state()
    prev = state.get("shows", {})
    horizon = state.get("horizon")

    dates = days_to_scan(args.mode, args.days, horizon)
    shows, errors = scan(dates, verbose=args.verbose)

    # A frontier run only sees part of the calendar, so it must not conclude that
    # the unscanned days vanished. Merge onto the previous state instead.
    merged = dict(prev)
    merged.update(shows)

    new_keys = sorted(k for k in shows if k not in prev)
    reopened = sorted(
        k for k in shows
        if k in prev
        and prev[k].get("status") != "available"
        and shows[k].get("status") == "available"
    )

    hits = [
        merged[k] for k in new_keys + reopened
        if merged[k]["band"] == "evening" and not merged[k]["expired"]
    ]
    hits.sort(key=lambda s: (s["date"], s["time"]))

    dates_seen = sorted({s["date"] for s in merged.values()})
    new_horizon = dates_seen[-1] if dates_seen else None

    print(f"checked {stamp} mode={args.mode} requests={len(dates)}")
    print(f"70mm showtimes tracked: {len(merged)} across {len(dates_seen)} dates")
    if new_horizon:
        print(f"booking horizon: {dates_seen[0]} .. {new_horizon}")
    if errors:
        print(f"errors on {len(errors)} day(s): {errors[:3]}")
        # A total failure means the endpoint changed; don't overwrite good state.
        if len(errors) == len(dates):
            print("ALL REQUESTS FAILED - leaving state untouched")
            return 2

    changed = merged != prev or new_horizon != horizon
    if changed:
        STATE_PATH.write_text(
            json.dumps({"horizon": new_horizon, "shows": merged}, indent=2, sort_keys=True)
        )
    LASTRUN_PATH.write_text(f"{stamp} mode={args.mode} tracked={len(merged)}\n")

    if args.baseline:
        print("baseline saved; no alerting on this run")
        return 0

    if not hits:
        n = len(new_keys) + len(reopened)
        print(f"\nno new evening showtimes ({n} new/reopened outside the evening window)")
        return 0

    print("\n*** NEW IN-WINDOW 70MM SHOWTIMES ***")
    for s in hits:
        print(f"  {s['date']} {s['display']}  status={s['status']}")
        print(f"    {s['url']}")

    if args.notify:
        import notify
        ok, detail = notify.send(hits)
        print(f"notify: {'sent' if ok else 'FAILED'} - {detail}")
        if not ok:
            return 3
    return 10


if __name__ == "__main__":
    sys.exit(main())
