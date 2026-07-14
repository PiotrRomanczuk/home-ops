#!/usr/bin/env python3
"""send-digest.py — send the home-ops digest via Gmail SMTP using stdlib smtplib.

No system packages, no msmtp, no sudo: Python 3 is already on elitedesk. Reads
the HTML body from stdin and config from the environment. The app password is
read from a 0600 file (SMTP_PASS_FILE) so it is never placed in an env var
(which would be visible via /proc/<pid>/environ).

Env:
  MAIL_FROM, MAIL_TO, MAIL_SUBJECT   required
  SMTP_HOST       default smtp.gmail.com
  SMTP_PORT       default 587 (STARTTLS)
  SMTP_USER       default = MAIL_FROM
  SMTP_PASS_FILE  default ~/.config/home-ops/smtp.pass

Exits 0 on send; non-zero with a message that never echoes the password.
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"send-digest: missing required env {name}")
    return value


def _read_password(path: Path) -> str:
    if not path.is_file():
        sys.exit(f"send-digest: password file not found: {path} (see README)")
    password = path.read_text(encoding="utf-8").strip()
    if not password:
        sys.exit(f"send-digest: password file is empty: {path}")
    return password


def main() -> int:
    mail_from = _require("MAIL_FROM")
    mail_to = _require("MAIL_TO")
    subject = _require("MAIL_SUBJECT")

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip() or mail_from
    pass_file = Path(
        os.environ.get("SMTP_PASS_FILE", "~/.config/home-ops/smtp.pass")
    ).expanduser()
    password = _read_password(pass_file)

    html = sys.stdin.read()
    if not html.strip():
        sys.exit("send-digest: empty body on stdin")

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.set_content("Your client does not render HTML — this is the home-ops digest.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        # Gmail returns an app-password hint here — never echo the secret itself.
        sys.exit(
            "send-digest: SMTP auth failed — the value in "
            f"{pass_file} must be a valid 16-char Gmail app password "
            "(2-Step Verification enabled on the account)."
        )
    except (smtplib.SMTPException, OSError) as exc:
        sys.exit(f"send-digest: send failed: {exc}")

    print(f"digest sent to {mail_to} via {host}:{port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
