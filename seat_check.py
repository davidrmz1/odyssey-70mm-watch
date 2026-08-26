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
import urllib.parse
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

# A showtime gaining this many seats in one sweep is treated as a release worth
# waking someone for, separately from whether the freed seats are centred.
# Measured over 17 sweeps on 2026-08-10/11: availability rose 16 times, fell 69,
# and was unchanged 515 times -- and every single rise was +1 or +2, i.e. one
# person cancelling. Alerting on those would mean ~16 notifications a day, none
# of which produced a centred pair. 4 skips the singles and catches a real block
# of seats going back on sale.
RELEASE_MIN = 4

# Pause between showtimes. Was 0.8s when a sweep ran every 2 hours; with session
# reuse each showtime is now a single request, and sweeps run every 5 minutes,
# so this stays deliberately non-zero -- a burst of 37 back-to-back requests is
# exactly the shape that gets an IP rate-limited.
REQUEST_GAP = 0.4

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

            if "queue-it.net" in final:
                raise Queued(queue_name(final))

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


class Blocked(Exception):
    """Fandango refused us (403/429) rather than the showtime being unavailable."""


def queue_name(url):
    """Label for a Queue-it waiting room, read off its own query string."""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return (q.get("man") or q.get("e") or ["unnamed"])[0]
    except Exception:
        return "unnamed"


class Queued(Exception):
    """Fandango has a Queue-it waiting room in front of ticketing.

    Categorically different from Blocked. Nothing is wrong with this machine, the
    code, or the showtime: Fandango gates tickets.fandango.com behind a virtual
    queue during a big presale, so the jump page redirects to queue-it.net and
    never reaches /mobileexpress/seatselection. showtimeId and sessionId are
    simply absent, which used to surface as the misleading
    "sold out or redirected?" ValueError on all 31 showtimes at once.

    First seen 2026-08-21. Config name was
    "PROD- Dune Part Three (2026) - Fandango DD - Catch All"
    -- a catch-all for another film's presale, not specific to The Odyssey.

    We do not try to get past it, and that is deliberate. The queue is traffic
    control the site owner put there on purpose; working around it is the same
    class of mistake as routing around a 403, and it risks the household's
    ability to buy tickets at all. So the sweep aborts on the first sighting
    instead of sending ~90 pointless requests every five minutes, and resumes by
    itself once Fandango lifts the queue.
    """


class SeatSession:
    """One checkout session reused across many showtimes.

    fetch_seat_map() below builds a fresh session per showtime -- jump page,
    /token, seat-map -- which is 3 requests each. state.json already carries
    showtime_id, and a single token + X-FD-SessionId is accepted for showtimes
    other than the one whose page created it (verified 2026-08-11, 4/4). So a
    sweep costs 2 setup requests plus 1 per showtime instead of 3 per showtime:
    111 -> 39 for a 37-showtime sweep. That is what makes short poll intervals
    affordable without tripling the request rate.
    """

    def __init__(self):
        self.opener = self.token = self.sess = self.referer = None

    def establish(self, jump_url):
        op, cj = new_session()
        r = op.open(urllib.request.Request(
            jump_url, headers={"User-Agent": UA,
                               "Referer": "https://www.fandango.com/"}), timeout=30)
        final = r.geturl()
        html = r.read().decode("utf-8", "replace")

        if "queue-it.net" in final:
            raise Queued(queue_name(final))

        m_sid = re.search(r'"showtimeId":"(\d+)"', html)
        m_sess = re.search(r'"sessionId":"([^"]+)"', html)
        if not (m_sid and m_sess):
            raise ValueError("showtimeId/sessionId not present (sold out or redirected?)")
        csrf = next((c.value for c in cj if c.name == "_csrf"), None)
        if not csrf:
            raise ValueError("no _csrf cookie")

        self.token = json.load(op.open(urllib.request.Request(
            f"{HOST}/token", data=b"",
            headers={"User-Agent": UA, "Referer": final,
                     "X-CSRF-Token": csrf, "Accept": "application/json"},
            method="POST"), timeout=25))["access_token"]
        self.opener, self.sess, self.referer = op, m_sess.group(1), final
        return m_sid.group(1)

    def seat_map(self, showtime_id):
        if not self.opener:
            raise ValueError("session not established")
        try:
            body = self.opener.open(urllib.request.Request(
                f"{HOST}/checkoutapi/showtimes/v2/{showtime_id}/seat-map/",
                headers={"User-Agent": UA, "Referer": self.referer,
                         "Authorization": self.token, "X-FD-SessionId": self.sess,
                         "Accept": "application/json"}), timeout=25).read()
        except urllib.error.HTTPError as exc:
            # 403/429 is Fandango pushing back on us, which is categorically
            # different from a sold-out or expired showtime. The caller counts
            # these to decide whether to stop hammering.
            if exc.code in (403, 429):
                raise Blocked(f"HTTP {exc.code}") from exc
            raise
        return json.loads(body)["data"]


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
    ap.add_argument("--notify-issue", action="store_true",
                    help="open an assigned GitHub issue when centre seats appear")
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

    import throttle
    skip, why = throttle.should_skip()
    if skip:
        print(f"SKIPPING SWEEP: {why}")
        return 0

    results, errors = [], []
    blocked_count = 0
    queued = None
    session = SeatSession()

    for s in evening:
        try:
            sid = str(s.get("showtime_id") or "")
            if session.opener and sid:
                # Cheap path: one request, reusing the established session.
                data = session.seat_map(sid)
            else:
                # First showtime, or one with no stored id: full 3-step, which
                # also establishes the session the rest of the sweep reuses.
                sid_from_page = session.establish(s["url"])
                data = session.seat_map(sid or sid_from_page)
            info = analyse(data)
        except Queued as exc:
            # Every remaining showtime would hit the same queue. Stop now.
            queued = str(exc)
            print(f"{s['date']} {s['display']:>7}  QUEUED  {exc}")
            break
        except Blocked as exc:
            blocked_count += 1
            errors.append((s["date"], f"Blocked: {exc}"))
            print(f"{s['date']} {s['display']:>7}  REFUSED {exc}")
            continue
        except Exception as exc:
            errors.append((s["date"], f"{type(exc).__name__}: {exc}"))
            print(f"{s['date']} {s['display']:>7}  ERROR {type(exc).__name__}: {exc}")
            # A dead session would fail every remaining showtime; drop it so the
            # next iteration rebuilds one.
            if session.opener and not isinstance(exc, ValueError):
                session = SeatSession()
            continue
        info.update(date=s["date"], display=s["display"], url=s["url"])
        results.append(info)
        flag = "  <-- IDEAL" if info["pairs_ideal"] else ""
        c = info["best_centred"]
        cs = (f"centre {'+'.join(c['seats'])} row {c['row']} depth {c['depth']:.0%}"
              if c else "no centred pair")
        print(f"{s['date']} {s['display']:>7}  {info['available']:>3}/{info['total']} free  "
              f"pairs {info['pairs_total']:>3} ideal {info['pairs_ideal']:>2}  {cs}{flag}")
        time.sleep(REQUEST_GAP)

    if queued:
        print(f"\nSWEEP ABORTED: Fandango has a Queue-it waiting room in front of "
              f"ticketing ({queued}).")
        print("  This is NOT an IP block and NOT sold out. The jump page redirects to\n"
              "  queue-it.net, so showtimeId/sessionId never appear in the HTML.")
        print("  Nothing to fix on this end; it resumes by itself once Fandango\n"
              "  lifts the queue. Seat state left untouched.")

    tripped, detail = throttle.record(blocked_count, len(evening))
    if tripped:
        print(f"THROTTLE: {detail}")

    ideal = [r for r in results if r["pairs_ideal"]]

    # Alert only on showtimes that did NOT have a centre pair last run. Without
    # this the 2-hourly job would re-announce the same four showtimes forever.
    try:
        prev = json.loads(SEAT_STATE_PATH.read_text())
        prev_ideal = {r["date"] for r in prev.get("results", []) if r.get("pairs_ideal")}
    except (OSError, json.JSONDecodeError):
        prev, prev_ideal = {}, set()
    newly = [r for r in ideal if r["date"] not in prev_ideal]

    # Seats going back on sale, regardless of where they are in the room. This
    # is a separate question from "is there an ideal pair" and must not touch
    # DEPTH_MIN. Compared against the immediately previous sweep, so a one-off
    # jump alerts once and then goes quiet by itself.
    prev_results = prev.get("results", []) if isinstance(prev, dict) else []
    prev_avail = {r["date"]: r["available"] for r in prev_results
                  if isinstance(r.get("available"), int)}
    releases = []
    for r in results:
        before = prev_avail.get(r["date"])
        if before is None or not isinstance(r.get("available"), int):
            continue  # never seen before, or a failed read: not a release
        gained = r["available"] - before
        if gained >= RELEASE_MIN:
            releases.append({**r, "gained": gained, "was": before})

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
        if queued:
            # Distinct from 2: not our IP, not our code, nothing to retry harder at.
            return 4
        if errors:
            # Must not exit 0: a sweep that checked nothing is a failure, and
            # reporting success made a fully-403'd run look green in Actions.
            print("ALL SEAT CHECKS FAILED (tickets.fandango.com blocks datacenter IPs)")
            return 2

    SEAT_HITS_PATH.write_text(json.dumps(newly, indent=2, sort_keys=True))
    if args.json:
        print(json.dumps(results, indent=2))

    if releases:
        print(f"\nSEATS RELEASED on {len(releases)} showtime(s):")
        for r in releases:
            print(f"  {r['date']} {r['display']}  +{r['gained']} "
                  f"({r['was']} -> {r['available']} free)")

    failed_alert = False
    if args.notify_issue:
        import notify_issue
        for hits, kind in ((newly, "seats"), (releases, "release")):
            if not hits:
                continue
            ok, detail = notify_issue.create_issue(hits, kind=kind)
            print(f"notify({kind}): {'ok' if ok else 'FAILED'} - {detail}")
            if not ok:
                failed_alert = True

    # Found something but couldn't tell anyone - must not look clean.
    if failed_alert:
        return 3
    return 10 if (newly or releases) else 0


if __name__ == "__main__":
    sys.exit(main())
