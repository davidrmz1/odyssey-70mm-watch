# odyssey-70mm-watch

Watches **Regal Irvine Spectrum** for newly-released **IMAX 70mm** showtimes of
*The Odyssey* and emails/texts when one appears in the evening window.

Runs on GitHub Actions, so it keeps working when your computer is asleep or offline.

## What it alerts on

Evening showtimes only — start between **17:00 and 21:30**. Morning and afternoon
shows are tracked in `state.json` but never alerted on.

It fires when a showtime is **newly listed**, or when one flips from unavailable
back to available.

### What it does *not* do

**It does not check seats.** Fandango's showtime feed reports every listed show as
`available`, which means "on sale", not "has seats left". Seat-level data needs a
server-side order context that only a real browser session establishes. So an alert
means *a new showtime exists*, not *two center seats are free*.

As of 2026-08-06 the whole run through **2026-09-16** is already listed, so in
practice the useful trigger is a **run extension past Sept 16**.

## Setup

Add these under **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the Gmail address that sends the alert |
| `SMTP_PASS` | a Gmail **App Password**, not your account password |
| `MAIL_TO` | where the full alert goes, e.g. `you@example.com` |
| `MAIL_TO_SMS` | *(optional)* carrier gateway address, for a text |

Gmail app password: enable 2-Step Verification, then
<https://myaccount.google.com/apppasswords>. It's a 16-character string.

### Carrier email-to-SMS gateways

`MAIL_TO_SMS` should be your 10-digit number at your carrier's gateway:

| Carrier | Address |
| --- | --- |
| AT&T / Cricket | `5551234567@txt.att.net` |
| T-Mobile / Mint / Metro | `5551234567@tmomail.net` |
| Verizon / Visible | `5551234567@vtext.com` |
| Google Fi | `5551234567@msg.fi.google.com` |
| US Cellular | `5551234567@email.uscc.net` |

These gateways are free but **best-effort** — carriers have been quietly degrading
and shutting them down, and they silently drop long messages. The plain email to
`MAIL_TO` is the reliable channel; treat the text as a bonus.

## Schedule

| Cron (UTC) | Mode | Requests |
| --- | --- | --- |
| `7,22,37,52 * * * *` | `frontier` — next 7 days + the horizon edge | ~29 |
| `12 */3 * * *` | `full` — every day in a 60-day window | ~60 |

GitHub's scheduled runs are queued, not guaranteed — under load they can be delayed
by 10+ minutes, and the schedule is disabled after 60 days of repo inactivity.

## Running by hand

Actions → *odyssey-70mm-watch* → **Run workflow**, choosing `mode` and optionally
`baseline` (records current state and alerts on nothing — use this after any change
to the time window, so you don't get a flood of alerts for shows you already knew
about).

Locally:

```sh
python3 odyssey_watch.py --mode full --days 60          # scan, print, no email
python3 odyssey_watch.py --mode frontier --notify       # scan and email on a hit
python3 odyssey_watch.py --baseline                     # reset state quietly
python3 notify.py                                       # test email delivery
```

Exit codes: `0` nothing new · `10` hit (email sent) · `2` every request failed
(endpoint probably changed) · `3` hit found but the email failed.

## How it works

Fandango's internal endpoint:

```
https://www.fandango.com/napi/theaterMovieShowtimes/AABTB?startDate=YYYY-MM-DD
```

`AABTB` is Regal Irvine Spectrum. A `Referer: https://www.fandango.com/` header is
**required** — without it the endpoint returns
`{"error":"FORBIDDEN","errorMessage":"Session expired or invalid token"}`.

70mm shows are the entries whose `filmFormat[].filterName` includes `IMAX 70MM`
(Fandango movie id `241386`, distinct from the standard-format id `241283`).

`regmovies.com` and `imax.com` both return 403 to non-browser clients, which is why
this uses Fandango.

State lives in `state.json`, committed back by the workflow so it survives between
runs. A `frontier` run merges onto existing state rather than replacing it, so the
days it didn't scan aren't mistaken for cancelled shows.
