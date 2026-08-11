#!/usr/bin/env python3
"""Open a GitHub issue as the alert. Cross-platform, standard library only.

Why an issue rather than email or SMS: it needs no mail credential, and the
GitHub mobile app pushes it to the phone. Crucially the app has NO push category
for "issue in a repo you watch" -- only Direct Mentions, Assigned, Workflow Runs
and friends. So the issue MUST assign the user and @mention them, or it silently
never pushes.

It must also be opened by SOMEONE ELSE. GitHub sends no notification for your
own activity, so an issue created with davidrmz1's own credential -- which is
what any personal token here is -- assigns and @mentions the recipient and
notifies nobody. Verified 2026-08-10: bot-authored issues #3/#4 each produced a
"mention" notification; self-authored #5 produced none.

So this does not POST to the issues API. It dispatches .github/workflows/alert.yml,
and github-actions[bot] opens the issue from the runner. A fine-grained token
therefore needs Actions: write (to dispatch), not Issues: write -- the bot
supplies the issue permission on the other side.

Auth: read from, in order:
    1. GITHUB_TOKEN environment variable
    2. gh_token.txt beside this file (gitignored)
    3. the gh CLI's stored credentials, if gh is installed
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO = "davidrmz1/odyssey-70mm-watch"
USER = "davidrmz1"
API = f"https://api.github.com/repos/{REPO}/issues"
WORKFLOW = "alert.yml"
BRANCH = "main"  # workflow_dispatch only resolves workflows on the default branch
DISPATCH_API = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
HERE = Path(__file__).parent


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip(), "environment"
    f = HERE / "gh_token.txt"
    if f.exists():
        tok = f.read_text().strip()
        if tok:
            return tok, "gh_token.txt"
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True,
                             text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip(), "gh CLI"
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


def build_body(hits):
    lines = [f"@{USER}", "", f"Centre seats opened up on {len(hits)} showtime(s):", ""]
    for h in hits:
        b = h.get("best_centred") or {}
        seats = "+".join(b.get("seats", [])) or "?"
        lines.append(
            f"- **{h['date']} {h['display']}** — {seats} "
            f"(row {b.get('row', '?')}, {b.get('depth', 0):.0%} back), "
            f"{h['pairs_ideal']} ideal pair(s), {h['available']}/{h['total']} free"
        )
        lines.append(f"  [book]({h['url']})")
    lines += ["", "These go fast — every centre pair found on 2026-08-06 sold within a day."]
    return "\n".join(lines)


def build_title(hits):
    f = hits[0]
    extra = f" +{len(hits) - 1} more" if len(hits) > 1 else ""
    return f"Odyssey 70mm: CENTRE SEATS open {f['date']} {f['display']}{extra}"


def build_dates_body(hits):
    """A newly-listed showtime, not a seat hit. Seats are NOT checked here."""
    lines = [f"@{USER}", "",
             f"{len(hits)} new IMAX 70mm evening showtime(s) at Regal Irvine Spectrum:", ""]
    for h in hits:
        lines.append(f"- **{h['date']} {h['display']}** — [book]({h['url']})")
    lines += ["", "Seats are not checked here; this only means the showtime is newly listed."]
    return "\n".join(lines)


def build_dates_title(hits):
    f = hits[0]
    extra = f" +{len(hits) - 1} more" if len(hits) > 1 else ""
    return f"Odyssey 70mm: new evening showtime {f['date']} {f['display']}{extra}"


def build_release_body(hits):
    """A block of seats went back on sale. Says nothing about whether they are
    centred -- that is what the "seats" alert is for."""
    lines = [f"@{USER}", "",
             f"Seats went back on sale on {len(hits)} showtime(s):", ""]
    for h in hits:
        b = h.get("best_centred") or {}
        seats = "+".join(b.get("seats", []))
        where = (f"best centred now {seats} (row {b.get('row', '?')}, "
                 f"{b.get('depth', 0):.0%} back)") if seats else "no centred pair"
        lines.append(
            f"- **{h['date']} {h['display']}** — **+{h['gained']} seats** "
            f"({h['was']} → {h['available']} of {h['total']} free); {where}"
        )
        lines.append(f"  [book]({h['url']})")
    lines += ["", "These are not necessarily good seats — check the map before booking."]
    return "\n".join(lines)


def build_release_title(hits):
    f = hits[0]
    extra = f" +{len(hits) - 1} more" if len(hits) > 1 else ""
    return f"Odyssey 70mm: +{f['gained']} seats released {f['date']} {f['display']}{extra}"


RENDERERS = {
    "seats": (build_title, build_body),
    "dates": (build_dates_title, build_dates_body),
    "release": (build_release_title, build_release_body),
}


def create_issue(hits, kind="seats"):
    """Dispatch alert.yml so the BOT opens the issue. See module docstring for
    why this cannot just POST to the issues API.

    kind: "seats" (centre pair opened up) or "dates" (new showtime listed).
    """
    if kind not in RENDERERS:
        return False, f"unknown alert kind {kind!r}"
    if not hits:
        return True, "no hits; no issue"
    token, source = get_token()
    if not token:
        return False, ("no token: set GITHUB_TOKEN, create gh_token.txt, "
                       "or install and log in to the gh CLI")

    # inputs values must be strings, so the hit list travels as encoded JSON.
    payload = json.dumps({
        "ref": BRANCH,
        "inputs": {"hits": json.dumps(hits), "kind": kind},
    }).encode()

    req = urllib.request.Request(DISPATCH_API, data=payload, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "odyssey-70mm-watch",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
        # 204 No Content is success; the issue appears once the runner starts.
        return True, f"dispatched {WORKFLOW} kind={kind} (HTTP {code}, token from {source})"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return False, f"HTTP {exc.code}: {detail}"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


if __name__ == "__main__":
    tok, src = get_token()
    print(f"token: {'found via ' + src if tok else 'NOT FOUND'}")
    demo = [{"date": "2026-09-14", "display": "6:30p", "available": 141, "total": 387,
             "pairs_ideal": 3, "url": "https://example.com",
             "best_centred": {"seats": ["D26", "D25"], "row": "D", "depth": 0.30}}]
    print("--- title ---"); print(build_title(demo))
    print("--- body ---"); print(build_body(demo))
