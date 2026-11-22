from __future__ import annotations

import re
import uuid

from flask import Blueprint, g, jsonify, render_template, request

from .arxiv import ArxivError, client
from .auth import require_user
from .db import get_db, row_to_article, save_articles
from .insights import related_articles, summary

bp = Blueprint("main", __name__)
ARXIV_ID_RE = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")


def _get_article(arxiv_id: str) -> dict | None:
    row = get_db().execute("SELECT * FROM articles WHERE arxiv_id=?", (arxiv_id,)).fetchone()
    return row_to_article(row) if row else None


def _ensure_article(arxiv_id: str) -> dict | None:
    if not ARXIV_ID_RE.fullmatch(arxiv_id):
        return None
    article = _get_article(arxiv_id)
    if article:
        return article
    try:
        result = client.search({"id": arxiv_id, "sort": "relevance", "limit": 1})
    except (ValueError, ArxivError):
        return None
    return result["articles"][0] if result["articles"] else None


def _upsert_user() -> None:
    user = g.user
    get_db().execute(
        """INSERT INTO users(uid, email, display_name) VALUES (?, ?, ?)
           ON CONFLICT(uid) DO UPDATE SET email=excluded.email,
             display_name=excluded.display_name""",
        (user["uid"], user["email"], user["display_name"]),
    )
    get_db().commit()


def _user_articles(table: str, uid: str) -> list[dict]:
    if table not in {"favorites", "reading_history"}:
        raise ValueError("Unsupported user article table")
    activity_column = "saved_at" if table == "favorites" else "viewed_at"
    rows = get_db().execute(
        f"""SELECT a.*, x.{activity_column} AS activity_at FROM {table} x
            JOIN articles a USING(arxiv_id) WHERE x.uid=?
            ORDER BY x.{activity_column} DESC LIMIT 100""",
        (uid,),
    ).fetchall()
    items = []
    for row in rows:
        article = row_to_article(row)
        article["activity_at"] = row["activity_at"]
        items.append(article)
    return items


@bp.get("/")
def home():
    return render_template("index.html", page="home", insights=summary())


@bp.get("/search")
def search_page():
    filters = {key: request.args.get(key, "") for key in ("q", "author", "category", "from_date", "to_date", "sort", "primary_only")}
    results = None
    error = None
    if request.args:
        filters["start"] = request.args.get("start", "0")
        filters["limit"] = request.args.get("limit", "20")
        try:
            results = client.search(filters)
        except (ValueError, ArxivError) as exc:
            error = str(exc)
    return render_template("search.html", page="search", filters=filters, results=results, error=error)


@bp.get("/article/<path:arxiv_id>")
def article_page(arxiv_id: str):
    article = _ensure_article(arxiv_id)
    if not article:
        return render_template("error.html", page="article", message="Article not found. Try searching arXiv."), 404
    return render_template(
        "article.html",
        page="article",
        article=article,
        related=related_articles(article),
    )


@bp.get("/trackers")
def trackers_page():
    return render_template("account.html", page="trackers", title="My Trackers", mode="trackers")


@bp.get("/library")
def library_page():
    return render_template("account.html", page="library", title="My Library", mode="library")


@bp.get("/alerts")
def alerts_page():
    return render_template("account.html", page="alerts", title="Alerts", mode="alerts")


@bp.get("/api/search")
def api_search():
    if not any(request.args.get(key) for key in ("q", "author", "category", "id", "from_date", "to_date")):
        return jsonify(error="Provide at least one search filter."), 400
    try:
        result = client.search(request.args.to_dict())
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except ArxivError as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(result)


@bp.get("/api/insights")
def api_insights():
    return jsonify(summary())


@bp.get("/api/articles/<path:arxiv_id>/comments")
def get_comments(arxiv_id: str):
    article = _ensure_article(arxiv_id)
    if not article:
        return jsonify(error="Article not found."), 404
    rows = get_db().execute(
        """SELECT c.id, c.parent_id, c.body, c.created_at, u.uid, u.display_name
           FROM comments c JOIN users u ON u.uid=c.uid
           WHERE c.arxiv_id=? ORDER BY c.created_at""",
        (article["arxiv_id"],),
    ).fetchall()
    return jsonify(comments=[dict(row) for row in rows])


@bp.post("/api/me")
@require_user
def sync_user():
    _upsert_user()
    return jsonify(user=g.user)


@bp.get("/api/library")
@require_user
def get_library():
    _upsert_user()
    return jsonify(
        favorites=_user_articles("favorites", g.user["uid"]),
        history=_user_articles("reading_history", g.user["uid"]),
    )


@bp.post("/api/articles/<path:arxiv_id>/favorite")
@require_user
def save_favorite(arxiv_id: str):
    article = _ensure_article(arxiv_id)
    if not article:
        return jsonify(error="Article not found."), 404
    _upsert_user()
    get_db().execute(
        """INSERT INTO favorites(uid, arxiv_id) VALUES (?, ?)
           ON CONFLICT(uid, arxiv_id) DO NOTHING""",
        (g.user["uid"], article["arxiv_id"]),
    )
    get_db().commit()
    return jsonify(saved=True)


@bp.delete("/api/articles/<path:arxiv_id>/favorite")
@require_user
def remove_favorite(arxiv_id: str):
    _upsert_user()
    get_db().execute("DELETE FROM favorites WHERE uid=? AND arxiv_id=?", (g.user["uid"], arxiv_id))
    get_db().commit()
    return jsonify(saved=False)


@bp.post("/api/articles/<path:arxiv_id>/history")
@require_user
def record_history(arxiv_id: str):
    article = _ensure_article(arxiv_id)
    if not article:
        return jsonify(error="Article not found."), 404
    _upsert_user()
    get_db().execute(
        """INSERT INTO reading_history(uid, arxiv_id) VALUES (?, ?)
           ON CONFLICT(uid, arxiv_id) DO UPDATE SET viewed_at=CURRENT_TIMESTAMP""",
        (g.user["uid"], article["arxiv_id"]),
    )
    get_db().commit()
    return jsonify(recorded=True)


@bp.route("/api/trackers", methods=["GET", "POST"])
@require_user
def trackers_api():
    _upsert_user()
    db = get_db()
    if request.method == "GET":
        rows = db.execute("SELECT * FROM trackers WHERE uid=? ORDER BY created_at DESC", (g.user["uid"],)).fetchall()
        return jsonify(trackers=[dict(row) for row in rows])
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    keywords = str(data.get("keywords", "")).strip()
    authors = str(data.get("authors", "")).strip()
    categories = str(data.get("categories", "")).strip()
    if not name or len(name) > 80:
        return jsonify(error="Tracker name must be between 1 and 80 characters."), 400
    if not any((keywords, authors, categories)):
        return jsonify(error="Provide at least one keyword, author, or category."), 400
    tracker_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO trackers(id, uid, name, keywords, authors, categories) VALUES (?, ?, ?, ?, ?, ?)",
        (tracker_id, g.user["uid"], name, keywords, authors, categories),
    )
    db.commit()
    return jsonify(id=tracker_id, name=name), 201


@bp.delete("/api/trackers/<tracker_id>")
@require_user
def delete_tracker(tracker_id: str):
    cursor = get_db().execute("DELETE FROM trackers WHERE id=? AND uid=?", (tracker_id, g.user["uid"]))
    get_db().commit()
    if not cursor.rowcount:
        return jsonify(error="Tracker not found."), 404
    return jsonify(deleted=True)


@bp.post("/api/trackers/<tracker_id>/refresh")
@require_user
def refresh_tracker(tracker_id: str):
    row = get_db().execute("SELECT * FROM trackers WHERE id=? AND uid=?", (tracker_id, g.user["uid"])).fetchone()
    if not row:
        return jsonify(error="Tracker not found."), 404
    filters = {"q": row["keywords"], "author": row["authors"], "category": row["categories"], "sort": "newest", "limit": 20}
    try:
        result = client.search(filters, force_refresh=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except ArxivError as exc:
        return jsonify(error=str(exc)), 503
    db = get_db()
    new_ids = []
    for article in result["articles"]:
        cursor = db.execute(
            """INSERT INTO notifications(uid, tracker_id, arxiv_id)
               VALUES (?, ?, ?)
               ON CONFLICT(uid, tracker_id, arxiv_id) DO NOTHING
               RETURNING arxiv_id""",
            (g.user["uid"], tracker_id, article["arxiv_id"]),
        )
        if cursor.fetchone():
            new_ids.append(article["arxiv_id"])
    db.execute("UPDATE trackers SET last_notified_at=CURRENT_TIMESTAMP WHERE id=?", (tracker_id,))
    db.commit()
    return jsonify(matched=len(result["articles"]), new_alerts=len(new_ids), stale=result["stale"])


@bp.get("/api/alerts")
@require_user
def get_alerts():
    rows = get_db().execute(
        """SELECT n.id, n.created_at, n.read_at, t.name AS tracker_name,
                  a.arxiv_id, a.title
           FROM notifications n JOIN trackers t ON t.id=n.tracker_id
           JOIN articles a ON a.arxiv_id=n.arxiv_id
           WHERE n.uid=? ORDER BY n.created_at DESC LIMIT 100""",
        (g.user["uid"],),
    ).fetchall()
    return jsonify(alerts=[dict(row) for row in rows])


@bp.post("/api/alerts/<int:notification_id>/read")
@require_user
def mark_alert_read(notification_id: int):
    cursor = get_db().execute(
        "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE id=? AND uid=?",
        (notification_id, g.user["uid"]),
    )
    get_db().commit()
    if not cursor.rowcount:
        return jsonify(error="Alert not found."), 404
    return jsonify(read=True)


@bp.post("/api/articles/<path:arxiv_id>/comments")
@require_user
def post_comment(arxiv_id: str):
    article = _ensure_article(arxiv_id)
    if not article:
        return jsonify(error="Article not found."), 404
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    parent_id = data.get("parent_id")
    if not body or len(body) > 5000:
        return jsonify(error="Comment must be between 1 and 5000 characters."), 400
    _upsert_user()
    db = get_db()
    if parent_id is not None:
        parent = db.execute(
            "SELECT id FROM comments WHERE id=? AND arxiv_id=?",
            (parent_id, article["arxiv_id"]),
        ).fetchone()
        if not parent:
            return jsonify(error="Reply target does not belong to this article."), 400
    cursor = db.execute(
        """INSERT INTO comments(arxiv_id, uid, parent_id, body)
           VALUES (?, ?, ?, ?) RETURNING id""",
        (article["arxiv_id"], g.user["uid"], parent_id, body),
    )
    comment_id = cursor.fetchone()["id"]
    db.commit()
    return jsonify(id=comment_id), 201


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.app_errorhandler(404)
def not_found(_error):
    return render_template("error.html", page="", message="That page could not be found."), 404
