from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from .db import get_db

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "Scholarly Insight <onboarding@resend.dev>"


def send_email(subject: str, body: str, to: str) -> bool:
    """Send a plain-text email through the Resend API.

    Returns False (and logs) when email is not configured or delivery fails,
    so callers can treat alerts as best-effort.
    """
    api_key = current_app.config.get("RESEND_API_KEY", "")
    if not api_key or not to:
        return False
    payload = {
        "from": current_app.config.get("EMAIL_FROM") or DEFAULT_FROM,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    request = Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return 200 <= response.status < 300
    except HTTPError as exc:
        current_app.logger.warning("Resend rejected alert email: %s %s", exc.code, exc.read()[:500])
        return False
    except (URLError, TimeoutError, OSError) as exc:
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
    plural = "s" if len(entries) != 1 else ""
    subject = f"[Scholarly Insight] {len(entries)} new paper{plural} for \"{tracker_name}\""
    lines = [
        f"Scholarly Insight found {len(entries)} new paper{plural} matching your tracker \"{tracker_name}\":",
        "",
        *entries,
    ]
    base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        lines += ["", f"View all alerts: {base_url}/alerts"]
    return send_email(subject, "\n".join(lines), to)
