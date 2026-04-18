# Agent 4 — Search Agent

## Role & Responsibility

The Search Agent was responsible for implementing the search system: query tokenization, letter-bucket file scanning, relevance scoring, result ranking, and pagination. A core constraint from the Architect Agent was that search must be safe to call while the indexer is actively writing — no locking, no stale-data errors.

---

## Prompt Given to This Agent

```
You are a search systems engineer. Implement search_service.py for a file-based inverted index.

Index format: data/storage/{letter}.data — JSON-lines files, one record per line:
{"word": "starbucks", "url": "https://...", "origin": "https://...", "depth": 1, "freq": 14}

Your deliverable is search_service.py with:

1. search(query, page, per_page) → dict
   - Tokenize query: extract words matching [a-zA-Z]{2,}, lowercase, filter stopwords
   - For each token, determine its letter bucket and scan the corresponding .data file
   - Score each URL: score += (freq * 10) + (1000 if exact match) - (depth * 5)
   - Return paginated results as a list of dicts:
     {"url": ..., "origin": ..., "depth": ..., "relevance_score": ..., "word": ..., "frequency": ...}
   - Also return: total, query, tokens, page, per_page, pages

2. feeling_lucky(query) → dict | None
   - Returns the single top result, or None if no results

Concurrency constraint: search reads files that the indexer appends to concurrently.
- Do NOT acquire any locks in search_service.py
- Handle json.JSONDecodeError on each line (partial writes from the indexer are possible)
- Handle OSError if a letter file does not yet exist
- The indexer only appends — reads will see either complete lines or be at EOF; no line will be partially overwritten

Relevance definition (your decision): you may use any reasonable scoring approach.
Justify your choices. Prefix matching is a plus.

Use Python standard library only.
```

---

## Key Implementation Decisions

### Lock-Free Concurrent Safety

The Search Agent's most important architectural choice was to make search entirely lock-free. This is safe because:

1. The indexer **only appends** to letter-bucket files — it never overwrites or truncates
2. A file opened in read mode on Linux will see all bytes written before the `open()` call, plus any bytes written before the file's internal position pointer advances past EOF
3. The only unsafe case is a partially written final line — handled by catching `json.JSONDecodeError`

```python
try:
    entry = json.loads(line)
except json.JSONDecodeError:
    continue  # skip partial line at EOF — safe to ignore
```

This means search results are "eventually consistent" with the index: a search that runs at time T will see all records written before T, and may or may not see records written during the scan. This is the correct behavior — the requirement is that search "reflects new results as they are discovered," not that it provides a point-in-time snapshot.

### Letter-Bucket Routing

```python
buckets: dict[str, list[str]] = defaultdict(list)
for token in tokens:
    if token[0].isalpha():
        buckets[token[0].lower()].append(token)
```

A multi-word query reads at most 26 files, but typically far fewer. A query like "machine learning" reads only `m.data` and `l.data`. The Search Agent initially scanned all 26 files and filtered — the Evaluation Agent flagged this as unnecessary I/O and the bucket routing was added.

### Relevance Scoring Formula

```
score += (freq * 10) + (1000 if exact_match else 0) - (depth * 5)
```

Three components:

| Component | Weight | Rationale |
|-----------|--------|-----------|
| `freq * 10` | High | Pages that mention the term often are more likely to be about it |
| `+1000` (exact match) | Very high | Exact matches rank above prefix matches |
| `-depth * 5` | Low | Slight penalty for deeply discovered pages; pages closer to the origin are presumed more relevant |

The exact-match bonus was the Search Agent's key decision. Without it, a page containing "pythons" (freq=50) would outrank a page about "python" (freq=5) even when the user searched for "python". The 1000-point bonus ensures exact matches always rank above prefix matches of the same term unless the frequency difference is extreme (>100x).

### Prefix Matching

```python
matched_token = next((t for t in words if word.startswith(t)), None)
```

For each record in the letter-bucket file, the Search Agent checks whether the stored word starts with any query token. This enables prefix matching: searching "wiki" returns results containing "wikipedia", "wikimedia", "wikidata", etc. The Architect Agent listed this as a "plus" feature; the Search Agent implemented it with a single `str.startswith()` call per record.

### Scoring Aggregation Across Tokens

When a URL matches multiple query tokens, scores are summed:

```python
url_scores[url]["score"] += entry_score
url_scores[url]["matched_words"][word] = freq
```

This means a page that mentions both "machine" and "learning" ranks higher than a page that mentions only one of them. Multi-word query coverage is rewarded.

### Result Display: Best Matched Word

The `word` field in each result shows the highest-frequency matched word for that URL:

```python
best_word = max(r["matched_words"], key=r["matched_words"].get)
```

This gives the UI a meaningful word to display alongside each result without returning the full matched-words dict.

---

## Interactions with Other Agents

- **Receives from Architect Agent**: concurrency constraints (lock-free design), storage schema
- **Receives from Indexer Agent**: the letter-bucket files it reads
- **Receives from Evaluation Agent**: performance bug (scanning all files for every query) — fixed by adding bucket routing; correctness concern (partial line handling) — confirmed via JSONDecodeError catch
- **Sends to UI Agent**: the response schema for `/api/search`

---

## Outputs Produced

- `search_service.py`
  - `_tokenize(query)` — query preprocessing
  - `search(query, page, per_page)` — main search function
  - `feeling_lucky(query)` — single top result shortcut
