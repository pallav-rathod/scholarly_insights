from __future__ import annotations

import re
from collections import Counter
from math import log, sqrt

from .db import get_db, row_to_article


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.lower())
        if token not in {"the", "and", "for", "with", "from", "using", "based", "that", "this"}
    }


def related_articles(article: dict, limit: int = 5) -> list[dict]:
    rows = get_db().execute(
        "SELECT * FROM articles WHERE arxiv_id != ? ORDER BY published DESC LIMIT 300",
        (article["arxiv_id"],),
    ).fetchall()
    candidates = [row_to_article(row) for row in rows]
    target_tokens = _tokens(article["title"] + " " + article["abstract"])
    if not target_tokens:
        return []
    document_tokens = [_tokens(item["title"] + " " + item["abstract"]) for item in candidates]
    document_frequency = Counter(token for tokens in document_tokens for token in tokens)
    document_count = len(candidates) + 1
    target_vector = {
        token: log((document_count + 1) / (document_frequency[token] + 1)) + 1
        for token in target_tokens
    }
    target_norm = sqrt(sum(weight * weight for weight in target_vector.values()))
    scored = []
    for candidate, tokens in zip(candidates, document_tokens):
        candidate_vector = {
            token: log((document_count + 1) / (document_frequency[token] + 1)) + 1
            for token in tokens
        }
        candidate_norm = sqrt(sum(weight * weight for weight in candidate_vector.values()))
        dot_product = sum(
            target_vector[token] * candidate_vector[token]
            for token in target_tokens & tokens
        )
        score = dot_product / (target_norm * candidate_norm) if candidate_norm else 0
        if set(article["categories"]) & set(candidate["categories"]):
            score += 0.1
        if score:
            scored.append((score, candidate))
    return [candidate for _, candidate in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]


def summary() -> dict:
    db = get_db()
    rows = db.execute("SELECT * FROM articles ORDER BY published DESC LIMIT 2000").fetchall()
    articles = [row_to_article(row) for row in rows]
    categories = Counter()
    authors = Counter()
    months = Counter()
    for article in articles:
        for category in article["categories"]:
            categories[category] += 1
        authors.update(article["authors"])
        if len(article["published"]) >= 7:
            months[article["published"][:7]] += 1
    return {
        "article_count": len(articles),
        "top_categories": categories.most_common(8),
        "top_authors": authors.most_common(8),
        "monthly": sorted(months.items())[-12:],
    }
