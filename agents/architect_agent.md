# Agent 1 — Architect Agent

## Role & Responsibility

The Architect Agent was the first agent activated in the workflow. Its job was to translate the project requirements into a concrete technical blueprint before any code was written. It owned the system design: what components exist, how they communicate, what the data model looks like, and what constraints the other agents must respect.

---

## Prompt Given to This Agent

```
You are a senior software architect. Read the following project requirements carefully and produce a complete technical design for a single-machine web crawler and search system.

Requirements:
- index(origin, k): crawl from origin URL up to depth k, never visiting the same URL twice
- search(query): return (relevant_url, origin_url, depth) triples ranked by relevance
- back-pressure: system must manage load in a controlled way (max rate, max queue depth)
- search must work while indexing is active (concurrent reads and writes)
- resume after interruption: system should recover without starting from scratch
- standard library only: no Scrapy, no BeautifulSoup, no external search frameworks
- simple UI or CLI to start indexing, run searches, and view system state

Produce:
1. A component list with clear boundaries of responsibility for each component
2. A storage design: what data is stored, in what format, where on disk
3. A concurrency model: how the crawler and search coexist safely
4. A back-pressure design: specific mechanism with thresholds
5. A resume design: what is persisted and how recovery works
6. API surface: what endpoints the UI will call

Do not write code. Produce a written technical specification only.
```

---

## Key Decisions Made

### Component Boundaries

The Architect Agent split the system into four distinct components with hard boundaries:

1. **Crawler Engine** (`crawler.py`) — fetching, parsing, BFS queue, depth tracking, back-pressure, visited-URL deduplication, word extraction, and state persistence. This component is intentionally monolithic because all of these concerns operate on the same shared state (the queue and the visited set) and splitting them across modules would introduce unnecessary synchronization complexity.

2. **Search Service** (`search_service.py`) — query tokenization, letter-bucket file scanning, relevance scoring, and result pagination. Strictly read-only: it never writes to the index. This boundary is what makes concurrent search safe — no locking is required on the search side.

3. **Storage Layer** (file system under `data/`) — the Architect Agent chose a file-based approach over SQLite or an in-memory store after evaluating the access patterns: the index is append-only (no updates, no deletes), search reads are sequential scans of a subset of files, and crawler state is a single JSON document per job. A database would add a dependency and transactional complexity without a meaningful performance benefit at this scale.

4. **API + UI** (`app.py` + `demo/`) — a thin Flask layer that glues the crawler engine and search service to a browser interface. The API is stateless; all state lives in the crawler engine and on disk.

### Storage Design

```
data/
├── visited_urls.data          — append-only, one URL per line
├── storage/
│   ├── a.data                 — JSON-lines, one word-frequency record per line
│   ├── b.data
│   └── ...z.data
└── crawlers/
    └── {epoch}_{thread_id}.data  — JSON, full crawler job state
```

The letter-bucket split was the Architect Agent's central indexing decision. It partitions the search space so that a query for a word beginning with "s" only reads `s.data`, not the entire index. It also allows the indexer to write to 26 independent files with per-letter locks, enabling concurrent writes from multiple crawler jobs without contention between jobs writing different letters.

### Concurrency Model

- One `threading.Thread` per crawler job (daemon thread)
- One `threading.Lock` per letter-bucket file (`_STORAGE_LOCKS`)
- One `threading.Lock` for `visited_urls.data` (`_VISITED_LOCK`)
- Search holds no locks — it opens files in read mode and reads sequentially; because the indexer only appends, a search that starts mid-write at worst sees a partial final line, which is skipped via `json.JSONDecodeError` handling

### Back-Pressure Design

Two independent mechanisms:
1. **Rate limiting**: `delay = 1.0 / hit_rate` seconds between fetches, configurable per job
2. **Queue capacity gate**: when `len(queue) >= queue_capacity`, the crawler thread sleeps 2 seconds and logs `[BACKPRESSURE]` before checking again

The Architect Agent specified that these two mechanisms must be independently configurable because they address different failure modes: rate limiting protects the target server; queue capacity protects the crawling machine's memory.

### Resume Design

Every state change flushes the crawler's full state to `{crawlerId}.data` via an atomic `os.replace(tmp, path)` pattern. On startup, `app.py` calls `_auto_resume_on_startup()`, which scans all crawler state files and re-launches any job whose status was `active` or `paused`. The visited-URL file is never deleted, so already-crawled URLs are always skipped.

---

## Outputs Produced

- `product_prd.md` — the PRD that other agents implemented against
- Component list and storage schema (communicated to Crawler Agent, Indexer Agent, Storage Agent)
- API surface definition (communicated to UI Agent)
- Concurrency constraints (communicated to Crawler Agent and Search Agent)
