# 🕷️ Brightwave Crawler

> A self-contained web crawler and keyword search engine — no database required.  
> Built using an 8-agent multi-agent AI workflow.

Brightwave Crawler lets you point it at any website, crawl it to a configurable depth, and search through everything it found — all from a clean browser interface. It is written entirely in Python using the standard library (no Scrapy, no BeautifulSoup), stores everything as plain files on disk, and can run multiple crawl jobs simultaneously.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation & Quick Start](#installation--quick-start)
- [Using the Interface](#using-the-interface)
- [Crawl Parameters Explained](#crawl-parameters-explained)
- [How Storage Works](#how-storage-works)
- [Back-Pressure & Rate Limiting](#back-pressure--rate-limiting)
- [Resume After Interruption](#resume-after-interruption)
- [Multi-Agent Workflow](#multi-agent-workflow)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Known Limitations](#known-limitations)

---

## How It Works

```
You give it a URL
        ↓
Brightwave fetches the page (using Python's urllib)
        ↓
It extracts all the text and all the links on that page
        ↓
Words are saved to disk, indexed by their first letter (a.data, b.data, …)
        ↓
Links found on the page are added to the queue
        ↓
The process repeats for every link, up to the depth limit you set
        ↓
Search queries scan those letter files and return ranked results instantly
```

Everything runs in the background in its own thread. You can start multiple crawl jobs at the same time, pause or stop them individually, and search the index at any point — even while crawling is still in progress.

---

## Prerequisites

- Python 3.10 or newer
- pip

That's it. No database, no Docker, no external services.

---

## Installation & Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/itu-itis22-gulerm21/Artificial-Intelligence-Aided-Computer-Engineering-HW-1
cd Artificial-Intelligence-Aided-Computer-Engineering-HW-1

# 2. Install dependencies
pip install flask flask-cors

# 3. Start the server
python app.py

# 4. Open your browser
# Go to: http://localhost:5000
```

The server starts on port 5000. All three pages of the interface are available immediately.

---

## Using the Interface

### 1. Create a Crawler — `/crawler`

Enter a URL and click **Start Crawling**.

| Field | What it does | Default |
|-------|-------------|---------|
| **Origin URL** | The website to start crawling from | *(required)* |
| **Max Depth** | How many link-hops away from the origin to crawl | 3 |
| **Hit Rate** | Pages to fetch per second | 1.0 |
| **Queue Capacity** | Maximum URLs to hold in the pending queue at once | 10,000 |
| **Max URLs** | Hard stop — crawler stops after visiting this many pages | 100 |

After starting, you'll see a confirmation banner with your **Crawler ID** and a link to its status page.

### 2. Monitor a Crawl — `/status?id=<id>`

Auto-refreshes every 3 seconds and shows:

- **Live metrics** — pages visited, queue depth, start time, last activity
- **Queue preview** — the next 50 URLs waiting to be crawled, with their depth
- **Full log** — every action the crawler has taken, in order
- **Controls** — Pause, Resume, Stop buttons
- **Downloads** — export the current queue or full log as a text file

### 3. Search — `/search?q=<query>`

Results are returned as triples: `(matched URL, origin URL, depth)`

Results are ranked by **keyword frequency** — pages where your search term appears more often rank higher. Multi-word queries rank pages that match more terms higher.

- Minimum word length is 2 characters
- Common words (the, and, is, etc.) are filtered automatically
- **I'm Feeling Lucky** opens the top result directly in a new tab
- Results paginate at 20 per page
- **Prefix search** is supported — searching `"wiki"` matches pages containing `"wikipedia"`, `"wikimedia"`, etc.

---

## Crawl Parameters Explained

### Depth

```
Depth 0:  https://example.com  (origin only)
Depth 1:  https://example.com/about
          https://example.com/contact    (pages linked from origin)
Depth 2:  https://example.com/blog/post-1  (pages linked from depth-1 pages)
```

### Hit Rate

Politeness setting. `1.0` = one page per second. Setting it very high may cause target servers to block your crawler (HTTP 429 or 403).

### Max URLs

A safety ceiling. The crawler stops after visiting this many pages, even if the queue still has URLs.

---

## How Storage Works

All data is saved in the `data/` directory as plain text files. No database is required.

```
data/
├── visited_urls.data        ← one URL per line; prevents crawling the same page twice
├── storage/
│   ├── a.data               ← all indexed words starting with "a"
│   ├── b.data
│   └── ...                  ← one file per letter of the alphabet
└── crawlers/
    └── <crawler_id>.data    ← JSON state for each crawl job
```

Each line in a word storage file:

```json
{"word": "starbucks", "url": "https://www.starbucks.com/menu", "origin": "https://www.starbucks.com", "depth": 1, "freq": 14}
```

This design means:
- **Search is fast** — a query for "s..." only reads `s.data`
- **Multiple crawlers write simultaneously** — each letter file has its own lock
- **Search works during active crawling** — files are appended to, not rewritten

---

## Back-Pressure & Rate Limiting

Two independent mechanisms:

**1. Hit Rate Limiting** — a configurable delay between requests (`1 / hit_rate` seconds). At the default of 1.0 req/sec, the crawler waits 1 second between page fetches.

**2. Queue Capacity Gate** — if the number of pending URLs exceeds `queue_capacity`, the crawler pauses and waits 2 seconds before checking again. Prevents unbounded memory growth when crawling very large sites. You'll see `[BACKPRESSURE]` in the logs when this kicks in, and the status page highlights these entries in orange.

---

## Resume After Interruption

If the server restarts or crashes, crawl jobs are not lost:

- **Automatic resume on startup** — any job that was `active` or `paused` when the server stopped will be automatically restarted when you run `python app.py` again
- **Visited URLs persist** — `data/visited_urls.data` is never deleted on restart, so already-crawled pages are always skipped
- **Full queue preserved** — the complete pending URL queue is saved to disk on every iteration, not just a preview

---

## Multi-Agent Workflow

This project was built using an **8-agent multi-agent AI workflow**. Each agent had a distinct responsibility:

| Agent | Responsibility | Output |
|-------|---------------|--------|
| Architect Agent | System design, PRD, API surface | `product_prd.md` |
| Storage Agent | File I/O, locking primitives, resume logic | Storage layer in `crawler.py` |
| Crawler Agent | BFS engine, depth control, back-pressure | `crawler.py` |
| Indexer Agent | HTML parsing, word extraction, stopwords | Text pipeline in `crawler.py` |
| Search Agent | Query engine, relevance scoring | `search_service.py` |
| UI/CLI Agent | Flask API, three HTML pages, long-poll | `app.py`, `demo/` |
| Evaluation Agent | Code review, bug finding, feedback loops | `PRD/evaluation_agent.md` |
| Documentation Agent | README, recommendation, agent docs | This file |

The agent team infrastructure is in `agent_team/` — a working Python implementation of the shared task list and mailbox (direct agent-to-agent messaging) used during development.

See `multi_agent_workflow.md` for the full workflow description and `PRD/` for each agent's prompt and decisions.

---

## API Reference

All responses are JSON.

### Crawlers

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/crawl` | Start a new crawl job |
| `GET` | `/api/crawlers` | List all crawl jobs |
| `GET` | `/api/crawlers/<id>` | Get full state of a specific crawler |
| `POST` | `/api/crawlers/<id>/pause` | Pause a running crawler |
| `POST` | `/api/crawlers/<id>/resume` | Resume a paused crawler |
| `POST` | `/api/crawlers/<id>/stop` | Stop a crawler permanently |
| `GET` | `/api/crawlers/<id>/poll?last_log=<n>` | Long-poll for live updates |

### Search & Stats

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/search?q=<query>` | Search the index |
| `GET` | `/api/stats` | System-wide stats |
| `POST` | `/api/clear` | Delete all crawled data |

### Example: Start a Crawl

```bash
curl -X POST http://localhost:5000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "https://en.wikipedia.org/wiki/Main_Page",
    "max_depth": 2,
    "hit_rate": 1.0,
    "queue_capacity": 10000,
    "max_urls": 50
  }'
```

### Example: Search

```bash
curl "http://localhost:5000/api/search?q=machine+learning&page=1&per_page=20"
```

---

## Project Structure

```
brightwave-crawler/
├── app.py                   ← Flask web server and API routes
├── crawler.py               ← Core crawl engine (fetching, parsing, indexing, threading)
├── search_service.py        ← Search logic (tokenization, file scanning, ranking)
├── stopwords.py             ← Common words excluded from indexing
├── requirements.txt         ← Python dependencies (flask, flask-cors only)
├── demo/
│   ├── crawler.html         ← Create Crawler page
│   ├── status.html          ← Crawler Status page
│   └── search.html          ← Search page
├── data/                    ← All runtime data (created automatically)
│   ├── visited_urls.data
│   ├── storage/
│   └── crawlers/
├── agent_team/              ← Multi-agent workflow infrastructure
│   ├── agent_team.py        ← Orchestrator (requires ANTHROPIC_API_KEY)
│   ├── task_list.py         ← Shared task list with file locking
│   └── mailbox.py           ← Direct agent-to-agent messaging
├── PRD/                     ← Agent descriptions and prompts
│   ├── multi_agent_workflow.md
│   ├── architect_agent.md
│   └── ...
├── product_prd.md           ← Product Requirements Document
├── recommendation.md        ← Production deployment recommendations
└── multi_agent_workflow.md  ← Multi-agent workflow summary
```

---

## Known Limitations

- **No JavaScript rendering** — single-page apps appear empty to the crawler
- **No robots.txt support** — crawl-delay directives are not respected
- **No per-domain rate limiting** — hit rate applies globally, not per host
- **Single machine only** — not horizontally distributed
- **`.tmp` orphan files** — if the process crashes mid-write, a `.data.tmp` file may remain in `data/crawlers/`; harmless but requires manual cleanup
