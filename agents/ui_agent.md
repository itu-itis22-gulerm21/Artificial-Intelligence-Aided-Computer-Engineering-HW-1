# Agent 6 — UI/CLI Agent

## Role & Responsibility

The UI/CLI Agent was responsible for building the user-facing interface: the Flask API that wraps the crawler engine and search service, and the three browser-based HTML pages that let users start crawls, monitor progress, and search the index. The agent also implemented the long-polling mechanism that enables the status page to receive live updates without WebSockets.

---

## Prompt Given to This Agent

```
You are a frontend and API engineer. Build the UI layer for a web crawler and search engine.

Backend API to expose (implemented in app.py using Flask):
- POST /api/crawl — start a new crawl job
  Body: {origin, max_depth, hit_rate, queue_capacity, max_urls}
  Response: {crawler_id, status, origin}

- GET /api/crawlers — list all crawl jobs
- GET /api/crawlers/<id> — get full state of one job
- POST /api/crawlers/<id>/pause — pause a running crawler
- POST /api/crawlers/<id>/resume — resume a paused crawler
- POST /api/crawlers/<id>/stop — stop a crawler permanently

- GET /api/search?q=<query>&page=<n>&per_page=<n>&lucky=<bool>
- GET /api/stats — {urls_visited, words_in_db, active_crawlers, total_created}
- POST /api/clear — delete all crawled data

- GET /api/crawlers/<id>/poll?last_log=<n> — long-poll endpoint
  Holds connection open up to 25s, returns when new log lines appear

Three HTML pages (standalone, no build step, no npm):
1. /crawler (crawler.html) — create crawl + system stats + job list
2. /status?id=<id> (status.html) — live status for one job
3. /search?q=<query> (search.html) — search interface

Requirements:
- Each HTML page is self-contained (inline JS, no separate .js files)
- Auto-refresh: status page updates every 3 seconds
- Display back-pressure status when [BACKPRESSURE] appears in logs
- Show queue depth, URLs visited, and crawl progress
- Pause/Resume/Stop controls on the status page
- Search results show: URL, matched word, frequency, depth, origin
- Paginated results (20 per page)
- "I'm Feeling Lucky" button opens top result directly
- Queue and log export (download as text)
```

---

## Key Implementation Decisions

### Long Polling Over WebSockets

The UI Agent initially proposed WebSockets for live status updates. After review, long polling was chosen instead:

| Factor | WebSockets | Long Polling |
|--------|-----------|--------------|
| Flask support | Requires flask-socketio (extra dep) | Native Flask |
| Client complexity | More complex JS | Simple fetch loop |
| Resume after network gap | Requires reconnect logic | Inherent (each request is independent) |
| Standard library | No | Yes (just Flask) |

The long-poll endpoint holds connections for up to 25 seconds (safely below the 30-second browser/proxy timeout), then returns the current state so the client immediately re-connects. This gives sub-second update latency in practice.

```python
LONG_POLL_TIMEOUT  = 25   # seconds
LONG_POLL_INTERVAL = 0.5  # polling granularity

@app.route("/api/crawlers/<crawler_id>/poll")
def long_poll_crawler(crawler_id):
    deadline = _time.monotonic() + LONG_POLL_TIMEOUT
    while _time.monotonic() < deadline:
        state = crawler_engine.load_crawler_state(crawler_id)
        current_logs = state.get("logs", [])
        if len(current_logs) > last_log or state["status"] in ("finished", "stopped"):
            return jsonify({**state, "new_logs": current_logs[last_log:], "log_cursor": len(current_logs)})
        _time.sleep(LONG_POLL_INTERVAL)
    # timeout — return current state; client re-connects immediately
    return jsonify({...})
```

### Back-Pressure Visibility

The status page scans incoming log lines for the `[BACKPRESSURE]` marker and highlights them in a distinct color. The queue depth is displayed as a progress bar that turns red when it exceeds 80% of the configured capacity. This gives operators an immediate visual signal when the system is under load.

### Standalone HTML Pages

Each page is a single HTML file with all JavaScript inline. This was a deliberate choice to eliminate any build step (no npm, no Webpack, no Vite). The trade-off is that the JS is not modular or reusable, but for a three-page application this is acceptable.

### Queue and Log Export

The status page provides download buttons that trigger browser-side file creation:

```javascript
function downloadText(content, filename) {
    const blob = new Blob([content], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
}
```

The log content comes from the `/api/crawlers/<id>` response; the queue content comes from `queue_preview`. This requires no additional API endpoint.

### Auto-Resume on Startup

The UI Agent added the `_auto_resume_on_startup()` call to `app.py`'s `__main__` block. When the Flask server starts, it iterates over all crawler state files and re-launches any job that was `active` or `paused` when the server last stopped. This is transparent to the user — the status page shows the crawler as active immediately.

---

## Interactions with Other Agents

- **Receives from Architect Agent**: API surface definition, page requirements
- **Receives from Storage Agent**: crawler state JSON schema (drives the status page display)
- **Receives from Search Agent**: search response schema (drives the search results display)
- **Receives from Evaluation Agent**: usability feedback on status page — added back-pressure color coding and queue depth progress bar

---

## Outputs Produced

- `app.py` — Flask API with all endpoints, long-poll handler, and startup resume
- `demo/crawler.html` — create crawl page with stats and job list
- `demo/status.html` — live status page with log viewer, queue preview, controls, export
- `demo/search.html` — search interface with pagination and "I'm Feeling Lucky"
