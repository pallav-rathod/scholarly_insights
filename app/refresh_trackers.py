from __future__ import annotations

from . import create_app
from .arxiv import ArxivError, client
from .db import get_db
from .mailer import email_new_paper_alerts


def refresh_all() -> int:
    app = create_app()
    refreshed = 0
    with app.app_context():
        db = get_db()
        trackers = db.execute("SELECT * FROM trackers ORDER BY created_at").fetchall()
        for tracker in trackers:
            filters = {
                "q": tracker["keywords"],
                "author": tracker["authors"],
                "category": tracker["categories"],
                "sort": "newest",
                "limit": 20,
            }
            try:
                results = client.search(filters, force_refresh=True)
            except (ValueError, ArxivError) as exc:
                app.logger.error("Could not refresh tracker %s: %s", tracker["id"], exc)
                continue
            new_ids = []
            for article in results["articles"]:
                cursor = db.execute(
                    """INSERT INTO notifications(uid, tracker_id, arxiv_id)
                       VALUES (?, ?, ?)
                       ON CONFLICT(uid, tracker_id, arxiv_id) DO NOTHING
                       RETURNING arxiv_id""",
                    (tracker["uid"], tracker["id"], article["arxiv_id"]),
                )
                if cursor.fetchone():
                    new_ids.append(article["arxiv_id"])
            db.execute(
                "UPDATE trackers SET last_notified_at=CURRENT_TIMESTAMP WHERE id=?",
                (tracker["id"],),
            )
            db.commit()
            if new_ids:
                email_new_paper_alerts(tracker["uid"], tracker["name"], new_ids)
            refreshed += 1
    return refreshed


if __name__ == "__main__":
    print(f"Refreshed {refresh_all()} tracker(s).")
