# Multi-Agent Workflow

## Overview

This project was developed using a structured multi-agent workflow in which eight specialized AI agents collaborated to design, build, evaluate, and document the Brightwave Crawler system. Each agent had a defined scope of responsibility, a specific prompt, and a clear interface with the agents it depended on.

The workflow implements the **Claude Code Agent Teams** architecture:
- A **Team Lead** (Architect Agent) spawns the team and assigns tasks
- A **Shared Task List** (`agent_team/task_list.py`) coordinates work with file locking — agents claim tasks autonomously, dependencies are enforced automatically
- A **Mailbox** (`agent_team/mailbox.py`) enables direct agent-to-agent messaging without human relay — any agent can message any other by name
- An **Evaluation Agent** reviews all outputs and sends feedback directly to the responsible agents
- A human developer reviewed final outputs and made architectural decisions

The agent team infrastructure is fully implemented in `agent_team/` and can be run with a real Anthropic API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python agent_team/agent_team.py
```

---

## Agent Definitions

| # | Agent | Primary Output | Depends On |
|---|-------|---------------|------------|
| 1 | Architect Agent | `product_prd.md`, system design | — |
| 2 | Storage Agent | Storage layer in `crawler.py` | Architect |
| 3 | Crawler Agent | `crawler.py` (crawl engine) | Architect, Storage |
| 4 | Indexer Agent | Text pipeline in `crawler.py` | Architect, Storage |
| 5 | Search Agent | `search_service.py` | Architect, Storage |
| 6 | UI/CLI Agent | `app.py`, `demo/*.html` | Crawler, Indexer, Search |
| 7 | Evaluation Agent | Bug reports, direct feedback | All implementation agents |
| 8 | Documentation Agent | `README.md`, `recommendation.md`, agent docs | All agents |

---

## Workflow Diagram

```
Architect Agent (Team Lead)
      │ broadcasts architecture to all agents via Mailbox
      │ writes task_architecture to Shared Task List
      ▼
┌─────────────────────────────────────────┐
│           SHARED TASK LIST              │
│  task_storage → task_crawler            │
│             → task_indexer              │
│             → task_search               │
│                    ↓                    │
│               task_ui                   │
│                    ↓                    │
│           task_evaluation               │
│                    ↓                    │
│          task_documentation             │
└─────────────────────────────────────────┘
      │
      ▼ agents claim tasks autonomously via task_list.py
      
Storage Agent ──[Mailbox]──► Crawler Agent   "Storage interfaces ready"
Storage Agent ──[Mailbox]──► Indexer Agent   "Call _store_words() only"
Storage Agent ──[Mailbox]──► Search Agent    "Files are append-only, lock-free"

Crawler Agent ──[Mailbox]──► Indexer Agent   "Confirm interface signatures"
Indexer Agent ──[Mailbox]──► Crawler Agent   "Interface confirmed ✓"

Search Agent  ──[Mailbox]──► UI Agent        "Search API response schema"

Evaluation Agent ──[Mailbox]──► Crawler Agent  "2 Critical Issues Found"
Evaluation Agent ──[Mailbox]──► Search Agent   "1 Critical + 1 Medium Issue Found"
Evaluation Agent ──[Mailbox]──► Storage Agent  "Low Severity Finding"
Evaluation Agent ──[Mailbox]──► UI Agent       "UX Finding"

Documentation Agent reads all outputs → produces final docs
```

---

## Shared Task List — Task Definitions

Tasks initialized at team startup with dependency chains:

| Task ID | Title | Assigned To | Depends On |
|---------|-------|-------------|------------|
| `task_architecture` | System Architecture Design | ArchitectAgent | — |
| `task_storage` | Storage Layer Implementation | StorageAgent | task_architecture |
| `task_crawler` | Crawler Engine Implementation | CrawlerAgent | task_storage |
| `task_indexer` | Text Extraction Pipeline | IndexerAgent | task_storage |
| `task_search` | Search Service Implementation | SearchAgent | task_storage |
| `task_ui` | API & UI Implementation | UIAgent | task_crawler, task_indexer, task_search |
| `task_evaluation` | Quality Evaluation & Feedback | EvaluationAgent | task_crawler, task_indexer, task_search, task_ui |
| `task_documentation` | Documentation Generation | DocumentationAgent | task_evaluation |

File locking (`fcntl.LOCK_EX`) prevents two agents from claiming the same task simultaneously. An agent cannot claim a task until all its dependencies are marked `completed`.

---

## Mailbox Interactions — Agent-to-Agent Messages

All messages delivered automatically, no human relay:

### ArchitectAgent → All Agents (Broadcast)
> "Architecture design is complete. Key decisions: Storage: file-based letter-bucket index. Concurrency: per-letter threading.Lock, search is lock-free. Back-pressure: hit_rate delay + queue_capacity gate. Resume: atomic JSON flush via os.replace()."

### StorageAgent → CrawlerAgent
> "Storage layer is complete. Key interfaces: `_mark_visited(url)`, `_read_visited() -> set[str]`, `_save_crawler_state(state_dict)` atomic via os.replace(). `_VISITED_LOCK` and `_STORAGE_LOCKS` defined in storage layer."

### StorageAgent → IndexerAgent
> "You must call `_store_words(words, url, origin, depth)`. Do NOT open storage files directly."

### StorageAgent → SearchAgent
> "Letter-bucket files are append-only JSON-lines. Open in read mode only (no locks). Catch json.JSONDecodeError on every line."

### CrawlerAgent → IndexerAgent
> "Confirm your function signatures: `LinkParser(base_url)`, `parser.links`, `parser.text_parts`, `extract_words(text) -> dict[str, int]`."

### IndexerAgent → CrawlerAgent
> "Interface confirmed ✓. No discrepancies."

### SearchAgent → UIAgent
> "Search API response schema: `{results: [{url, origin, depth, relevance_score, word, frequency}], total, query, tokens, page, per_page, pages}`"

### EvaluationAgent → CrawlerAgent
> "[CRITICAL] Verify visited_urls.data is re-read inside the main loop, not just at startup. [CRITICAL] Verify full queue is saved in `_flush()`, not just `queue_preview[:50]`."

### EvaluationAgent → SearchAgent
> "[CRITICAL] Verify json.JSONDecodeError is caught per line inside the scan loop. [MEDIUM] Verify letter-bucket routing — only open files for letters in query tokens."

### EvaluationAgent → StorageAgent
> "[LOW] Document: if process crashes between open(tmp) and os.replace(), a .data.tmp file is left on disk."

### EvaluationAgent → UIAgent
> "[LOW] Add visual distinction for [BACKPRESSURE] log lines in status.html."

---

## Phase Details

### Phase 1: Design — Architect Agent

The Architect Agent was activated first with the full project requirements. It produced the technical specification all other agents worked against:
- Component boundaries (what goes in which file)
- Storage schema (file formats, directory layout)
- Concurrency model (which locks exist, what they protect)
- Back-pressure specification (two mechanisms, thresholds)
- API surface (all endpoints with request/response shapes)
- Resume design (what is persisted, recovery procedure on startup)

No code was written in this phase. Output: written specification only, broadcast to all agents via Mailbox.

### Phase 2: Implementation — Storage, Crawler, Indexer, Search, UI

Agents 2–6 ran in dependency order enforced by the Shared Task List. Storage Agent ran first (all others depend on its interfaces). Crawler and Indexer could run in parallel (both depend only on Storage). UI Agent ran last (depends on all three implementation agents).

Key lateral interactions:
- CrawlerAgent and IndexerAgent exchanged interface confirmation messages directly
- SearchAgent sent its response schema directly to UIAgent
- StorageAgent sent interface specs directly to all three consumers

### Phase 3: Evaluation — Evaluation Agent

The Evaluation Agent reviewed all implementation outputs independently and found 6 issues:

| Issue | Agent | Severity | Resolution |
|-------|-------|----------|-----------|
| Full queue not saved in resume | CrawlerAgent | Critical | Fixed: `_flush()` now saves `[[url, depth]]` for full queue |
| visited_global stale in multi-crawler | CrawlerAgent | Medium | Fixed: re-read `visited_urls.data` per iteration |
| Partial JSON line crashes search | SearchAgent | Critical | Fixed: `json.JSONDecodeError` caught per line |
| All 26 files scanned per query | SearchAgent | Medium | Fixed: letter-bucket routing added |
| `.tmp` orphan on crash | StorageAgent | Low | Documented in `recommendation.md` |
| No backpressure visual indicator | UIAgent | Low | Fixed: orange highlight + queue depth progress bar |

All feedback sent directly to responsible agents via Mailbox. Each agent revised and the Evaluation Agent confirmed fixes.

### Phase 4: Documentation — Documentation Agent

The Documentation Agent read the final code (not the original plan) and produced documentation that reflects the actual implementation. It found one naming issue: `product_pdr.md` → corrected to `product_prd.md`.

---

## Key Decisions Made by the Human Developer

**Decision 1: File-based storage over SQLite**
The Storage Agent proposed SQLite with WAL mode. The human reviewed the access patterns (append-only writes, prefix-partitioned reads) and decided the file-based letter-bucket approach was simpler and equally correct at this scale.

**Decision 2: Indexer logic merged into `crawler.py`**
The Indexer Agent proposed a separate `indexer.py`. The Evaluation Agent noted this would require passing `_STORAGE_LOCKS` across module boundaries. The human merged the text pipeline into `crawler.py`, keeping functions logically distinct but co-located.

**Decision 3: Long polling over WebSockets**
The UI Agent proposed WebSockets. The human decided long polling required no additional dependencies, was simpler to implement, and met the latency requirement. 25-second timeout with `_time.monotonic()`.

**Decision 4: Frequency + exact-match bonus scoring**
The Search Agent proposed (a) pure frequency, (b) TF-IDF, (c) frequency + exact-match bonus + depth penalty. The human chose (c): `score = (freq × 10) + (1000 if exact) − (depth × 5)`. TF-IDF deferred to production.

---

## What Each Agent Contributed to the Final Codebase

| File | Primary Agent | Contributing Agents |
|------|--------------|---------------------|
| `crawler.py` | Crawler Agent | Indexer Agent (text pipeline), Storage Agent (persistence), Evaluation Agent (bug fixes) |
| `search_service.py` | Search Agent | Evaluation Agent (bucket routing, JSONDecodeError fix) |
| `app.py` | UI/CLI Agent | Storage Agent (resume on startup) |
| `demo/status.html` | UI/CLI Agent | Evaluation Agent (backpressure visualization) |
| `demo/crawler.html` | UI/CLI Agent | — |
| `demo/search.html` | UI/CLI Agent | — |
| `stopwords.py` | Indexer Agent | — |
| `agent_team/task_list.py` | (workflow infrastructure) | — |
| `agent_team/mailbox.py` | (workflow infrastructure) | — |
| `agent_team/agent_team.py` | (workflow infrastructure) | — |
| `README.md` | Documentation Agent | — |
| `product_prd.md` | Documentation Agent | Architect Agent (original spec) |
| `recommendation.md` | Documentation Agent | Evaluation Agent (known limitations) |
| `PRD/*.md` | Documentation Agent | All agents (source material) |

---

## Lessons Learned

**What worked well:**
- The Shared Task List enforced dependency order automatically — no agent started before its prerequisites were complete
- Lateral messaging (StorageAgent→CrawlerAgent, CrawlerAgent→IndexerAgent) eliminated ambiguity about interfaces without human relay
- The Evaluation Agent catching the full-queue-resume bug before delivery was the highest-value intervention — this bug would cause silent data loss that is difficult to detect at runtime

**What would be done differently:**
- The Storage Agent should have been involved earlier in the Crawler Agent's design; the lock primitives were defined late and caused a revision cycle
- The Evaluation Agent should have run a concurrent-crawlers load test, not just static code review, to verify the concurrency model under real stress
- The Indexer Agent's proposal to create a separate `indexer.py` was worth exploring longer before merging — the merge made `crawler.py` harder to navigate
