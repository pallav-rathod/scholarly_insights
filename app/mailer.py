from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from .db import get_db


def send_email(subject: str, body: str, to: str) -> bool:
    """Send a plain-text email through the configured SMTP server.

    Returns False (and logs) when email is not configured or delivery fails,
    so callers can treat alerts as best-effort.
    """
    host = current_app.config.get("SMTP_HOST", "")
    if not host or not to:
        return False
    message = EmailMessage()
    message["From"] = (
        current_app.config.get("EMAIL_FROM")
        or current_app.config.get("SMTP_USERNAME", "")
    )
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        port = int(current_app.config.get("SMTP_PORT", 587))
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            username = current_app.config.get("SMTP_USERNAME", "")
            if username:
                server.login(username, current_app.config.get("SMTP_PASSWORD", ""))
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        current_app.logger.warning("Could not send alert email: %s", exc)
        return False


def email_new_paper_alerts(uid: str, tracker_name: str, arxiv_ids: list[str]) -> bool:
    """Email the tracker owner about newly created in-app notifications."""
    if not arxiv_ids:
        return False
    db = get_db()
    user = db.execute("SELECT email FROM users WHERE uid=?", (uid,)).fetchone()
    to = user["email"] if user else ""
    if not to:
        current_app.logger.info("No email on file for user %s; skipping alert email", uid)
        return False
    placeholders = ",".join("?" for _ in arxiv_ids)
    rows = db.execute(
        f"""SELECT arxiv_id, title, authors, published, abs_url
            FROM articles WHERE arxiv_id IN ({placeholders})""",
        arxiv_ids,
    ).fetchall()
    by_id = {row["arxiv_id"]: row for row in rows}
    entries = []
    for arxiv_id in arxiv_ids:
        row = by_id.get(arxiv_id)
        if not row:
            continue
        authors = ", ".join(json.loads(row["authors"]))
        published = (row["published"] or "")[:10]
        entries.append(
            f"- {row['title']}\n"
            f"  {authors}{f' — {published}' if published else ''}\n"
            f"  {row['abs_url']}"
        )
    if not entries:
        return False
    subject = (
        f"[Scholarly Insight] {len(entries)} new paper"
        f"{'s' if len(entries) != 1 else ''} for \"{tracker_name}\""
    )
    lines = [
        f"Scholarly Insight found {len(entries)} new paper"
        f"{'s' if len(entries) != 1 else ''} matching your tracker \"{tracker_name}\":",
        "",
        *entries,
    ]
    base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        lines += ["", f"View all alerts: {base_url}/alerts"]
    return send_email(subject, "\n".join(lines), to)
