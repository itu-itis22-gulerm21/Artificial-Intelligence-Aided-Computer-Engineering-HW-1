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
- Reads `data/visited_urls.data` on initialization to skip already-crawled URLs
- Fetches HTML via `urllib` with a permissive SSL context
- Parses links and body text using Python's native `html.parser`
- Stores word frequencies to `data/storage/{letter}.data` in JSON-lines format
- Marks each URL visited atomically after processing
- Back-pressure: when queue depth reaches capacity, the crawler pauses and waits before resuming
- Supports full lifecycle control: pause, resume, and stop

---

### 2. Search

**Input:** `query` (string)
**Output:** A ranked list of triples in the form `(relevant_url, origin_url, depth)`

**Relevance:** Results are ranked by the sum of per-word frequencies across all matched query terms. Pages that match more terms, or contain them at higher frequency, rank higher.

**Concurrency:** The search component reads directly from the letter-bucket storage files. Because the indexer appends to these files under per-letter locks, search results reflect the current state of the index at query time without requiring a separate sync step.

---

## User Interface

### `/crawler` — Create & Monitor

- System stats bar: total URLs visited, words indexed, active crawlers, total jobs created
- Crawl submission form: origin URL, max depth, hit rate, queue capacity, max URLs
- Confirmation banner with job ID and direct link to the status page
- Live list of recent crawler jobs with pause, resume, and stop controls

### `/status?id=<crawlerId>` — Crawler Status

- Auto-refreshes every 3 seconds
- Displays: origin, depth, hit rate, URLs visited, queue depth, start time, last update
- Queue preview showing the next 50 pending URLs with their depth
- Scrollable log viewer (last 500 entries)
- Job controls: Pause, Resume, Stop
- Downloadable queue and log exports

### `/search?q=<query>` — Search Interface

- Search input with query submission
- Results display: URL, matched keyword, frequency, crawl depth, origin URL
- Paginated output (20 results per page)
- "I'm Feeling Lucky" shortcut — opens the top result directly

---

## Non-Functional Requirements

| Requirement | Implementation |
|-------------|----------------|
| No external database | File-system only (`data/` directory) |
| Concurrency-safe writes | Per-letter `threading.Lock` on all storage files |
| Visited URL deduplication | Append-only `visited_urls.data`, checked before each fetch |
| Resume after restart | Persistent queue and visited-URL state survives process restarts |
| Back-pressure | Queue capacity gate combined with configurable request rate |
| Standard library only | `urllib`, `html.parser`, `threading` — no Scrapy, BeautifulSoup, or Playwright |

---

## Out of Scope — Version 1

The following capabilities are recognized as valuable but are deferred to future iterations in the interest of delivering a focused, well-tested v1:

- Robots.txt compliance and crawl-delay directives
- JavaScript rendering for dynamically generated content
- Distributed or multi-machine crawl coordination
- Authentication-gated or session-protected pages
- Incremental re-crawling and content TTL expiry
