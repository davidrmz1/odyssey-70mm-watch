# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Read this first: there is live infrastructure attached to this repo

This is not a dormant codebase. As of 2026-08-11 it is **actively running on a
Windows PC** (`C:\Users\mikee\odyssey-70mm-watch`) via Task Scheduler, hitting
Fandango's servers around the clock and able to send the owner phone
notifications. Assume any change you make has immediate real-world effect.

Live components:

| Thing | Where | Cadence |
| --- | --- | --- |
| `OdysseyDateWatch` | Task Scheduler | every **2 min** — new showtimes |
| `OdysseyDateWatchFull` | Task Scheduler | every **30 min** — full 60-day scan |
| `OdysseySeatCheck` | Task Scheduler | every **5 min** — seat maps |
| `deadman.yml` | GitHub Actions | hourly — alerts if the PC goes quiet |

## If the user asks to shut it down / stop it / turn it off

They have booked their tickets and are done. Run:

```powershell
powershell -ExecutionPolicy Bypass -File windows\teardown.ps1
```

**Order matters and the script encodes it.** `deadman.yml` runs in Actions
independently of the PC and opens an issue when heartbeats go stale for 12
hours, so removing the tasks first would alert the user about a system they
switched off deliberately. Disable the workflow *first*, then the tasks.

Doing it by hand is these two, in this order:

```powershell
gh workflow disable deadman.yml --repo davidrmz1/odyssey-70mm-watch
Unregister-ScheduledTask -TaskName OdysseyDateWatch,OdysseyDateWatchFull,OdysseySeatCheck -Confirm:$false
```

Removing the tasks also clears their wake timers, so the PC stops waking itself.
Do not touch the gh CLI login or git credentials — they predate this project.

## Hard-won constraints — do not "fix" these

**Alerts must be opened by the bot, never by this machine.** GitHub sends no
notification for your own activity. An issue created with the owner's own
credential assigns them, @mentions them, and notifies nobody — verified
2026-08-10: bot-authored issues #3/#4 produced a `mention` notification,
self-authored #5 produced none. So `notify_issue.create_issue()` dispatches
`alert.yml` and `github-actions[bot]` opens the issue. Never change it to POST
to the issues API. A fine-grained PAT would have the same flaw; the token needs
**Actions: write**, not Issues: write.

**Seat maps need a residential IP.** `tickets.fandango.com` returns 403 to
datacenter addresses, which is why the sweep cannot run in Actions. If sweeps
start returning `REFUSED HTTP 403`, that is this PC's IP being blocked. **Stop
— do not route around it, do not retry harder, do not add a proxy.** A block
likely applies to the whole household, including buying tickets in a browser,
which defeats the point of the project. `throttle.py` backs off automatically;
let it.

**The tasks must stay `LogonType=Interactive`.** "Run whether user is logged on
or not" would hide the console window without `run_hidden.vbs`, but it needs a
stored password or S4U, and S4U cannot unlock DPAPI — the gh token and git
credential helper both live in Windows Credential Manager behind DPAPI, so
alerting and pushing would silently break. The cost is that checks pause when
the user signs out (locking is fine).

**`DEPTH_MIN = 0.28` is deliberate.** The owner was offered a lower floor and
declined. Rows D–I qualify; row D clears by only 0.017, so it is tight but
intended. Do not loosen it without being asked.

## Architecture

Two independent scans, both on the PC, both alerting through the same bot path:

- `odyssey_watch.py` — showtime feed (`www.fandango.com/napi/...`), writes
  `state.json`. Wrapped by `watch_dates.py`, which alerts with `kind="dates"`.
- `seat_check.py` — checkout API (`tickets.fandango.com`), writes
  `seat_state.json`. Alerts with `kind="seats"` (a centred pair clearing
  `DEPTH_MIN`) or `kind="release"` (a showtime gains `RELEASE_MIN`=4 seats).

`SeatSession` reuses one checkout session across showtimes using the
`showtime_id` values in `state.json` — 39 requests per sweep instead of 111.
That is what makes a 5-minute cadence affordable; do not undo it.

`publish_state.py` commits state and heartbeats, throttled to once an hour per
source (the heartbeat always changes, so unthrottled it would be ~288 commits a
day). Alerting never waits on this.

Full operational detail, including the reasoning behind each decision, is in
`windows/SETUP.md` and the git history — the commit messages explain *why*, not
just what.
