"""
Brightwave Crawler - Core crawler engine
Handles crawling, word indexing, and state management using file-based storage.
"""

import threading
import time
import json
import os
import re
import ssl
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from html.parser import HTMLParser
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
STORAGE_DIR = os.path.join(DATA_DIR, "storage")
CRAWLERS_DIR = os.path.join(DATA_DIR, "crawlers")
VISITED_URLS_FILE = os.path.join(DATA_DIR, "visited_urls.data")

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(CRAWLERS_DIR, exist_ok=True)

# Global registry of active crawler threads
_crawlers: dict[str, "CrawlerJob"] = {}
_crawlers_lock = threading.Lock()

from stopwords import STOP_WORDS


class LinkParser(HTMLParser):
    """Extracts links and text from HTML."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self._skip_tags = {"script", "style", "noscript", "head"}
        self._current_skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._current_skip += 1
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            if href:
                full_url = urllib.parse.urljoin(self.base_url, href)
                parsed = urllib.parse.urlparse(full_url)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    # Normalize: strip fragment
                    clean = parsed._replace(fragment="").geturl()
                    self.links.append(clean)

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._current_skip > 0:
            self._current_skip -= 1

    def handle_data(self, data):
        if self._current_skip == 0:
            self.text_parts.append(data)


def extract_words(text: str) -> dict[str, int]:
    """Extract word frequencies from text."""
    words = re.findall(r"[a-zA-Z]{2,}", text.lower())
    freq: dict[str, int] = defaultdict(int)
    for word in words:
        if word not in STOP_WORDS:
            freq[word] += 1
    return dict(freq)


def fetch_url(url: str, timeout: int = 10) -> tuple[int, str]:
    """Fetch a URL, return (status_code, html_content)."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "BrightwaveCrawler/1.0 (educational project)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            charset = "utf-8"
            ct = resp.headers.get_content_charset()
            if ct:
                charset = ct
            content = resp.read().decode(charset, errors="replace")
            return resp.status, content
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


# ---- File-based state helpers ----

def _get_crawler_file(crawler_id: str) -> str:
    return os.path.join(CRAWLERS_DIR, f"{crawler_id}.data")


def _read_visited() -> set[str]:
    if not os.path.exists(VISITED_URLS_FILE):
        # Spec: "If the file does not exist, an empty visited_urls.data file is created."
        open(VISITED_URLS_FILE, "w", encoding="utf-8").close()
        return set()
    with open(VISITED_URLS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def _mark_visited(url: str):
    with _VISITED_LOCK:
        with open(VISITED_URLS_FILE, "a", encoding="utf-8") as f:
            f.write(url + "\n")


_VISITED_LOCK = threading.Lock()
_STORAGE_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _store_words(words: dict[str, int], url: str, origin: str, depth: int):
    """Store word frequencies to letter-bucket files."""
    by_letter: dict[str, list] = defaultdict(list)
    for word, freq in words.items():
        if word and word[0].isalpha():
            letter = word[0].lower()
            by_letter[letter].append((word, url, origin, depth, freq))

    for letter, entries in by_letter.items():
        path = os.path.join(STORAGE_DIR, f"{letter}.data")
        lock = _STORAGE_LOCKS[letter]
        with lock:
            with open(path, "a", encoding="utf-8") as f:
                for word, u, o, d, freq in entries:
                    f.write(json.dumps({
                        "word": word, "url": u, "origin": o,
                        "depth": d, "freq": freq
                    }) + "\n")


def _save_crawler_state(state: dict):
    path = _get_crawler_file(state["id"])
    # Don't hold file lock while writing — each crawler writes its own file
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def load_crawler_state(crawler_id: str) -> dict | None:
    path = _get_crawler_file(crawler_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_all_crawlers() -> list[dict]:
    results = []
    for fname in sorted(os.listdir(CRAWLERS_DIR), reverse=True):
        if fname.endswith(".data"):
            cid = fname[:-5]
            state = load_crawler_state(cid)
            if state:
                results.append(state)
    return results


def get_stats() -> dict:
    visited = _read_visited()
    words = 0
    if os.path.exists(STORAGE_DIR):
        for fname in os.listdir(STORAGE_DIR):
            if fname.endswith(".data"):
                try:
                    with open(os.path.join(STORAGE_DIR, fname), "r") as f:
                        words += sum(1 for _ in f)
                except Exception:
                    pass
    active = sum(
        1 for s in list_all_crawlers() if s.get("status") == "active"
    )
    total = len(list_all_crawlers())
    return {
        "urls_visited": len(visited),
        "words_in_db": words,
        "active_crawlers": active,
        "total_created": total,
    }


def clear_all_data():
    """Remove all stored data."""
    import shutil
    for d in [STORAGE_DIR, CRAWLERS_DIR]:
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
    if os.path.exists(VISITED_URLS_FILE):
        os.remove(VISITED_URLS_FILE)
    with _crawlers_lock:
        _crawlers.clear()


# ---- CrawlerJob ----

class CrawlerJob:
    def __init__(
        self,
        origin: str,
        max_depth: int = 3,
        hit_rate: float = 1.0,
        queue_capacity: int = 10000,
        max_urls: int = 100,
    ):
        self.origin = origin
        self.max_depth = max_depth
        self.hit_rate = max(0.1, min(hit_rate, 100.0))
        self.queue_capacity = queue_capacity
        self.max_urls = max_urls

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Will be set after thread starts
        self.crawler_id: str = ""

        # In-memory state (mirrored to file)
        self.status = "pending"
        self.urls_visited: list[str] = []
        self.queue: list[tuple[str, int]] = []  # (url, depth)
        self.logs: list[str] = []
        self.started_at: str = ""
        self.last_update: str = ""

    def _log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{ts} - {msg}"
        self.logs.append(entry)
        self.last_update = datetime.now().isoformat()
        self._flush()

    def _flush(self):
        state = {
            "id": self.crawler_id,
            "status": self.status,
            "origin": self.origin,
            "max_depth": self.max_depth,
            "hit_rate": self.hit_rate,
            "queue_capacity": self.queue_capacity,
            "max_urls": self.max_urls,
            "urls_visited_count": len(self.urls_visited),
            "urls_visited": self.urls_visited[-200:],  # keep last 200 for perf
            "queue_size": len(self.queue),
            "queue_preview": [u for u, d in self.queue[:50]],
            "queue_preview_depths": [d for u, d in self.queue[:50]],
            "queue": [[u, d] for u, d in self.queue],  # full queue for resume
            "logs": self.logs[-500:],
            "started_at": self.started_at,
            "last_update": self.last_update,
        }
        _save_crawler_state(state)

    def start(self) -> str:
        _id_ready = threading.Event()

        self._thread = threading.Thread(target=self._run, args=(_id_ready,), daemon=True)
        self._thread.start()

        # Block until the thread has set its real OS thread ID, then flush.
        _id_ready.wait()
        return self.crawler_id

    def pause(self):
        if self.status == "active":
            self._pause_event.set()
            self.status = "paused"
            self._log("Crawler paused by user.")

    def resume(self):
        if self.status == "paused":
            self._pause_event.clear()
            self.status = "active"
            self._log("Crawler resumed by user.")

    def stop(self):
        self._stop_event.set()
        self._pause_event.clear()

    def _run(self, _id_ready: threading.Event = None):
        # Set the real OS thread ID now that we are inside the thread.
        if not self.crawler_id:
            epoch = int(time.time())
            self.crawler_id = f"{epoch}_{threading.get_ident()}"

        self.started_at = datetime.now().isoformat()
        self.status = "pending"
        self.last_update = self.started_at
        self._flush()

        # Signal start() that the ID is ready and the file is written.
        if _id_ready is not None:
            _id_ready.set()

        self.status = "active"
        self.last_update = datetime.now().isoformat()

        with _crawlers_lock:
            _crawlers[self.crawler_id] = self

        self._flush()

        visited_global = _read_visited()

        if self.origin in visited_global and not self.queue:
            self._log(f"Origin {self.origin} already visited — skipping.")
        elif not self.queue:  # only seed when not resuming with an existing queue
            self.queue = [(self.origin, 0)]

        delay = 1.0 / self.hit_rate

        while self.queue and not self._stop_event.is_set():
            # Back-pressure: pause if queue exceeds capacity
            while len(self.queue) >= self.queue_capacity and not self._stop_event.is_set():
                self._log(
                    f"[BACKPRESSURE] Queue at capacity ({len(self.queue)}). Waiting…"
                )
                time.sleep(2)

            # Honour pause
            while self._pause_event.is_set() and not self._stop_event.is_set():
                time.sleep(0.5)

            if self._stop_event.is_set():
                break

            # Max URLs limit
            if len(self.urls_visited) >= self.max_urls:
                self._log(
                    f"Reached maximum URL limit ({self.max_urls}). Stopping crawler."
                )
                break

            url, depth = self.queue.pop(0)

            # Skip already visited
            with _VISITED_LOCK:
                visited_global = _read_visited()
            if url in visited_global:
                continue

            if depth > self.max_depth:
                continue

            self._log(f"Crawling {url} at depth {depth}")

            status_code, html = fetch_url(url)

            if status_code == 200:
                self._log(f"Successfully fetched {url} (depth={depth})")
            else:
                self._log(f"Failed to access {url} — HTTP {status_code}")
                _mark_visited(url)
                self.urls_visited.append(url)
                # Spec: if the *origin* page returns a non-200 status, log the
                # error and stop the crawler entirely.  For subsequently
                # discovered links we skip the failing URL and continue so
                # that one bad link does not abort the whole crawl.
                if url == self.origin:
                    self._log("Origin page unreachable — stopping crawler.")
                    break
                continue

            # Parse
            parser = LinkParser(url)
            try:
                parser.feed(html)
            except Exception:
                pass

            text = " ".join(parser.text_parts)
            words = extract_words(text)
            unique_words = len(words)

            _store_words(words, url, self.origin, depth)
            self._log(f"Stored {unique_words} unique words from {url}")

            _mark_visited(url)
            self.urls_visited.append(url)

            # Enqueue new links
            new_links = [
                lnk for lnk in parser.links
                if lnk not in visited_global and lnk not in [u for u, _ in self.queue]
            ]
            self._log(f"Found {len(new_links)} new URLs at {url}")

            if depth < self.max_depth:
                for lnk in new_links:
                    if len(self.queue) < self.queue_capacity:
                        self.queue.append((lnk, depth + 1))

            self._flush()
            time.sleep(delay)

        if self._stop_event.is_set():
            self.status = "stopped"
            self._log("Crawler stopped by user.")
        else:
            self.status = "finished"
            self._log("Crawler finished.")

        self._flush()


def get_crawler(crawler_id: str) -> CrawlerJob | None:
    with _crawlers_lock:
        return _crawlers.get(crawler_id)



def resume_crawler(crawler_id: str) -> str | None:
    """
    Restore a crawler from its saved state file and restart its thread.
    Returns the crawler_id on success, or None if the job cannot be resumed
    (not found, already finished, or already in memory).
    """
    # Don't double-resume a job that's already running in this process
    with _crawlers_lock:
        if crawler_id in _crawlers:
            return crawler_id

    state = load_crawler_state(crawler_id)
    if not state:
        return None
    if state.get("status") in ("finished", "stopped"):
        return None

    job = CrawlerJob(
        origin=state["origin"],
        max_depth=state["max_depth"],
        hit_rate=state["hit_rate"],
        queue_capacity=state["queue_capacity"],
        max_urls=state["max_urls"],
    )

    # Pre-set the original crawler ID so _run() keeps it
    job.crawler_id = crawler_id

    # Restore the full queue saved by _flush(); fall back to queue_preview
    saved_queue = state.get("queue", [])
    if not saved_queue:
        urls   = state.get("queue_preview", [])
        depths = state.get("queue_preview_depths", [])
        saved_queue = list(zip(urls, depths))
    job.queue = [(u, d) for u, d in saved_queue]

    # Restore logs and visited list; pad to preserve accurate urls_visited count
    job.logs = state.get("logs", [])
    saved_visited  = state.get("urls_visited", [])
    visited_count  = state.get("urls_visited_count", len(saved_visited))
    job.urls_visited = [""] * (visited_count - len(saved_visited)) + saved_visited

    job.started_at = state.get("started_at", "")

    job.start()
    return crawler_id


def start_crawler(
    origin: str,
    max_depth: int = 3,
    hit_rate: float = 1.0,
    queue_capacity: int = 10000,
    max_urls: int = 100,
) -> str:
    job = CrawlerJob(origin, max_depth, hit_rate, queue_capacity, max_urls)
    cid = job.start()
    return cid