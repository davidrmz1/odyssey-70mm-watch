#!/usr/bin/env python3
"""Open a GitHub issue as the alert. Cross-platform, standard library only.

Why an issue rather than email or SMS: it needs no mail credential, and the
GitHub mobile app pushes it to the phone. Crucially the app has NO push category
for "issue in a repo you watch" -- only Direct Mentions, Assigned, Workflow Runs
and friends. So the issue MUST assign the user and @mention them, or it silently
never pushes.

Auth: a fine-grained personal access token scoped to this one repo with
Issues: read/write. Read from, in order:
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


def create_issue(hits):
    if not hits:
        return True, "no hits; no issue"
    token, source = get_token()
    if not token:
        return False, ("no token: set GITHUB_TOKEN, create gh_token.txt, "
                       "or install and log in to the gh CLI")

    payload = json.dumps({
        "title": build_title(hits),
        "body": build_body(hits),
        "assignees": [USER],   # drives the "Assigned" push category
    }).encode()

    req = urllib.request.Request(API, data=payload, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "odyssey-70mm-watch",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            num = json.load(resp).get("number")
        return True, f"opened issue #{num} (token from {source})"
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
