"""
Brightwave Crawler - Search Service
Searches indexed words across letter-bucket files.
"""

import os
import json
import re
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STORAGE_DIR = os.path.join(DATA_DIR, "storage")

from stopwords import STOP_WORDS


def _tokenize(query: str) -> list[str]:
    words = re.findall(r"[a-zA-Z]{2,}", query.lower())
    return [w for w in words if w not in STOP_WORDS]


def search(query: str, page: int = 1, per_page: int = 20) -> dict:
    """
    Search indexed content for query terms.
    Returns (relevant_url, origin_url, depth) triples sorted by relevance.
    Reads from letter-bucket files; safe to call while indexing is active.
    """
    tokens = _tokenize(query)
    if not tokens:
        return {"results": [], "total": 0, "query": query, "tokens": []}

    # Map token -> letter bucket
    buckets: dict[str, list[str]] = defaultdict(list)
    for token in tokens:
        if token[0].isalpha():
            buckets[token[0].lower()].append(token)

    # Score: url -> {origin, depth, score, matched_words}
    url_scores: dict[str, dict] = {}

    for letter, words in buckets.items():
        path = os.path.join(STORAGE_DIR, f"{letter}.data")
        if not os.path.exists(path):
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    word = entry.get("word", "")
                    matched_token = next((t for t in words if word.startswith(t)), None)
                    if matched_token is None:
                        continue

                    url = entry.get("url", "")
                    origin = entry.get("origin", "")
                    depth = entry.get("depth", 0)
                    freq = entry.get("freq", 1)

                    if url not in url_scores:
                        url_scores[url] = {
                            "url": url,
                            "origin": origin,
                            "depth": depth,
                            "score": 0,
                            "matched_words": {},
                        }

                    # score = (frequency x 10) + 1000 (exact match bonus) - (depth x 5)
                    is_exact = word in words
                    entry_score = (freq * 10) + (1000 if is_exact else 0) - (depth * 5)
                    url_scores[url]["score"] += entry_score
                    url_scores[url]["matched_words"][word] = freq
        except OSError:
            continue

    # Sort by score descending
    sorted_results = sorted(
        url_scores.values(), key=lambda x: x["score"], reverse=True
    )

    total = len(sorted_results)
    start = (page - 1) * per_page
    end = start + per_page
    page_results = sorted_results[start:end]

    # Return as (relevant_url, origin_url, depth) triples + metadata
    formatted = []
    for r in page_results:
        # Pick the best matched word (highest freq) for display
        best_word = max(r["matched_words"], key=r["matched_words"].get) if r["matched_words"] else tokens[0]
        formatted.append({
            "url": r["url"],
            "origin": r["origin"],
            "depth": r["depth"],
            "relevance_score": r["score"],
            "word": best_word,
            "frequency": r["matched_words"].get(best_word, 0),
        })

    return {
        "results": formatted,
        "total": total,
        "query": query,
        "tokens": tokens,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


def feeling_lucky(query: str) -> dict | None:
    result = search(query, page=1, per_page=1)
    if result["results"]:
        return result["results"][0]
    return None