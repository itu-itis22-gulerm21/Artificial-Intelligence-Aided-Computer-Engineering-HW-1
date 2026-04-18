# Agent 5 — Storage Agent

## Role & Responsibility

The Storage Agent was responsible for designing and implementing the entire data persistence layer. Rather than choosing a database, the Storage Agent designed a file-based storage system tailored to the access patterns of this specific application. It also owned the resume-after-interruption mechanism.

---

## Prompt Given to This Agent

```
You are a storage systems engineer. Design and implement the persistence layer for a web crawler and search engine that must run entirely on localhost with no external database.

Access patterns to support:
1. visited_urls.data — write: append one URL per crawl iteration (high frequency, concurrent crawlers); read: full scan at crawler startup
2. storage/{letter}.data — write: append multiple JSON records per crawl iteration (26 independent files); read: full sequential scan per search query
3. crawlers/{id}.data — write: full JSON rewrite on every state change; read: on demand by API and on startup for resume

Requirements:
- No SQLite, no external DB — plain filesystem only
- Thread-safe: multiple crawler jobs may run concurrently
- Atomic writes: partial state files must never be visible to readers
- Resume after interruption: define what is persisted and how recovery works
- Implement: all file I/O helpers, locking primitives, and the resume logic

Justify each storage format choice relative to the alternatives you considered.
```

---

## Design Decisions and Justifications

### Why Not SQLite?

The Storage Agent evaluated SQLite as the primary storage backend and rejected it for the following reasons:

| Concern | Detail |
|---------|--------|
| **WAL mode required** | Without WAL, SQLite uses exclusive write locks that would serialize all crawler writes. WAL mode requires configuration and adds a `.wal` and `.shm` file. |
| **Schema migration** | Any change to the word record format requires an `ALTER TABLE`. The JSON-lines format is schema-flexible. |
| **Search access pattern** | Search scans records for a specific first letter. In SQLite this would be `WHERE word LIKE 'a%'` — a full table scan anyway without an index, or an index that duplicates storage. The letter-bucket files achieve the same partition natively. |
| **Standard library** | `sqlite3` is part of the standard library, so it would not violate the project constraint. But it adds no benefit over the file-based approach for this access pattern. |

### `visited_urls.data` — Append-Only Text File

**Format**: one URL per line, UTF-8  
**Write**: under `_VISITED_LOCK` (`threading.Lock`), append mode  
**Read**: full scan into a Python `set` at crawler startup; re-read before each URL pop

The Storage Agent chose an append-only text file over a set persisted as JSON for two reasons:
1. Appending a single line is O(1) and does not require reading the existing file
2. JSON serialization of a large set requires reading, deserializing, adding the new entry, re-serializing, and writing — O(n) per write

Trade-off: the file grows unboundedly and is never compacted. For the scale of this project (tens of thousands of URLs), this is not a problem. At millions of URLs, a Bloom filter or a compact binary format would be appropriate (noted in `recommendation.md`).

### `storage/{letter}.data` — JSON-Lines, Per-Letter Bucket

**Format**: one JSON object per line  
**Write**: under `_STORAGE_LOCKS[letter]` (`defaultdict(threading.Lock)`), append mode  
**Read**: sequential full scan, no lock (append-safe)

The letter-bucket partition is the Storage Agent's central design contribution. It provides:

- **Search locality**: a query for "python" only reads `p.data`, not all 26 files
- **Write parallelism**: 26 independent locks mean two crawlers writing words starting with different letters never contend with each other
- **Append safety for concurrent reads**: because the indexer only appends and never truncates, a reader that opens the file mid-write sees complete lines up to the point of its `open()` call, then reads to EOF. The last line may be incomplete if a write is in progress — handled by `json.JSONDecodeError` in `search_service.py`

### `crawlers/{id}.data` — Atomic JSON Rewrite

**Format**: single JSON document  
**Write**: write to `.tmp`, then `os.replace()` (atomic on POSIX)  
**Read**: `json.load()` on demand

```python
def _save_crawler_state(state: dict):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)  # atomic rename — readers never see partial state
```

`os.replace()` is a POSIX rename, which is guaranteed atomic. A reader either sees the old complete file or the new complete file — never a file being written. This is critical because the status page reads crawler state every 3 seconds while the crawler is writing it on every URL fetch.

### Resume After Interruption

The resume mechanism the Storage Agent designed has three parts:

**1. What is persisted on every `_flush()`:**
```json
{
  "id": "1774252574_5028",
  "status": "active",
  "origin": "https://example.com",
  "max_depth": 3,
  "queue": [["https://example.com/page", 1], ...],
  "urls_visited": ["https://example.com", ...],
  "urls_visited_count": 47,
  "logs": ["2026-03-23 11:51:00 - Crawling https://..."],
  "started_at": "2026-03-23T11:51:00",
  "last_update": "2026-03-23T11:51:30"
}
```

**2. What is NOT re-derived on resume:**
- `visited_urls.data` is persistent and never deleted — already-crawled URLs are always skipped
- The word index (`storage/*.data`) is persistent — words from pre-interruption pages are already in the index and do not need to be re-crawled

**3. Recovery on startup:**
```python
def _auto_resume_on_startup():
    for state in list_all_crawlers():
        if state["status"] in ("active", "paused"):
            resume_crawler(state["id"])
```

`resume_crawler()` reads the state file, reconstructs a `CrawlerJob`, restores the saved queue, and starts the thread. Because `visited_urls.data` is persistent, the restored crawler picks up exactly where it left off without re-crawling any page.

---

## Interactions with Other Agents

- **Receives from Architect Agent**: storage layout specification, atomicity requirements
- **Sends to Crawler Agent**: `_VISITED_LOCK`, `_STORAGE_LOCKS`, `_save_crawler_state()`, `_mark_visited()`, `_read_visited()`
- **Sends to Search Agent**: letter-bucket files (append-only, JSON-lines)
- **Sends to UI Agent**: crawler state JSON schema (consumed by `/api/crawlers/<id>`)
- **Receives from Evaluation Agent**: review of atomicity guarantees and resume correctness

---

## Outputs Produced

- Storage design (integrated into `crawler.py`):
  - `_VISITED_LOCK`, `_STORAGE_LOCKS` — threading primitives
  - `_read_visited()`, `_mark_visited()` — visited URL management
  - `_save_crawler_state()`, `load_crawler_state()`, `list_all_crawlers()` — crawler state persistence
  - `resume_crawler()` — restoration from disk
  - `_auto_resume_on_startup()` (in `app.py`) — startup recovery
  - `clear_all_data()` — full reset
