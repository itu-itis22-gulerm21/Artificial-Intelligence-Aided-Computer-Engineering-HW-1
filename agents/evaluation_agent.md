# Agent 8 — Evaluation Agent (Quality Controller)

## Role & Responsibility

The Evaluation Agent was the quality gate for the entire workflow. It reviewed every other agent's output independently — without access to the producing agent's reasoning — and reported bugs, correctness issues, and improvement opportunities. When it found a problem, it issued a feedback note to the responsible agent, which then revised its output. The Evaluation Agent did a final pass after revisions to confirm the issue was resolved.

---

## Prompt Given to This Agent

```
You are a senior code reviewer with a security and correctness mindset. Review the following files and identify bugs, race conditions, correctness issues, and missing requirements:

Files: crawler.py, search_service.py, app.py, stopwords.py

Check against these requirements:
1. Crawler: no URL crawled twice; depth k strictly enforced; back-pressure activates correctly; rate limiting is per-job; resume restores the full queue (not just the preview)
2. Indexer: HTML artifacts stripped; stopwords filtered; single-character words excluded; words not double-indexed
3. Search: no stale-data errors during concurrent read/write; letter-bucket routing correct; relevance scores sensible; multi-word queries handled
4. Storage: atomic writes; no lock on search reads; resume produces correct job ID

For each issue found:
- File and line number
- Description of the bug or gap
- Recommended fix
- Severity: Critical / Medium / Low

After each agent revises their code, re-review the changed section and confirm the fix.
```

---

## Issues Found and Resolved

### Issue 1 — Crawler: Full Queue Not Saved in Resume (Critical)

**File**: `crawler.py`, `_flush()` method  
**Finding**: The initial `_flush()` implementation saved only `queue_preview` (first 50 URLs) to the state file. When `resume_crawler()` restored a job, it would rebuild a 50-URL queue instead of the full queue — losing potentially thousands of pending URLs.

**Feedback to Crawler Agent**:
> The `queue_preview` field only stores the first 50 URLs. If a crawler with 5,000 URLs in its queue is interrupted, `resume_crawler()` will restore only the first 50. Add a `queue` field to `_flush()` that stores the full queue as `[[url, depth], ...]`. `resume_crawler()` should prefer this field and fall back to `queue_preview` only if `queue` is absent (for backward compatibility with old state files).

**Fix applied in `_flush()`**:
```python
"queue": [[u, d] for u, d in self.queue],  # full queue for resume
"queue_preview": [u for u, d in self.queue[:50]],  # UI display only
```

**Fix applied in `resume_crawler()`**:
```python
saved_queue = state.get("queue", [])
if not saved_queue:
    urls = state.get("queue_preview", [])
    depths = state.get("queue_preview_depths", [])
    saved_queue = list(zip(urls, depths))
```

**Confirmed resolved**: ✅

---

### Issue 2 — Search: Scanning All Files for Every Query (Medium)

**File**: `search_service.py`  
**Finding**: The initial implementation iterated over all 26 letter files for every query, regardless of which letters appeared in the query tokens.

**Feedback to Search Agent**:
> A search for "python" should only scan `p.data`. The current implementation opens all 26 files and checks every record. Add a bucket routing step: group tokens by their first letter and only open the files for those letters.

**Fix applied**:
```python
buckets: dict[str, list[str]] = defaultdict(list)
for token in tokens:
    if token[0].isalpha():
        buckets[token[0].lower()].append(token)

for letter, words in buckets.items():
    # only scan files for letters that appear in the query
    ...
```

**Confirmed resolved**: ✅

---

### Issue 3 — Crawler: `visited_global` Not Re-Read Atomically (Medium)

**File**: `crawler.py`, main crawl loop  
**Finding**: The visited set was read once at crawler start. In a multi-crawler scenario, URLs discovered by crawler B after crawler A's startup would not be in A's visited set, potentially causing both to crawl the same URL.

**Feedback to Crawler Agent**:
> `visited_global` is read once at `_run()` start. If two crawlers are running and crawler B crawls URL X after crawler A started, A will not see X in its visited set and may crawl it again. Re-read `visited_urls.data` before each URL pop, under `_VISITED_LOCK`.

**Fix applied**:
```python
with _VISITED_LOCK:
    visited_global = _read_visited()
if url in visited_global:
    continue
```

**Confirmed resolved**: ✅

---

### Issue 4 — Storage: `.tmp` File Left on Disk After Crash (Low)

**File**: `crawler.py`, `_save_crawler_state()`  
**Finding**: If the process crashes between `open(tmp, "w")` and `os.replace(tmp, path)`, a `.data.tmp` file is left on disk. `list_all_crawlers()` only lists `.data` files, so the orphan is harmless, but it wastes disk space and is confusing.

**Feedback to Storage Agent**:
> Document this behavior in `recommendation.md` as a known limitation. A production implementation should add a startup cleanup pass that deletes any `.data.tmp` files found in `data/crawlers/`. No code change needed for this prototype, but it should be acknowledged.

**Action taken**: Added to `recommendation.md` Known Limitations section.

**Confirmed resolved**: ✅ (documented)

---

### Issue 5 — Search: Partial JSON Line at EOF Not Handled (Critical)

**File**: `search_service.py`  
**Finding**: If `search_service.py` reads a letter file while the indexer is mid-write, the last line may be incomplete JSON. Without a `try/except`, `json.loads()` would raise `JSONDecodeError` and abort the entire search.

**Feedback to Search Agent**:
> Add `try/except json.JSONDecodeError: continue` inside the per-line loop. An incomplete final line is expected during concurrent write; it is safe to skip.

**Fix applied**:
```python
try:
    entry = json.loads(line)
except json.JSONDecodeError:
    continue
```

**Confirmed resolved**: ✅

---

### Issue 6 — UI: No Visual Indicator for Back-Pressure (Low)

**File**: `demo/status.html`  
**Finding**: The `[BACKPRESSURE]` log entries were displayed in the same style as normal log entries. Users could miss them if the log was scrolled.

**Feedback to UI Agent**:
> Color `[BACKPRESSURE]` log lines distinctly (orange or red). Add a queue depth progress bar that turns red when queue depth exceeds 80% of `queue_capacity`. This makes the back-pressure state immediately visible without reading the logs.

**Action taken**: Implemented in `demo/status.html`.

**Confirmed resolved**: ✅

---

## Evaluation Report Summary

| Issue | Agent | Severity | Status |
|-------|-------|----------|--------|
| Full queue not saved in resume | Crawler Agent | Critical | ✅ Fixed |
| Search scans all 26 files for every query | Search Agent | Medium | ✅ Fixed |
| visited_global not re-read per iteration | Crawler Agent | Medium | ✅ Fixed |
| .tmp orphan files on crash | Storage Agent | Low | ✅ Documented |
| Partial JSON line crashes search | Search Agent | Critical | ✅ Fixed |
| No visual back-pressure indicator | UI Agent | Low | ✅ Fixed |

---

## Outputs Produced

- Inline feedback to each agent (reproduced above)
- This evaluation report (`agents/evaluation_agent.md`)
- Verification confirmations after each fix
