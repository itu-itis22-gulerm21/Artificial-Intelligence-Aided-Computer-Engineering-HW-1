# Product Requirements Document
## Brightwave Crawler — Web Indexer & Search Engine

## Overview

Brightwave Crawler is a self-contained web indexing and search engine designed to run on a single machine without external dependencies. Given an origin URL and a configurable crawl depth, it recursively fetches and indexes web pages, storing word-frequency data in a file-based key-value store. A keyword search interface is exposed concurrently alongside the indexer, allowing queries to reflect newly discovered content in real time. The system is implemented entirely using Python's standard library, with no reliance on third-party crawling or parsing frameworks.

---

## Core Components

### 1. Indexer (Crawler Job)

**Inputs:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `origin` | URL | required | Starting URL for the crawl |
| `max_depth` | int | 3 | Maximum hops from the origin |
| `hit_rate` | float | 1.0 | Requests per second |
| `queue_capacity` | int | 10,000 | Back-pressure limit on the pending queue |
| `max_urls` | int | 100 | Hard cap on total pages visited per job |

**Behavior:**
- Each job runs in its own daemon thread; multiple jobs may run concurrently
- Crawler ID format: `{epoch_created}_{thread_id}`
- State file written immediately on start: `data/crawlers/{crawlerId}.data`
- Reads `data/visited_urls.data` on initialization to skip already-crawled URLs; re-reads before each URL pop to catch URLs added by concurrent crawlers
- Fetches HTML via `urllib` with a permissive SSL context and a `BrightwaveCrawler/1.0` User-Agent header
- Parses links and body text using Python's native `html.parser`; skips content inside `<script>`, `<style>`, `<noscript>`, and `<head>` tags
- Stores word frequencies to `data/storage/{letter}.data` in JSON-lines format under per-letter threading locks
- Marks each URL visited atomically after processing
- Back-pressure: when queue depth reaches `queue_capacity`, the crawler sleeps 2 seconds and logs `[BACKPRESSURE]` before resuming
- Supports full lifecycle control: pause, resume, and stop
- State is flushed atomically to disk on every iteration via `os.replace()` — enables resume after interruption

**URL handling:**
- Absolute URLs only; relative URLs normalized via `urllib.parse.urljoin`
- URL fragments stripped before storage
- Non-200 responses: mark URL visited and continue; if the *origin* URL returns non-200, stop the crawler entirely

---

### 2. Search

**Input:** `query` (string)
**Output:** A paginated, ranked list of result objects, each containing:
```json
{
  "url": "https://example.com/page",
  "origin": "https://example.com",
  "depth": 2,
  "relevance_score": 1045,
  "word": "python",
  "frequency": 8
}
```

**Relevance scoring:**
```
score = (freq × 10) + (1000 if exact match) − (depth × 5)
```
- Scores aggregated per URL across all matched query tokens
- Prefix matching supported: query token `"wiki"` matches stored words `"wikipedia"`, `"wikimedia"`, etc.
- Exact match bonus (1000 points) ensures exact matches always outrank prefix matches at similar frequency

**Tokenization:** Extract `[a-zA-Z]{2,}` tokens, lowercase, filter stopwords (defined in `stopwords.py`)

**Concurrency:** Search reads letter-bucket files in read mode only, with no locks. Because the indexer only appends to these files, a search that starts mid-write at worst encounters a partial final line, which is skipped via `json.JSONDecodeError` handling.

**Pagination:** `page` and `per_page` parameters; default 20 results per page.

**Feeling Lucky:** Returns only the single top result.

---

### 3. Storage Layer

**File layout:**
```
data/
├── visited_urls.data          — append-only, one URL per line, UTF-8
├── storage/
│   ├── a.data                 — JSON-lines, one word-frequency record per line
│   ├── b.data
│   └── ...z.data
└── crawlers/
    └── {epoch}_{thread_id}.data  — JSON, full crawler job state
```

**Word record format:**
```json
{"word": "starbucks", "url": "https://...", "origin": "https://...", "depth": 1, "freq": 14}
```

**Crawler state format (key fields):**
```json
{
  "id": "1774252574_5028",
  "status": "active",
  "origin": "https://example.com",
  "max_depth": 3,
  "queue": [["https://example.com/page", 1]],
  "urls_visited_count": 47,
  "logs": ["2026-03-23 11:51:00 - Crawling https://..."],
  "started_at": "2026-03-23T11:51:00",
  "last_update": "2026-03-23T11:51:30"
}
```

**Locking:**
- `_VISITED_LOCK` (`threading.Lock`) — protects all reads and writes to `visited_urls.data`
- `_STORAGE_LOCKS` (`defaultdict(threading.Lock)`) — one lock per letter; protects each `{letter}.data` file independently

---

## User Interface

### `/crawler` — Create & Monitor

- System stats bar: total URLs visited, words indexed, active crawlers, total jobs created
- Crawl submission form: origin URL, max depth, hit rate, queue capacity, max URLs
- Confirmation banner with job ID and direct link to the status page
- Live list of recent crawler jobs with pause, resume, and stop controls

### `/status?id=<crawlerId>` — Crawler Status

- Auto-refreshes via long-poll (holds connection up to 25 seconds, returns on new log lines or terminal state)
- Displays: origin, depth, hit rate, URLs visited, queue depth, start time, last update
- Queue preview showing the next 50 pending URLs with their depth
- Scrollable log viewer (last 500 entries); `[BACKPRESSURE]` entries highlighted in orange
- Job controls: Pause, Resume, Stop
- Downloadable queue and log exports

### `/search?q=<query>` — Search Interface

- Search input with query submission
- Results display: URL, matched keyword, frequency, crawl depth, origin URL
- Paginated output (20 results per page)
- "I'm Feeling Lucky" shortcut — opens the top result directly

---

## API Surface

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/crawl` | Start a new crawl job |
| `GET` | `/api/crawlers` | List all crawl jobs |
| `GET` | `/api/crawlers/<id>` | Get full state of one job |
| `POST` | `/api/crawlers/<id>/pause` | Pause a running crawler |
| `POST` | `/api/crawlers/<id>/resume` | Resume a paused or interrupted crawler |
| `POST` | `/api/crawlers/<id>/stop` | Stop a crawler permanently |
| `GET` | `/api/crawlers/<id>/poll?last_log=<n>` | Long-poll for live state updates |
| `GET` | `/api/search?q=<query>&page=<n>&per_page=<n>&lucky=<bool>` | Search the index |
| `GET` | `/api/stats` | System-wide statistics |
| `POST` | `/api/clear` | Delete all crawled data and reset |

---

## Non-Functional Requirements

| Requirement | Implementation |
|-------------|----------------|
| No external database | File-system only (`data/` directory) |
| Concurrency-safe writes | Per-letter `threading.Lock` on all storage files |
| Visited URL deduplication | Append-only `visited_urls.data`, re-read before each fetch |
| Resume after restart | Full queue + visited-URL state survives process restarts |
| Back-pressure | Queue capacity gate + configurable request rate |
| Standard library only | `urllib`, `html.parser`, `threading` — no Scrapy, BeautifulSoup, or Playwright |
| Atomic state writes | `os.replace(tmp, path)` — readers never see partial state |

---

## Multi-Agent Workflow

This PRD was produced by the **Architect Agent** — the Team Lead of an 8-agent development workflow. The system was designed, implemented, evaluated, and documented by specialized agents communicating via a shared task list and direct mailbox messaging. See `multi_agent_workflow.md` for the full workflow description.

---

## Out of Scope — Version 1

- Robots.txt compliance and crawl-delay directives
- JavaScript rendering for dynamically generated content
- Distributed or multi-machine crawl coordination
- Authentication-gated or session-protected pages
- Incremental re-crawling and content TTL expiry
- Per-domain rate limiting
