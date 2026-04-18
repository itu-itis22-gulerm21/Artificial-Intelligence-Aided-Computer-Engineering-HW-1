# Agent 2 — Crawler Agent

## Role & Responsibility

The Crawler Agent was responsible for implementing the core crawl engine. It received the Architect Agent's technical specification and produced `crawler.py` — the component that fetches pages, manages the BFS queue, enforces depth limits, deduplicates URLs, applies back-pressure, and persists state.

---

## Prompt Given to This Agent

```
You are an expert Python engineer implementing a web crawler. Work from the following technical specification:

Storage layout:
- data/visited_urls.data — append-only, one URL per line, protected by a threading.Lock
- data/crawlers/{crawlerId}.data — JSON file with full crawler job state, written atomically via os.replace()
- data/storage/{letter}.data — word-frequency records (handled by the Indexer Agent, not you)

Your deliverable is crawler.py. It must implement:

1. CrawlerJob class:
   - __init__(origin, max_depth, hit_rate, queue_capacity, max_urls)
   - start() → returns crawler_id (format: {epoch}_{thread_id})
   - pause(), resume(), stop()
   - BFS queue: list of (url, depth) tuples
   - On each iteration: check back-pressure → check pause → check stop → check max_urls → pop URL → check visited → fetch → parse → store words → enqueue new links → sleep(1/hit_rate)
   - Back-pressure: when len(queue) >= queue_capacity, sleep 2s and log [BACKPRESSURE]
   - Atomic state flush: write to .tmp, then os.replace()

2. Module-level functions:
   - start_crawler(origin, max_depth, hit_rate, queue_capacity, max_urls) → crawler_id
   - get_crawler(crawler_id) → CrawlerJob | None
   - resume_crawler(crawler_id) → crawler_id | None (restores from disk)
   - load_crawler_state(crawler_id) → dict | None
   - list_all_crawlers() → list[dict]
   - get_stats() → dict with urls_visited, words_in_db, active_crawlers, total_created
   - clear_all_data()

3. HTML fetching:
   - Use urllib.request only (no requests library)
   - Permissive SSL context (check_hostname=False, CERT_NONE) — educational project
   - User-Agent: "BrightwaveCrawler/1.0 (educational project)"
   - Return (status_code, html_content)
   - On HTTPError: return (error_code, "")
   - On any other exception: return (0, "")

4. HTML parsing:
   - Use html.parser (stdlib only, no BeautifulSoup)
   - Extract all <a href> links, normalize to absolute URLs, strip fragments
   - Skip content inside <script>, <style>, <noscript>, <head> tags
   - Collect visible text for word extraction

5. Visited URL deduplication:
   - Read visited_urls.data once at crawler start into a local set
   - Re-read before each URL pop to catch URLs added by other concurrent crawlers
   - Append new URL to visited_urls.data atomically under _VISITED_LOCK after processing

6. Resume behavior:
   - resume_crawler() reads the state file, reconstructs a CrawlerJob, restores queue and logs, then starts the thread
   - The restored job uses the original crawler_id, not a new one

Use only Python standard library. Do not import requests, scrapy, beautifulsoup4, or any third-party parsing library.
```

---

## Key Implementation Decisions

### BFS Queue as In-Memory List

The Crawler Agent implemented the queue as a plain Python list of `(url, depth)` tuples, persisted to the crawler's JSON state file on every `_flush()` call. The alternative — a `collections.deque` — was rejected because deque does not support slicing for the queue preview feature, and the performance difference at queue depths under 10,000 is negligible.

### Thread-Per-Job Model

Each `CrawlerJob` runs in its own daemon thread. The `_crawlers` dict maps `crawler_id → CrawlerJob` and is protected by `_crawlers_lock`. The Crawler Agent considered an async approach (asyncio + aiohttp) but rejected it because: (a) it would require a third-party library for HTTP, and (b) threading is simpler to pause/resume — setting `_pause_event` causes the thread to spin on `event.is_set()` without any async machinery.

### `_id_ready` Synchronization

The `start()` method creates the thread and then blocks on a `threading.Event` until the thread has computed its real OS thread ID and written its state file. This prevents a race where `start()` returns a `crawler_id` before the state file exists on disk — which would cause `load_crawler_state()` to return `None` if called immediately after `start()`.

```python
def start(self) -> str:
    _id_ready = threading.Event()
    self._thread = threading.Thread(target=self._run, args=(_id_ready,), daemon=True)
    self._thread.start()
    _id_ready.wait()  # block until thread has set self.crawler_id
    return self.crawler_id
```

### Visited URL Re-Read Per Iteration

The visited set is read from disk at crawler start into `visited_global`, then re-read before each URL is processed. This is intentionally conservative: it means that if two crawler jobs are running simultaneously and both discover the same URL, the second to process it will see it already in `visited_urls.data` and skip it. The cost is one file read per URL pop, which is acceptable because `visited_urls.data` is an append-only text file and reads are fast.

### Non-200 Handling

The Crawler Agent implemented asymmetric non-200 behavior:
- If the **origin URL** returns non-200: log the error and stop the entire crawler job. An unreachable origin means the job is pointless.
- If a **discovered link** returns non-200: mark it visited (so it is not retried), log the error, and continue. One bad link should not abort a crawl that may have thousands of other valid URLs.

### Atomic State Write

```python
def _save_crawler_state(state: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)  # atomic on POSIX
```

`os.replace()` is atomic on POSIX systems. This prevents the status page from reading a half-written JSON file during a flush.

---

## Interactions with Other Agents

- **Receives from Architect Agent**: storage layout, concurrency constraints, back-pressure thresholds
- **Sends to Indexer Agent**: extracted text and word frequencies via `_store_words()` (the Indexer Agent's logic was merged into `crawler.py` by the Evaluation Agent — see that agent's report)
- **Sends to Storage Agent**: `_flush()` writes JSON state that the Storage Agent's resume logic depends on
- **Receives from Evaluation Agent**: bug report on visited-URL check ordering (fixed in final version)

---

## Outputs Produced

- `crawler.py` — complete crawler engine
  - `CrawlerJob` class with full lifecycle management
  - `LinkParser` (HTML parser)
  - `fetch_url()`, `extract_words()`, `_store_words()`
  - State persistence and resume functions
  - `get_stats()` and `clear_all_data()`
