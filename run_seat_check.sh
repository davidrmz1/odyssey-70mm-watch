#!/bin/bash
# Runs the seat sweep and, when a showtime newly gains a centred pair, opens an
# assigned GitHub issue -- the alert path that was verified to push to the phone.
#
# Driven by launchd (see com.davidramirez.odyssey-seats.plist). Seat maps can
# only be read from a residential IP: tickets.fandango.com 403s datacenter IPs,
# so this cannot run on GitHub Actions.

set -uo pipefail

REPO_DIR="/Users/davidramirez/odyssey-70mm-watch"
GH="/opt/homebrew/bin/gh"
PY="/usr/bin/python3"
REPO="davidrmz1/odyssey-70mm-watch"
LOG="$REPO_DIR/seat_check.log"

cd "$REPO_DIR" || exit 1

# Keep the log from growing without bound.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') starting sweep ===" >> "$LOG"

"$PY" seat_check.py >> "$LOG" 2>&1
code=$?
echo "--- exit $code ---" >> "$LOG"

# 0 = nothing new, 2 = every check failed, 10 = newly-available centre seats
if [ "$code" != "10" ]; then
  [ "$code" = "2" ] && echo "ALL CHECKS FAILED - Fandango may be blocking this machine" >> "$LOG"
  exit 0
fi

BODY=$("$PY" - <<'PY'
import json, pathlib
hits = json.loads(pathlib.Path("seat_hits.json").read_text())
# The @mention plus the assignee are what make the GitHub mobile app push.
print("@davidrmz1\n")
print(f"Centre seats opened up on {len(hits)} showtime(s):\n")
for h in hits:
    b = h.get("best_centred") or {}
    seats = "+".join(b.get("seats", [])) or "?"
    print(f"- **{h['date']} {h['display']}** — {seats} "
          f"(row {b.get('row','?')}, {b.get('depth',0):.0%} back), "
          f"{h['pairs_ideal']} ideal pair(s), {h['available']}/{h['total']} free")
    print(f"  [book]({h['url']})")
print("\nThese go fast — yesterday every centre pair sold within a day.")
PY
)

TITLE=$("$PY" - <<'PY'
import json
h = json.load(open("seat_hits.json"))
f = h[0]
extra = f" +{len(h)-1} more" if len(h) > 1 else ""
print(f"Odyssey 70mm: CENTRE SEATS open {f['date']} {f['display']}{extra}")
PY
)

echo "$BODY" | "$GH" issue create -R "$REPO" --assignee davidrmz1 \
  --title "$TITLE" --body-file - >> "$LOG" 2>&1
echo "--- alert issue created ---" >> "$LOG"
