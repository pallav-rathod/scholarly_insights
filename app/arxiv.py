from __future__ import annotations

import hashlib
import json
import re
import ssl
import threading
import time
from datetime import date
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
import feedparser
from flask import current_app

from .db import get_db, postgres_arxiv_request_lock, row_to_article, save_articles


class ArxivError(RuntimeError):
    pass


class ArxivClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_request = 0.0

    @staticmethod
    def _query_term(field: str, value: str) -> str:
        value = " ".join(value.split())
        if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
            raise ValueError(f"{field} must be between 1 and 160 printable characters")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{field}:"{escaped}"'

    def build_query(self, filters: dict) -> tuple[str, dict]:
        terms: list[str] = []
        normalized: dict = {}
        keyword = filters.get("q", "").strip()
        author = filters.get("author", "").strip()
        category = filters.get("category", "").strip()
        arxiv_id = filters.get("id", "").strip()
        from_date = filters.get("from_date", "").strip()
        to_date = filters.get("to_date", "").strip()
        if keyword:
            terms.append(self._query_term("all", keyword))
            normalized["q"] = " ".join(keyword.split())
        if author:
            authors = [" ".join(value.split()) for value in author.split(",") if value.strip()]
            if not authors:
                raise ValueError("author must contain at least one name")
            if len(authors) > 10:
                raise ValueError("author accepts at most 10 comma-separated names")
            author_terms = [self._query_term("au", value) for value in authors]
            terms.append(author_terms[0] if len(author_terms) == 1 else f"({' OR '.join(author_terms)})")
            normalized["author"] = ", ".join(authors)
        if category:
            categories = [value.strip() for value in category.split(",") if value.strip()]
            if not categories:
                raise ValueError("category must contain at least one category")
            if len(categories) > 10 or any(not re.fullmatch(r"[A-Za-z0-9.-]{1,32}", value) for value in categories):
                raise ValueError("category contains unsupported characters or too many values")
            category_terms = [f"cat:{value}" for value in categories]
            terms.append(category_terms[0] if len(category_terms) == 1 else f"({' OR '.join(category_terms)})")
            normalized["category"] = ", ".join(categories)
        if arxiv_id:
            if not re.fullmatch(r"(?:\d{4}\.\d{4,5}(?:v\d+)?|[A-Za-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)", arxiv_id):
                raise ValueError("id must be a valid arXiv identifier")
            terms.append(f"id:{arxiv_id}")
            normalized["id"] = arxiv_id
        parsed_from = self._parse_date(from_date, "from_date")
        parsed_to = self._parse_date(to_date, "to_date")
        if parsed_from and parsed_to and parsed_from > parsed_to:
            raise ValueError("from_date must not be later than to_date")
        if parsed_from or parsed_to:
            lower = parsed_from.strftime("%Y%m%d") + "0000" if parsed_from else "000000000000"
            upper = parsed_to.strftime("%Y%m%d") + "2359" if parsed_to else "999912312359"
            terms.append(f"submittedDate:[{lower} TO {upper}]")
            if parsed_from:
                normalized["from_date"] = parsed_from.isoformat()
            if parsed_to:
                normalized["to_date"] = parsed_to.isoformat()
        return " AND ".join(terms), normalized

    @staticmethod
    def _parse_date(value: str, field: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from exc

    def search(self, filters: dict, *, force_refresh: bool = False) -> dict:
        search_query, normalized = self.build_query(filters)
        if not search_query:
            raise ValueError("Enter a keyword, author, or category to search")
        sort = filters.get("sort") or "newest"
        sort_map = {
            "newest": ("submittedDate", "descending"),
            "updated": ("lastUpdatedDate", "descending"),
            "relevance": ("relevance", "descending"),
        }
        if sort not in sort_map:
            raise ValueError("sort must be newest, updated, or relevance")
        try:
            start = int(filters.get("start", 0))
            limit = int(filters.get("limit", 20))
        except (TypeError, ValueError) as exc:
            raise ValueError("start and limit must be integers") from exc
        if start < 0 or start > 10000:
            raise ValueError("start must be between 0 and 10000")
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        sort_by, sort_order = sort_map[sort]
        normalized.update(sort=sort, start=start, limit=limit)
        cache_key = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        db = get_db()
        cached = db.execute(
            "SELECT article_ids, total, fetched_at FROM query_cache WHERE query_hash=?",
            (cache_key,),
        ).fetchone()
        now = time.time()
        ttl = current_app.config["ARXIV_CACHE_TTL"]
        if cached and now - cached["fetched_at"] < ttl and not force_refresh:
            return self._cached_result(json.loads(cached["article_ids"]), cached["total"])

        params = {
            "search_query": search_query,
            "start": start,
            "max_results": limit,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        try:
            payload = self._fetch(params)
            parsed = feedparser.parse(payload)
        except (URLError, TimeoutError, OSError) as exc:
            current_app.logger.warning("arXiv API request failed: %s", exc, exc_info=True)
            if cached:
                result = self._cached_result(json.loads(cached["article_ids"]), cached["total"])
                result["stale"] = True
                return result
            raise ArxivError("arXiv is temporarily unavailable; no cached results exist.") from exc
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise ArxivError("arXiv returned an unreadable Atom response.")
        articles = [self._entry_to_article(entry) for entry in parsed.entries]
        save_articles(articles)
        ids = [article["arxiv_id"] for article in articles]
        total = int(parsed.feed.get("opensearch_totalresults") or len(ids))
        db.execute(
            """INSERT INTO query_cache(query_hash, article_ids, total, fetched_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(query_hash) DO UPDATE SET article_ids=excluded.article_ids,
                 total=excluded.total, fetched_at=excluded.fetched_at""",
            (cache_key, json.dumps(ids), total, now),
        )
        db.commit()
        return {"articles": articles, "total": total, "stale": False}

    def _fetch(self, params: dict) -> bytes:
        with self._lock:
            if current_app.config.get("DATABASE_URL"):
                with postgres_arxiv_request_lock(current_app.config["ARXIV_MIN_INTERVAL"]):
                    return self._request(params)
            wait = current_app.config["ARXIV_MIN_INTERVAL"] - (
                time.monotonic() - self._last_request
            )
            if wait > 0:
                time.sleep(wait)
            try:
                return self._request(params)
            finally:
                self._last_request = time.monotonic()

    @staticmethod
    def _request(params: dict) -> bytes:
        request = Request(
            f'{current_app.config["ARXIV_API_URL"]}?{urlencode(params)}',
            headers={"User-Agent": "ScholarlyInsight/1.0 (academic research discovery)"},
        )
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(request, timeout=30, context=context) as response:
            return response.read()

    @staticmethod
    def _entry_to_article(entry) -> dict:
        raw_id = entry.get("id", "").rstrip("/")
        match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)$", raw_id, re.I)
        arxiv_id = match.group(1) if match else raw_id.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        links = entry.get("links", [])
        pdf = next((link.get("href", "") for link in links if link.get("type") == "application/pdf"), "")
        categories = [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")]
        authors = [author.get("name", "") for author in entry.get("authors", []) if author.get("name")]
        return {
            "arxiv_id": arxiv_id,
            "title": " ".join(entry.get("title", "").split()),
            "authors": authors,
            "abstract": " ".join(entry.get("summary", "").split()),
            "categories": categories,
            "primary_category": entry.get("arxiv_primary_category", {}).get("term", ""),
            "published": entry.get("published", ""),
            "updated": entry.get("updated", ""),
            "pdf_url": pdf,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "doi": entry.get("arxiv_doi", ""),
            "journal_ref": entry.get("arxiv_journal_ref", ""),
            "comment": entry.get("arxiv_comment", ""),
        }

    @staticmethod
    def _cached_result(ids: list[str], total: int) -> dict:
        if not ids:
            return {"articles": [], "total": total, "stale": False}
        placeholders = ",".join("?" for _ in ids)
        rows = get_db().execute(
            f"SELECT * FROM articles WHERE arxiv_id IN ({placeholders})", ids
        ).fetchall()
        by_id = {row["arxiv_id"]: row_to_article(row) for row in rows}
        return {
            "articles": [by_id[arxiv_id] for arxiv_id in ids if arxiv_id in by_id],
            "total": total,
            "stale": False,
        }


client = ArxivClient()
