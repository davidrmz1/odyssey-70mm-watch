#!/usr/bin/env python3
"""Email notifier for the Odyssey 70mm watcher.

Two recipient lists, because a carrier email-to-SMS gateway truncates hard
(~160 chars) and mangles long URLs:

    MAIL_TO      full detail, one line + ticket link per showtime
    MAIL_TO_SMS  terse, no URLs, sized to survive an SMS gateway

Config comes from environment variables (GitHub Actions Secrets):
    SMTP_HOST     e.g. smtp.gmail.com
    SMTP_PORT     e.g. 587
    SMTP_USER     the sending account
    SMTP_PASS     app password, NOT the account password
    MAIL_TO       comma-separated
    MAIL_TO_SMS   comma-separated, optional
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

SITE = "https://www.fandango.com/regal-irvine-spectrum-aabtb/theater-page"


def _split(raw):
    return [a.strip() for a in (raw or "").split(",") if a.strip()]


def _pretty(show):
    """'2026-09-17' + '6:30p' -> 'Thu Sep 17, 6:30p'"""
    from datetime import datetime
    d = datetime.strptime(show["date"], "%Y-%m-%d")
    return f"{d:%a %b %-d}, {show['display']}"


def build_bodies(hits):
    n = len(hits)
    subject = (
        f"Odyssey 70mm: {n} new evening show{'s' if n != 1 else ''} at Irvine Spectrum"
    )

    full = [
        f"{n} new IMAX 70mm evening showtime{'s' if n != 1 else ''} "
        f"at Regal Irvine Spectrum:",
        "",
    ]
    for s in hits:
        full.append(f"  {_pretty(s)}")
        full.append(f"  {s['url']}")
        full.append("")
    full += [
        "Seats are NOT checked -- this only means the showtime is newly listed.",
        "Book fast; 70mm shows have been selling out within hours.",
        "",
        SITE,
    ]

    # Terse for SMS gateways. Keep it comfortably under 160 chars.
    times = "; ".join(_pretty(s) for s in hits[:3])
    more = f" +{n - 3} more" if n > 3 else ""
    sms = f"ODYSSEY 70mm Irvine: {times}{more}. Book now."
    if len(sms) > 155:
        sms = sms[:152] + "..."

    return subject, "\n".join(full), sms


def send(hits):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to_full = _split(os.environ.get("MAIL_TO"))
    to_sms = _split(os.environ.get("MAIL_TO_SMS"))

    missing = [
        name for name, val in
        (("SMTP_HOST", host), ("SMTP_USER", user), ("SMTP_PASS", password))
        if not val
    ]
    if missing:
        return False, f"missing config: {', '.join(missing)}"
    if not to_full and not to_sms:
        return False, "no recipients (set MAIL_TO and/or MAIL_TO_SMS)"

    subject, body_full, body_sms = build_bodies(hits)
    sent_to = []

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(user, password)

            if to_full:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = user
                msg["To"] = ", ".join(to_full)
                msg.set_content(body_full)
                smtp.send_message(msg)
                sent_to += to_full

            for addr in to_sms:
                # Gateways generally prepend/ignore the subject; keep it empty
                # so the whole text is the body.
                msg = EmailMessage()
                msg["Subject"] = ""
                msg["From"] = user
                msg["To"] = addr
                msg.set_content(body_sms)
                smtp.send_message(msg)
                sent_to.append(addr)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, f"delivered to {len(sent_to)} recipient(s)"


if __name__ == "__main__":
    # Manual smoke test: python3 notify.py
    demo = [{
        "date": "2026-09-17",
        "display": "6:30p",
        "url": "https://tickets.fandango.com/example",
    }]
    subject, full, sms = build_bodies(demo)
    print("SUBJECT:", subject)
    print("\n--- FULL ---\n" + full)
    print(f"\n--- SMS ({len(sms)} chars) ---\n{sms}")
    print("\nsending...", send(demo))
