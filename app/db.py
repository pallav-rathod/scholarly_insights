from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS articles (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    abstract TEXT NOT NULL,
    categories TEXT NOT NULL,
    primary_category TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    abs_url TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    journal_ref TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS query_cache (
    query_hash TEXT PRIMARY KEY,
    article_ids TEXT NOT NULL,
    total INTEGER NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS favorites (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uid, arxiv_id)
);
CREATE TABLE IF NOT EXISTS reading_history (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uid, arxiv_id)
);
CREATE TABLE IF NOT EXISTS trackers (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '',
    last_notified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS trackers_uid_idx ON trackers(uid);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    tracker_id TEXT NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    UNIQUE (uid, tracker_id, arxiv_id)
);
CREATE INDEX IF NOT EXISTS notifications_uid_idx
    ON notifications(uid, read_at, created_at DESC);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS comments_article_idx ON comments(arxiv_id, created_at);
CREATE TABLE IF NOT EXISTS arxiv_rate_limit (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    last_request_at REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO arxiv_rate_limit(singleton_id, last_request_at) VALUES (1, 0);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    abstract TEXT NOT NULL,
    categories TEXT NOT NULL,
    primary_category TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    abs_url TEXT NOT NULL DEFAULT '',
    doi TEXT NOT NULL DEFAULT '',
    journal_ref TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    cached_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS query_cache (
    query_hash TEXT PRIMARY KEY,
    article_ids TEXT NOT NULL,
    total INTEGER NOT NULL,
    fetched_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS favorites (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    saved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uid, arxiv_id)
);
CREATE TABLE IF NOT EXISTS reading_history (
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (uid, arxiv_id)
);
CREATE TABLE IF NOT EXISTS trackers (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '',
    last_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS trackers_uid_idx ON trackers(uid);
CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    tracker_id TEXT NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TIMESTAMPTZ,
    UNIQUE (uid, tracker_id, arxiv_id)
);
CREATE INDEX IF NOT EXISTS notifications_uid_idx
    ON notifications(uid, read_at, created_at DESC);
CREATE TABLE IF NOT EXISTS comments (
    id BIGSERIAL PRIMARY KEY,
    arxiv_id TEXT NOT NULL REFERENCES articles(arxiv_id) ON DELETE CASCADE,
    uid TEXT NOT NULL REFERENCES users(uid) ON DELETE CASCADE,
    parent_id BIGINT REFERENCES comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS comments_article_idx ON comments(arxiv_id, created_at);
CREATE TABLE IF NOT EXISTS arxiv_rate_limit (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    last_request_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
INSERT INTO arxiv_rate_limit(singleton_id, last_request_at) VALUES (1, 0)
ON CONFLICT (singleton_id) DO NOTHING;
"""


class PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, statement: str, parameters=()):
        return self._connection.execute(statement.replace("?", "%s"), parameters)

    def executemany(self, statement: str, parameters):
        return self._connection.executemany(statement.replace("?", "%s"), parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _connect_postgres() -> PostgresConnection:
    import psycopg
    from psycopg.rows import dict_row

    return PostgresConnection(
        psycopg.connect(current_app.config["DATABASE_URL"], row_factory=dict_row)
    )


def get_db() -> Any:
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL")
        if database_url:
            g.db = _connect_postgres()
        else:
            database = current_app.config["DATABASE_PATH"]
            if database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(database)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def postgres_arxiv_request_lock(min_interval: float):
    """Serialize arXiv calls across Cloud Run instances using PostgreSQL."""
    from contextlib import contextmanager

    @contextmanager
    def lock():
        connection = _connect_postgres()
        lock_key = 7123849271946658123
        try:
            connection.execute("SELECT pg_advisory_lock(?)", (lock_key,))
            row = connection.execute(
                "SELECT last_request_at FROM arxiv_rate_limit WHERE singleton_id=1"
            ).fetchone()
            elapsed = time.time() - row["last_request_at"]
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            connection.execute(
                "UPDATE arxiv_rate_limit SET last_request_at=? WHERE singleton_id=1",
                (time.time(),),
            )
            connection.commit()
            yield
        finally:
            try:
                connection.execute("SELECT pg_advisory_unlock(?)", (lock_key,))
                connection.commit()
            finally:
                connection.close()

    return lock()


def close_db(_error: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    schema = POSTGRES_SCHEMA if current_app.config.get("DATABASE_URL") else SCHEMA
    db.executescript(schema)
    get_db().commit()


def init_app(app) -> None:
    with app.app_context():
        init_db()


def row_to_article(row: sqlite3.Row | Mapping[str, Any]) -> dict:
    article = dict(row)
    article["authors"] = json.loads(article["authors"])
    article["categories"] = json.loads(article["categories"])
    return article


def save_articles(articles: list[dict]) -> None:
    db = get_db()
    db.executemany(
        """INSERT INTO articles
           (arxiv_id, title, authors, abstract, categories, primary_category,
            published, updated, pdf_url, abs_url, doi, journal_ref, comment)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(arxiv_id) DO UPDATE SET
             title=excluded.title, authors=excluded.authors,
             abstract=excluded.abstract, categories=excluded.categories,
             primary_category=excluded.primary_category,
             published=excluded.published, updated=excluded.updated,
             pdf_url=excluded.pdf_url, abs_url=excluded.abs_url,
             doi=excluded.doi, journal_ref=excluded.journal_ref,
             comment=excluded.comment, cached_at=CURRENT_TIMESTAMP""",
        [
            (
                article["arxiv_id"],
                article["title"],
                json.dumps(article["authors"]),
                article["abstract"],
                json.dumps(article["categories"]),
                article["primary_category"],
                article["published"],
                article["updated"],
                article["pdf_url"],
                article["abs_url"],
                article["doi"],
                article["journal_ref"],
                article["comment"],
            )
            for article in articles
        ],
    )
    db.commit()
