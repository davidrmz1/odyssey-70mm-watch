#!/usr/bin/env python3
"""Check actual seat availability for The Odyssey 70mm evening showtimes.

Fandango's showtime feed marks every listed show "available", which only means
"on sale". Real seat data lives behind the checkout API, reached like this:

  1. GET  the showtime's ticketing jump URL   -> lands on /mobileexpress/seatselection,
                                                 sets cookies, embeds showtimeId +
                                                 deviceSession.sessionId
  2. POST /token          with X-CSRF-Token   -> {"access_token": ...}
  3. GET  /checkoutapi/showtimes/v2/<id>/seat-map/
          with Authorization + X-FD-SessionId -> full seat map

The trailing slash on seat-map is REQUIRED; without it the gateway mangles the
last path segment and 404s.

Seat status: "A" = available, "R" = taken.

Reads showtimes from state.json (produced by odyssey_watch.py).
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar
from collections import defaultdict
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0 Safari/537.36")
HOST = "https://tickets.fandango.com"

# "Ideal middle" per the user: horizontally-centred block, middle-to-two-thirds
# back. CENTRE_FRAC is a fraction of total row width; DEPTH is front(0)..back(1).
CENTRE_FRAC = 0.20   # within +/-20% of width from centre => middle ~40% of the row
# Row D sits at ~30% depth. Rows E-L are centre-sold-out on every showtime checked
# on 2026-08-06, so a 0.40 floor reported "nothing ideal" everywhere and hid the one
# genuinely decent option. 0.28 includes row D and still excludes rows A-C.
DEPTH_MIN, DEPTH_MAX = 0.28, 0.80
SEATS_WANTED = 2

HERE = Path(__file__).parent
STATE_PATH = HERE / "state.json"
SEAT_STATE_PATH = HERE / "seat_state.json"
SEAT_HITS_PATH = HERE / "seat_hits.json"  # gitignored; workflow opens an issue from it


def new_session():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)), cj


def fetch_seat_map(jump_url, retries=2):
    """Walk the three-step flow. Returns the seat-map 'data' dict."""
    last = None
    for attempt in range(retries + 1):
        try:
            op, cj = new_session()
            r = op.open(urllib.request.Request(
                jump_url, headers={"User-Agent": UA,
                                   "Referer": "https://www.fandango.com/"}), timeout=30)
            final = r.geturl()
            html = r.read().decode("utf-8", "replace")

            m_sid = re.search(r'"showtimeId":"(\d+)"', html)
            m_sess = re.search(r'"sessionId":"([^"]+)"', html)
            if not (m_sid and m_sess):
                raise ValueError("showtimeId/sessionId not present (sold out or redirected?)")
            sid, sess = m_sid.group(1), m_sess.group(1)
            csrf = next((c.value for c in cj if c.name == "_csrf"), None)
            if not csrf:
                raise ValueError("no _csrf cookie")

            tok = json.load(op.open(urllib.request.Request(
                f"{HOST}/token", data=b"",
                headers={"User-Agent": UA, "Referer": final,
                         "X-CSRF-Token": csrf, "Accept": "application/json"},
                method="POST"), timeout=25))["access_token"]

            body = op.open(urllib.request.Request(
                f"{HOST}/checkoutapi/showtimes/v2/{sid}/seat-map/",  # trailing slash!
                headers={"User-Agent": UA, "Referer": final,
                         "Authorization": tok, "X-FD-SessionId": sess,
                         "Accept": "application/json"}), timeout=25).read()
            return json.loads(body)["data"]
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last


def analyse(data):
    """Find adjacent available seat runs, scored against the ideal-middle spec."""
    seats = data["seats"]
    xs = [s["x"] for s in seats]
    ys = [s["y"] for s in seats]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    cx, span = (xmin + xmax) / 2, (xmax - xmin) or 1
    ydepth = (ymax - ymin) or 1

    rows = defaultdict(list)
    for s in seats:
        rows[s["row"]].append(s)

    runs = []
    for r, rs in rows.items():
        rs = sorted(rs, key=lambda s: s["x"])
        for i in range(len(rs) - SEATS_WANTED + 1):
            grp = rs[i:i + SEATS_WANTED]
            if any(s["status"] != "A" or s["type"] != "standard" for s in grp):
                continue
            mid = sum(s["x"] for s in grp) / len(grp)
            off = abs(mid - cx) / span            # 0 = dead centre
            depth = (grp[0]["y"] - ymin) / ydepth  # 0 = front row
            ideal = off <= CENTRE_FRAC and DEPTH_MIN <= depth <= DEPTH_MAX
            runs.append({
                "seats": [s["id"] for s in grp],
                "row": grp[0]["id"][0],
                "centre_offset": round(off, 3),
                "depth": round(depth, 3),
                "ideal": ideal,
                # lower is better: distance from 60% deep, plus centre offset
                "score": round(abs(depth - 0.60) * 2 + off, 3),
            })
    runs.sort(key=lambda x: x["score"])
    # Deepest genuinely-centred pair, regardless of the depth floor. Reported so a
    # too-strict floor can never silently hide the best real option again.
    centred = [x for x in runs if x["centre_offset"] <= CENTRE_FRAC
               and x["depth"] <= DEPTH_MAX]
    centred.sort(key=lambda x: -x["depth"])
    return {
        "available": data.get("totalAvailableSeatCount"),
        "total": data.get("totalSeatCount"),
        "auditorium": data.get("auditoriumId"),
        "pairs_total": len(runs),
        "pairs_ideal": sum(1 for x in runs if x["ideal"]),
        "best": runs[:5],
        "best_centred": centred[0] if centred else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only check first N showtimes")
    ap.add_argument("--date", help="check a single date, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="dump machine-readable results")
    args = ap.parse_args()

    shows = json.loads(STATE_PATH.read_text())["shows"]
    evening = sorted(
        (s for s in shows.values() if s["band"] == "evening" and not s["expired"]),
        key=lambda s: (s["date"], s["time"]),
    )
    if args.date:
        evening = [s for s in evening if s["date"] == args.date]
    if args.limit:
        evening = evening[:args.limit]

    results, errors = [], []
    for s in evening:
        try:
            info = analyse(fetch_seat_map(s["url"]))
        except Exception as exc:
            errors.append((s["date"], f"{type(exc).__name__}: {exc}"))
            print(f"{s['date']} {s['display']:>7}  ERROR {type(exc).__name__}: {exc}")
            continue
        info.update(date=s["date"], display=s["display"], url=s["url"])
        results.append(info)
        flag = "  <-- IDEAL" if info["pairs_ideal"] else ""
        c = info["best_centred"]
        cs = (f"centre {'+'.join(c['seats'])} row {c['row']} depth {c['depth']:.0%}"
              if c else "no centred pair")
        print(f"{s['date']} {s['display']:>7}  {info['available']:>3}/{info['total']} free  "
              f"pairs {info['pairs_total']:>3} ideal {info['pairs_ideal']:>2}  {cs}{flag}")
        time.sleep(0.8)

    ideal = [r for r in results if r["pairs_ideal"]]

    # Alert only on showtimes that did NOT have a centre pair last run. Without
    # this the 2-hourly job would re-announce the same four showtimes forever.
    try:
        prev = json.loads(SEAT_STATE_PATH.read_text())
        prev_ideal = {r["date"] for r in prev.get("results", []) if r.get("pairs_ideal")}
    except (OSError, json.JSONDecodeError):
        prev, prev_ideal = {}, set()
    newly = [r for r in ideal if r["date"] not in prev_ideal]

    print(f"\nchecked {len(results)} showtimes, {len(errors)} error(s)")
    print(f"showtimes with an IDEAL centre pair: {len(ideal)} ({len(newly)} new)")
    for r in ideal:
        # Must report the centred pair, NOT best[0]: best[0] is score-ranked and an
        # edge seat at the right depth can outrank a dead-centre seat, which made
        # this summary print seats that were not ideal at all.
        b = r["best_centred"]
        if not b:
            continue
        print(f"  {r['date']} {r['display']}  {'+'.join(b['seats'])}  row {b['row']}"
              f"  depth {b['depth']:.0%}  offset {b['centre_offset']:.2f}")
        print(f"    {r['url']}")

    # Don't overwrite good state with a mostly-failed sweep, or every showtime
    # would look "new" again on the next run and re-alert.
    if results:
        # Merge, never replace: a --date or --limit run only sees part of the
        # calendar, and replacing would make every unchecked showtime look new
        # (and re-alert) on the following sweep.
        merged = {r["date"]: r for r in (prev.get("results", []) if isinstance(prev, dict) else [])}
        merged.update({r["date"]: r for r in results})
        SEAT_STATE_PATH.write_text(json.dumps(
            {"results": sorted(merged.values(), key=lambda r: r["date"]),
             "errors": errors}, indent=2, sort_keys=True))
    else:
        print("no showtimes checked successfully - leaving seat state untouched")
        if errors:
            # Must not exit 0: a sweep that checked nothing is a failure, and
            # reporting success made a fully-403'd run look green in Actions.
            print("ALL SEAT CHECKS FAILED (tickets.fandango.com blocks datacenter IPs)")
            return 2

    SEAT_HITS_PATH.write_text(json.dumps(newly, indent=2, sort_keys=True))
    if args.json:
        print(json.dumps(results, indent=2))
    return 10 if newly else 0


if __name__ == "__main__":
    sys.exit(main())
