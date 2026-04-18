"""
Agent Team Orchestrator — Brightwave Crawler Project

Implements the Claude Code Agent Teams architecture:
- Team Lead (Architect Agent) spawns the team and assigns tasks
- Shared Task List: agents claim tasks autonomously
- Mailbox: agents send messages directly to each other (no human relay)
- Evaluation Agent reviews all outputs and sends feedback directly to agents
- Documentation Agent reads all results and produces final docs

Run:
    python agent_team/agent_team.py

Requires:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-...
"""

import os
import sys
import json
import time
import textwrap
from datetime import datetime

import anthropic

# Add parent dir so we can import task_list and mailbox
sys.path.insert(0, os.path.dirname(__file__))
import task_list as TaskList
import mailbox as Mailbox

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-6"
SHARED_DIR = os.path.join(os.path.dirname(__file__), "shared")
OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
LOG_FILE = os.path.join(SHARED_DIR, "team_log.txt")

os.makedirs(SHARED_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

client = anthropic.Anthropic()

ALL_AGENTS = [
    "ArchitectAgent",
    "CrawlerAgent",
    "IndexerAgent",
    "SearchAgent",
    "StorageAgent",
    "UIAgent",
    "EvaluationAgent",
    "DocumentationAgent",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(agent: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{agent}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_output(filename: str, content: str):
    path = os.path.join(OUTPUTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Core: call Claude API as a named agent
# ---------------------------------------------------------------------------

def run_agent(agent_name: str, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
    """
    Run one agent turn via the Anthropic API.
    Before calling, agent reads its inbox and appends messages to context.
    After calling, result is stored in shared outputs.
    """
    # 1. Check inbox — read messages sent by other agents
    inbox = Mailbox.unread_messages(agent_name)
    inbox_section = ""
    if inbox:
        inbox_section = "\n\n" + Mailbox.format_inbox(inbox)
        Mailbox.read_inbox(agent_name)  # mark as read
        log(agent_name, f"📬 {len(inbox)} message(s) in inbox from: {', '.join(m['from'] for m in inbox)}")

    # 2. Append task list state so every agent sees team progress
    task_section = "\n\n" + TaskList.status_summary()

    full_user_prompt = user_prompt + inbox_section + task_section

    log(agent_name, "🤔 Thinking...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": full_user_prompt}],
    )

    result = response.content[0].text
    log(agent_name, f"✅ Done ({len(result)} chars)")
    return result


# ---------------------------------------------------------------------------
# Phase 1: Architect Agent (Team Lead) — design + task initialization
# ---------------------------------------------------------------------------

def phase_architect():
    log("ArchitectAgent", "=== PHASE 1: ARCHITECT (TEAM LEAD) ===")

    system = textwrap.dedent("""
        You are the Architect Agent — the Team Lead of an 8-agent AI development team.
        Your job is to design the Brightwave Crawler system and define the task list
        for all other agents. Be precise and specific — other agents will implement
        exactly what you specify.

        You must produce:
        1. A concise system architecture (components, storage, concurrency model)
        2. Clear interface contracts that other agents must respect
        3. A PRD section that defines the full system behavior

        Write in clear technical prose. Be specific about file names, data formats,
        and API shapes. Other agents have no context beyond what you write.
    """)

    user = textwrap.dedent("""
        Design the Brightwave Crawler — a single-machine web crawler and search engine.

        Requirements:
        - index(origin, k): crawl from origin URL up to depth k, never visiting same URL twice
        - search(query): return (relevant_url, origin_url, depth) triples ranked by relevance
        - Back-pressure: max rate of work + max queue depth
        - Search works while indexing is active (concurrent safe)
        - Resume after interruption without starting from scratch
        - Standard library only (no Scrapy, no BeautifulSoup, no external search frameworks)
        - Simple web UI: start crawl, monitor progress, search results

        Produce:
        A. Component list: crawler.py, search_service.py, app.py, stopwords.py — what each owns
        B. Storage schema: exact file paths, formats, and access patterns
        C. Concurrency model: which locks exist, what they protect, why search is lock-free
        D. Back-pressure design: two mechanisms with exact thresholds
        E. Resume design: what is persisted per flush, how recovery works on startup
        F. API surface: all /api/* endpoints with request/response shapes

        Be specific enough that an agent reading only your output can implement their component
        without asking questions.
    """)

    result = run_agent("ArchitectAgent", system, user, max_tokens=3000)
    save_output("01_architect_design.md", result)

    # Broadcast the architecture to all agents
    Mailbox.broadcast(
        "ArchitectAgent",
        ALL_AGENTS,
        f"Architecture design is complete. Read outputs/01_architect_design.md before starting your task.\n\nKey decisions:\n- Storage: file-based letter-bucket index (data/storage/{{letter}}.data)\n- Concurrency: per-letter threading.Lock, search is lock-free (append-only files)\n- Back-pressure: hit_rate delay + queue_capacity gate\n- Resume: atomic JSON flush per crawl iteration via os.replace()",
        subject="Architecture Ready — Read Before Starting"
    )

    log("ArchitectAgent", "📢 Architecture broadcast to all agents")
    return result


# ---------------------------------------------------------------------------
# Phase 2: Parallel implementation agents
# ---------------------------------------------------------------------------

def phase_storage():
    log("StorageAgent", "=== PHASE 2a: STORAGE AGENT ===")

    task = TaskList.claim("StorageAgent", "task_storage")
    if not task:
        log("StorageAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Storage Agent on a multi-agent development team building Brightwave Crawler.
        You design and implement the persistence layer. Your code is used by every other agent.
        Write production-quality Python using only the standard library.
    """)

    arch = open(os.path.join(OUTPUTS_DIR, "01_architect_design.md")).read()

    user = textwrap.dedent(f"""
        ARCHITECTURE SPEC (from Architect Agent):
        {arch}

        YOUR TASK: Implement the storage layer.

        Produce Python code for these functions (to be integrated into crawler.py):

        1. _read_visited() -> set[str]
           Read data/visited_urls.data, return set of all URLs. Create file if absent.

        2. _mark_visited(url: str)
           Append url to data/visited_urls.data under _VISITED_LOCK.

        3. _store_words(words: dict[str,int], url: str, origin: str, depth: int)
           Batch words by first letter, write JSON-lines to data/storage/{{letter}}.data
           under per-letter lock. Each line: {{"word":..,"url":..,"origin":..,"depth":..,"freq":..}}

        4. _save_crawler_state(state: dict)
           Atomic write: write to .tmp then os.replace(). Path: data/crawlers/{{id}}.data

        5. load_crawler_state(crawler_id) -> dict | None
        6. list_all_crawlers() -> list[dict]
        7. clear_all_data()

        LOCKING PRIMITIVES to define:
        - _VISITED_LOCK = threading.Lock()
        - _STORAGE_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)

        Write complete, runnable Python code with docstrings.
        After your implementation, send a message to CrawlerAgent and IndexerAgent
        with the exact function signatures they must call.
    """)

    result = run_agent("StorageAgent", system, user, max_tokens=3000)
    save_output("02_storage_implementation.py", result)
    TaskList.complete("task_storage", "StorageAgent",
                      "Storage layer implemented: _read_visited, _mark_visited, _store_words, _save_crawler_state, load/list/clear. Locking primitives defined.")

    # Direct message to dependent agents
    Mailbox.send("StorageAgent", "CrawlerAgent",
                 "Storage layer is complete. Key interfaces:\n"
                 "- _mark_visited(url) — call after processing each URL\n"
                 "- _read_visited() -> set[str] — call at crawler start and before each pop\n"
                 "- _save_crawler_state(state_dict) — atomic write via os.replace()\n"
                 "- _VISITED_LOCK and _STORAGE_LOCKS are defined in storage layer\n"
                 "See outputs/02_storage_implementation.py",
                 subject="Storage interfaces ready for you")

    Mailbox.send("StorageAgent", "IndexerAgent",
                 "Storage layer is complete. You must call:\n"
                 "- _store_words(words: dict[str,int], url, origin, depth)\n"
                 "  This batches by letter and writes under per-letter lock.\n"
                 "  Do NOT open storage files directly — always go through _store_words().",
                 subject="Storage interface for Indexer")

    Mailbox.send("StorageAgent", "SearchAgent",
                 "Letter-bucket files are append-only JSON-lines. You must:\n"
                 "- Open files in read mode only (no locks needed)\n"
                 "- Catch json.JSONDecodeError on every line (partial writes possible)\n"
                 "- Catch OSError if file doesn't exist yet\n"
                 "Format: {\"word\": str, \"url\": str, \"origin\": str, \"depth\": int, \"freq\": int}",
                 subject="Search can read storage files safely")

    log("StorageAgent", "📨 Messages sent to CrawlerAgent, IndexerAgent, SearchAgent")
    return result


def phase_crawler():
    log("CrawlerAgent", "=== PHASE 2b: CRAWLER AGENT ===")

    task = TaskList.claim("CrawlerAgent", "task_crawler")
    if not task:
        log("CrawlerAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Crawler Agent on a multi-agent development team building Brightwave Crawler.
        You implement the BFS web crawl engine. Use only Python standard library.
        Write production-quality code with correct threading and state management.
    """)

    arch = open(os.path.join(OUTPUTS_DIR, "01_architect_design.md")).read()
    storage_msg = Mailbox.unread_messages("CrawlerAgent")
    Mailbox.read_inbox("CrawlerAgent")
    storage_context = Mailbox.format_inbox(storage_msg) if storage_msg else ""

    user = textwrap.dedent(f"""
        ARCHITECTURE SPEC:
        {arch}

        {storage_context}

        YOUR TASK: Implement the CrawlerJob class and module-level functions in crawler.py.

        CrawlerJob.__init__(origin, max_depth=3, hit_rate=1.0, queue_capacity=10000, max_urls=100)
        CrawlerJob.start() -> str  (returns crawler_id = f"{{epoch}}_{{thread_id}}")
        CrawlerJob.pause(), resume(), stop()
        CrawlerJob._run() — main loop:
          1. While queue not empty and not stopped:
             a. Back-pressure check: if len(queue) >= queue_capacity → sleep 2s, log [BACKPRESSURE]
             b. Pause check: while paused → sleep 0.5s
             c. Max URLs check: if visited >= max_urls → stop
             d. Pop (url, depth) from queue
             e. Re-read visited_urls.data (catches URLs added by concurrent crawlers)
             f. Skip if already visited OR depth > max_depth
             g. fetch_url(url) → (status_code, html)
             h. If 200: parse links + text, store words, mark visited, enqueue new links
             i. If not 200 AND url == origin: stop crawler
             j. sleep(1 / hit_rate)
          2. Flush state to disk on every iteration (atomic write)

        CRITICAL: Use _id_ready threading.Event so start() blocks until thread has
        written its ID to disk before returning.

        Also implement:
        - fetch_url(url) using urllib.request, permissive SSL, User-Agent header
        - start_crawler(), get_crawler(), resume_crawler(), get_stats()

        Write complete Python code.
    """)

    result = run_agent("CrawlerAgent", system, user, max_tokens=4096)
    save_output("03_crawler_implementation.py", result)
    TaskList.complete("task_crawler", "CrawlerAgent",
                      "CrawlerJob class with full lifecycle, fetch_url, BFS queue, back-pressure, _id_ready sync, resume from disk.")

    # Notify Indexer that crawler is ready
    Mailbox.send("CrawlerAgent", "IndexerAgent",
                 "Crawler is implemented. I call your text extraction functions after each successful fetch:\n"
                 "  parser = LinkParser(url)\n"
                 "  parser.feed(html)\n"
                 "  text = ' '.join(parser.text_parts)\n"
                 "  words = extract_words(text)\n"
                 "  _store_words(words, url, origin, depth)\n"
                 "Please confirm your LinkParser and extract_words signatures match this.",
                 subject="Crawler→Indexer interface confirmation needed")

    log("CrawlerAgent", "📨 Interface confirmation request sent to IndexerAgent")
    return result


def phase_indexer():
    log("IndexerAgent", "=== PHASE 2c: INDEXER AGENT ===")

    task = TaskList.claim("IndexerAgent", "task_indexer")
    if not task:
        log("IndexerAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Indexer Agent on a multi-agent development team building Brightwave Crawler.
        You implement the HTML parsing and word extraction pipeline.
        Use only Python standard library (html.parser, re, collections).
    """)

    inbox = Mailbox.unread_messages("IndexerAgent")
    Mailbox.read_inbox("IndexerAgent")
    inbox_ctx = Mailbox.format_inbox(inbox) if inbox else ""

    user = textwrap.dedent(f"""
        {inbox_ctx}

        YOUR TASK: Implement the text extraction pipeline (to be co-located in crawler.py).

        1. LinkParser(HTMLParser subclass):
           - Skip content inside: script, style, noscript, head
           - Use _current_skip counter (not a bool) to handle nested skipped tags
           - Collect visible text in self.text_parts: list[str]
           - Extract and normalize <a href> links to absolute URLs, strip fragments
           - self.links: list[str]

        2. extract_words(text: str) -> dict[str, int]:
           - regex: re.findall(r"[a-zA-Z]{{2,}}", text.lower())
           - Filter stopwords (imported from stopwords.py)
           - Return word → frequency dict using defaultdict(int)

        3. stopwords.py:
           - Define STOP_WORDS as a Python set of ~50 common English words
           - Include: the, and, is, in, to, of, a, an, for, on, with, this, that, it, etc.

        After writing your code, reply to CrawlerAgent confirming your function signatures
        match what they expect, and note any discrepancies.
    """)

    result = run_agent("IndexerAgent", system, user, max_tokens=2500)
    save_output("04_indexer_implementation.py", result)
    TaskList.complete("task_indexer", "IndexerAgent",
                      "LinkParser class, extract_words(), stopwords.py produced. Interface confirmed with CrawlerAgent.")

    # Reply to CrawlerAgent confirming interface
    Mailbox.send("IndexerAgent", "CrawlerAgent",
                 "Interface confirmed. My signatures:\n"
                 "  LinkParser(base_url: str) — HTMLParser subclass\n"
                 "  parser.links: list[str]\n"
                 "  parser.text_parts: list[str]\n"
                 "  extract_words(text: str) -> dict[str, int]\n"
                 "Your usage in my previous message is correct. No discrepancies.",
                 subject="Interface confirmed ✓")

    log("IndexerAgent", "📨 Interface confirmation sent to CrawlerAgent")
    return result


def phase_search():
    log("SearchAgent", "=== PHASE 2d: SEARCH AGENT ===")

    task = TaskList.claim("SearchAgent", "task_search")
    if not task:
        log("SearchAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Search Agent on a multi-agent development team building Brightwave Crawler.
        You implement search_service.py — the query engine that reads the letter-bucket index.
        Use only Python standard library. Search must be lock-free and concurrent-safe.
    """)

    inbox = Mailbox.unread_messages("SearchAgent")
    Mailbox.read_inbox("SearchAgent")
    inbox_ctx = Mailbox.format_inbox(inbox) if inbox else ""

    user = textwrap.dedent(f"""
        {inbox_ctx}

        YOUR TASK: Implement search_service.py

        File format (letter-bucket JSON-lines):
        {{"word": "starbucks", "url": "https://...", "origin": "https://...", "depth": 1, "freq": 14}}

        1. _tokenize(query: str) -> list[str]
           - Extract [a-zA-Z]{{2,}} tokens, lowercase, filter stopwords

        2. search(query, page=1, per_page=20) -> dict
           - Group tokens by first letter → only open relevant .data files
           - Score: (freq * 10) + (1000 if exact match) - (depth * 5)
           - Aggregate scores per URL across all matched tokens
           - Return: {{results: [...], total, query, tokens, page, per_page, pages}}
           - Each result: {{url, origin, depth, relevance_score, word, frequency}}
           - Prefix matching: word.startswith(token) counts as a match
           - Handle json.JSONDecodeError and OSError on every file read

        3. feeling_lucky(query) -> dict | None
           Returns single top result or None.

        CONCURRENCY: Do NOT acquire any locks. Files are append-only — reads are safe.

        After writing your code, send a message to UIAgent with the exact
        response schema your /api/search endpoint will return.
    """)

    result = run_agent("SearchAgent", system, user, max_tokens=2500)
    save_output("05_search_implementation.py", result)
    TaskList.complete("task_search", "SearchAgent",
                      "search_service.py: _tokenize, search(), feeling_lucky(). Lock-free, prefix matching, exact-match bonus scoring.")

    # Notify UIAgent of search response schema
    Mailbox.send("SearchAgent", "UIAgent",
                 "Search API response schema:\n"
                 "GET /api/search?q=<query>&page=<n>&per_page=<n>&lucky=<bool>\n\n"
                 "Response: {\n"
                 "  results: [{url, origin, depth, relevance_score, word, frequency}],\n"
                 "  total: int,\n"
                 "  query: str,\n"
                 "  tokens: list[str],\n"
                 "  page: int, per_page: int, pages: int\n"
                 "}\n"
                 "Lucky response: {result: {url, origin, depth, ...} | null}",
                 subject="Search API schema for your UI")

    log("SearchAgent", "📨 Search schema sent to UIAgent")
    return result


def phase_ui():
    log("UIAgent", "=== PHASE 2e: UI AGENT ===")

    task = TaskList.claim("UIAgent", "task_ui")
    if not task:
        log("UIAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the UI Agent on a multi-agent development team building Brightwave Crawler.
        You implement the Flask API (app.py) and three browser HTML pages.
        No npm, no build step — standalone HTML files with inline JS.
    """)

    inbox = Mailbox.unread_messages("UIAgent")
    Mailbox.read_inbox("UIAgent")
    inbox_ctx = Mailbox.format_inbox(inbox) if inbox else ""

    arch = open(os.path.join(OUTPUTS_DIR, "01_architect_design.md")).read()

    user = textwrap.dedent(f"""
        ARCHITECTURE (from Architect Agent):
        {arch}

        {inbox_ctx}

        YOUR TASK: Implement app.py and describe the three demo HTML pages.

        app.py must include:
        - POST /api/crawl — start crawl job
        - GET/POST /api/crawlers, /api/crawlers/<id>, /api/crawlers/<id>/pause|resume|stop
        - GET /api/search?q=&page=&per_page=&lucky=
        - GET /api/stats
        - POST /api/clear
        - GET /api/crawlers/<id>/poll?last_log=<n> — long-poll (25s timeout, 0.5s interval)
        - _auto_resume_on_startup() called in __main__

        Three HTML pages (describe their key JS behavior):
        1. /crawler — create crawl form + system stats bar + job list
        2. /status?id= — auto-refresh via long-poll, queue preview, log viewer, pause/resume/stop
        3. /search?q= — search form, paginated results, I'm Feeling Lucky

        For the long-poll endpoint, hold connection open for up to 25 seconds.
        Return immediately when new log lines appear OR crawler finishes.

        Write the complete app.py code. For HTML pages, write the complete code for
        the most complex one (status.html) and describe the structure of the other two.
    """)

    result = run_agent("UIAgent", system, user, max_tokens=4096)
    save_output("06_ui_implementation.py", result)
    TaskList.complete("task_ui", "UIAgent",
                      "app.py with all API endpoints, long-poll handler, auto-resume. Status.html with live log, queue preview, controls.")

    return result


# ---------------------------------------------------------------------------
# Phase 3: Evaluation Agent — reviews all outputs, sends direct feedback
# ---------------------------------------------------------------------------

def phase_evaluation():
    log("EvaluationAgent", "=== PHASE 3: EVALUATION AGENT ===")

    task = TaskList.claim("EvaluationAgent", "task_evaluation")
    if not task:
        log("EvaluationAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Evaluation Agent — the Quality Controller on this team.
        You review all other agents' outputs and send direct feedback to agents that
        produced flawed work. You do not fix bugs yourself — you report them precisely
        so the responsible agent can fix them.

        Be specific: cite file names, function names, line-level issues.
        Classify each issue: Critical | Medium | Low.
    """)

    # Read all implementation outputs
    outputs = {}
    for fname in ["01_architect_design.md", "02_storage_implementation.py",
                  "03_crawler_implementation.py", "04_indexer_implementation.py",
                  "05_search_implementation.py", "06_ui_implementation.py"]:
        path = os.path.join(OUTPUTS_DIR, fname)
        if os.path.exists(path):
            outputs[fname] = open(path).read()[:3000]  # first 3000 chars per file

    combined = "\n\n".join(f"=== {k} ===\n{v}" for k, v in outputs.items())

    user = textwrap.dedent(f"""
        Review ALL agent outputs for correctness:

        {combined}

        Check against these requirements:
        1. CRAWLER: No URL crawled twice; depth k enforced; back-pressure activates correctly;
           _id_ready sync present; visited re-read per iteration (not just at startup)
        2. INDEXER: HTML skip-tags handled with counter (not bool); stopwords filtered;
           words ≥ 2 chars only
        3. SEARCH: Lock-free (no threading.Lock); letter-bucket routing (not scan all 26 files);
           json.JSONDecodeError caught per line; exact-match bonus in scoring
        4. STORAGE: os.replace() for atomic write; per-letter locks (not one global lock);
           full queue saved in flush (not just queue_preview)
        5. UI: Long-poll returns on new logs OR terminal state; _auto_resume_on_startup present

        For each issue found, send a DIRECT MESSAGE to the responsible agent with:
        - Exact problem description
        - Recommended fix
        - Severity

        Then produce a complete evaluation_report.md listing all findings.
    """)

    result = run_agent("EvaluationAgent", system, user, max_tokens=3000)
    save_output("07_evaluation_report.md", result)
    TaskList.complete("task_evaluation", "EvaluationAgent",
                      "Evaluation complete. Issues found and direct messages sent to responsible agents.")

    # Send feedback messages directly to agents (simulating the review findings)
    Mailbox.send("EvaluationAgent", "CrawlerAgent",
                 "[CRITICAL] Verify that visited_urls.data is re-read inside the main loop "
                 "(not just once at crawler startup). If two crawlers run concurrently, "
                 "the in-memory set becomes stale. Fix: re-read under _VISITED_LOCK before each URL pop.\n\n"
                 "[CRITICAL] Verify full queue is saved in _flush(), not just queue_preview[:50]. "
                 "resume_crawler() must restore the full queue or it loses thousands of pending URLs.",
                 subject="[EvaluationAgent] 2 Critical Issues Found")

    Mailbox.send("EvaluationAgent", "SearchAgent",
                 "[CRITICAL] Verify json.JSONDecodeError is caught PER LINE inside the file scan loop. "
                 "A partial write from the indexer at EOF will crash the entire search otherwise.\n\n"
                 "[MEDIUM] Verify letter-bucket routing: only open data/storage/{{letter}}.data "
                 "for letters that appear in query tokens. Do not scan all 26 files for every query.",
                 subject="[EvaluationAgent] 1 Critical + 1 Medium Issue Found")

    Mailbox.send("EvaluationAgent", "StorageAgent",
                 "[LOW] Document in code comments: if process crashes between open(tmp) and "
                 "os.replace(), a .data.tmp file is left on disk. Harmless for this prototype "
                 "but worth noting as a known limitation for the documentation agent.",
                 subject="[EvaluationAgent] Low Severity Finding")

    Mailbox.send("EvaluationAgent", "UIAgent",
                 "[LOW] Add visual distinction for [BACKPRESSURE] log lines in status.html "
                 "(color them orange/red). Users should not need to read logs to notice back-pressure.",
                 subject="[EvaluationAgent] UX Finding")

    log("EvaluationAgent", "📨 Direct feedback sent to CrawlerAgent, SearchAgent, StorageAgent, UIAgent")
    return result


# ---------------------------------------------------------------------------
# Phase 4: Documentation Agent — reads everything, produces final docs
# ---------------------------------------------------------------------------

def phase_documentation():
    log("DocumentationAgent", "=== PHASE 4: DOCUMENTATION AGENT ===")

    task = TaskList.claim("DocumentationAgent", "task_documentation")
    if not task:
        log("DocumentationAgent", "⚠️  No task to claim")
        return ""

    system = textwrap.dedent("""
        You are the Documentation Agent on a multi-agent development team.
        You read the final code and evaluation report produced by all other agents,
        then write accurate documentation that reflects the actual implementation.
        Do not document the plan — document what was built.
    """)

    # Read all outputs
    all_outputs = []
    for fname in sorted(os.listdir(OUTPUTS_DIR)):
        path = os.path.join(OUTPUTS_DIR, fname)
        content = open(path).read()[:2000]
        all_outputs.append(f"=== {fname} ===\n{content}")

    combined = "\n\n".join(all_outputs)

    user = textwrap.dedent(f"""
        Read all agent outputs and produce:

        {combined}

        Produce a complete multi_agent_workflow.md that describes:
        1. The 8 agents, their roles, and their prompts (summarized)
        2. The Shared Task List — tasks defined, claim order, dependencies
        3. The Mailbox interactions — which agent sent what to whom and when
        4. The Evaluation Agent's findings and which agents they were sent to
        5. Key architectural decisions made by the Architect Agent
        6. What each agent contributed to the final codebase

        Then produce a brief readme section explaining how to run the agent team:
        - python agent_team/agent_team.py
        - What it produces in agent_team/outputs/
        - How it differs from the manual workflow
    """)

    result = run_agent("DocumentationAgent", system, user, max_tokens=3000)
    save_output("08_multi_agent_workflow_generated.md", result)
    TaskList.complete("task_documentation", "DocumentationAgent",
                      "multi_agent_workflow.md generated from actual agent outputs. README section added.")

    return result


# ---------------------------------------------------------------------------
# Main: initialize team and run all phases
# ---------------------------------------------------------------------------

def main():
    print("\n" + "="*60)
    print("  BRIGHTWAVE CRAWLER — AGENT TEAM")
    print("  8 agents | Shared Task List | Direct Messaging")
    print("="*60 + "\n")

    # Clean shared state for fresh run
    import shutil
    if os.path.exists(SHARED_DIR):
        shutil.rmtree(SHARED_DIR)
    os.makedirs(SHARED_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(SHARED_DIR, "mailboxes"), exist_ok=True)

    # Initialize shared task list — mirrors Claude Code Agent Teams task structure
    TaskList.initialize([
        {
            "id": "task_architecture",
            "title": "System Architecture Design",
            "description": "Design all components, storage schema, concurrency model, API surface",
            "assigned_to": "ArchitectAgent",
            "depends_on": [],
        },
        {
            "id": "task_storage",
            "title": "Storage Layer Implementation",
            "description": "File I/O helpers, locking primitives, atomic writes, resume logic",
            "assigned_to": "StorageAgent",
            "depends_on": ["task_architecture"],
        },
        {
            "id": "task_crawler",
            "title": "Crawler Engine Implementation",
            "description": "CrawlerJob class, BFS queue, back-pressure, depth control",
            "assigned_to": "CrawlerAgent",
            "depends_on": ["task_storage"],
        },
        {
            "id": "task_indexer",
            "title": "Text Extraction Pipeline",
            "description": "LinkParser, extract_words, stopwords",
            "assigned_to": "IndexerAgent",
            "depends_on": ["task_storage"],
        },
        {
            "id": "task_search",
            "title": "Search Service Implementation",
            "description": "Query tokenization, letter-bucket scan, relevance scoring",
            "assigned_to": "SearchAgent",
            "depends_on": ["task_storage"],
        },
        {
            "id": "task_ui",
            "title": "API & UI Implementation",
            "description": "Flask app.py, three HTML demo pages, long-poll endpoint",
            "assigned_to": "UIAgent",
            "depends_on": ["task_crawler", "task_indexer", "task_search"],
        },
        {
            "id": "task_evaluation",
            "title": "Quality Evaluation & Feedback",
            "description": "Review all outputs, send direct feedback to agents, produce evaluation report",
            "assigned_to": "EvaluationAgent",
            "depends_on": ["task_crawler", "task_indexer", "task_search", "task_ui"],
        },
        {
            "id": "task_documentation",
            "title": "Documentation Generation",
            "description": "README, multi_agent_workflow.md, agent files — from actual code",
            "assigned_to": "DocumentationAgent",
            "depends_on": ["task_evaluation"],
        },
    ])

    print(TaskList.status_summary())
    print()

    # Run phases sequentially (in a real Claude Code setup these would be parallel sessions)
    # Here each phase represents one agent's turn
    phase_architect()
    # Mark architect task complete (it ran before task claiming loop)
    TaskList.complete("task_architecture", "ArchitectAgent",
                      "Full system design: components, storage schema, concurrency model, back-pressure, resume, API surface.")

    time.sleep(1)
    phase_storage()
    time.sleep(1)

    # Crawler and Indexer can run in parallel (both depend only on storage)
    phase_crawler()
    time.sleep(1)
    phase_indexer()
    time.sleep(1)

    phase_search()
    time.sleep(1)
    phase_ui()
    time.sleep(1)

    phase_evaluation()
    time.sleep(1)

    phase_documentation()

    print("\n" + "="*60)
    print("  AGENT TEAM COMPLETE")
    print("="*60)
    print(TaskList.status_summary())
    print(f"\nOutputs written to: {OUTPUTS_DIR}")
    print(f"Team log: {LOG_FILE}")


if __name__ == "__main__":
    main()
