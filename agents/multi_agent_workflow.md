# Multi-Agent Workflow

## Overview

This project was developed using a structured multi-agent workflow in which eight specialized AI agents collaborated to design, build, evaluate, and document the Brightwave Crawler system. Each agent had a defined scope of responsibility, a specific prompt, and a clear interface with the agents it depended on.

The workflow was orchestrated by the human developer, who reviewed each agent's output, decided whether to accept it or send it back for revision, and made all final architectural decisions.

---

## Agent Definitions

| # | Agent | Primary Output | Depends On |
|---|-------|---------------|------------|
| 1 | Architect Agent | `product_prd.md`, system design | — |
| 2 | Crawler Agent | `crawler.py` (crawl engine) | Architect, Storage |
| 3 | Indexer Agent | `crawler.py` (text pipeline) | Architect, Crawler |
| 4 | Search Agent | `search_service.py` | Architect, Storage, Indexer |
| 5 | Storage Agent | Storage layer in `crawler.py` | Architect |
| 6 | UI/CLI Agent | `app.py`, `demo/*.html` | Architect, Crawler, Search |
| 7 | Documentation Agent | `README.md`, `recommendation.md`, `/agents/*.md` | All agents |
| 8 | Evaluation Agent | Bug reports, feedback loops | All agents |

---

## Workflow Diagram

```
Architect Agent
      │ produces: PRD, system design, API surface
      ▼
Storage Agent ◄──────────────────────────────────┐
      │ produces: file layout, locking primitives, resume logic
      ▼                                           │
Crawler Agent ──────────► Indexer Agent          │
      │ BFS engine,        text pipeline,         │
      │ queue, depth       word extraction        │
      │                         │                 │
      └──────────┬──────────────┘                 │
                 ▼                                │
           Search Agent ────────────────────────►┘
                 │ letter-bucket scan,
                 │ relevance scoring
                 ▼
          UI/CLI Agent
                 │ Flask API, HTML pages
                 ▼
        Evaluation Agent ◄── (reviews all outputs)
                 │ bug reports + feedback loops
                 │ (agents revise → re-review)
                 ▼
        Documentation Agent
                 │ reads final code + eval reports
                 ▼
           Final Deliverables
```

---

## Agent Interactions in Detail

### Phase 1: Design

**Architect Agent → All Agents**

The Architect Agent was activated first with the full project requirements. It produced the technical specification that all other agents worked against:
- Component boundaries (what goes in which file)
- Storage schema (file formats, directory layout)
- Concurrency model (which locks exist, what they protect)
- Back-pressure specification (two mechanisms, thresholds)
- API surface (endpoint list with request/response shapes)
- Resume design (what is persisted, recovery procedure)

No code was written in this phase. The Architect Agent's output was a written specification only.

---

### Phase 2: Implementation

Agents 2–6 ran in dependency order. Each received the Architect Agent's specification plus the relevant outputs of its upstream dependencies.

**Storage Agent → Crawler Agent + Search Agent**

The Storage Agent designed the persistence layer before the Crawler Agent wrote any crawling logic. The key interfaces it defined:
- `_VISITED_LOCK` and `_STORAGE_LOCKS` — threading primitives with their ownership rules
- `_read_visited()` and `_mark_visited()` — the contract for visited URL management
- `_store_words()` — the interface the Indexer Agent would call
- `_save_crawler_state()` — the atomic write pattern the Crawler Agent must use

**Crawler Agent + Indexer Agent → Search Agent**

The Crawler Agent and Indexer Agent produced the letter-bucket files that the Search Agent reads. The Search Agent was given the exact JSON-lines format and was told: reads are lock-free; handle `JSONDecodeError` on every line; handle `OSError` if a file does not yet exist.

**All implementation agents → UI Agent**

The UI Agent was given the final API surface (confirmed against the actual implementation, not just the plan) and the crawler state JSON schema. It built the three HTML pages and the Flask route handlers to match.

---

### Phase 3: Evaluation

**Evaluation Agent ← All implementation outputs**

After each agent produced its first version, the Evaluation Agent reviewed all files independently. It found six issues across the codebase (two critical, two medium, two low). Each issue was sent as a feedback note to the responsible agent.

**Feedback loop example — Issue 1 (Critical):**

1. Evaluation Agent reviewed `crawler.py` and found that `_flush()` saved only the first 50 URLs of the queue (`queue_preview`), not the full queue.
2. Feedback sent to Crawler Agent: *"Resume will lose all but the first 50 queued URLs. Add a `queue` field with the full `[[url, depth]]` list. `resume_crawler()` must prefer this field."*
3. Crawler Agent revised `_flush()` and `resume_crawler()`.
4. Evaluation Agent reviewed the revision and confirmed the fix.

All six issues were resolved through this loop. See `agents/evaluation_agent.md` for the complete list.

---

### Phase 4: Documentation

**Documentation Agent ← Final code + Evaluation Agent reports**

The Documentation Agent was the last to run. It read the final versions of all source files (not the original plans) and produced documentation that reflects the actual implementation. It also wrote all eight `/agents/*.md` files.

The Documentation Agent found one naming discrepancy: the project file was called `product_pdr.md` (PDR) instead of `product_prd.md` (PRD) as required by the assignment. This was flagged and corrected.

---

## Key Decisions Made by the Human Developer

The multi-agent workflow produced code and documentation, but several architectural decisions were made by the human after reviewing agent proposals:

**Decision 1: File-based storage over SQLite**

The Storage Agent initially proposed SQLite with WAL mode. The human reviewed the access patterns and decided the file-based approach was simpler and equally correct for this scale. The Storage Agent then designed the letter-bucket layout.

**Decision 2: Indexer logic merged into `crawler.py`**

The Indexer Agent proposed a separate `indexer.py`. The Evaluation Agent noted this would require passing locking primitives across module boundaries. The human decided to merge the indexer functions into `crawler.py`, keeping them logically distinct but in the same file.

**Decision 3: Long polling over WebSockets**

The UI Agent proposed WebSockets. The human decided long polling was simpler, required no additional dependencies, and met the latency requirement. The UI Agent implemented the 25-second timeout with `_time.monotonic()`.

**Decision 4: Frequency-based scoring with exact-match bonus**

The Search Agent proposed three scoring approaches: (a) pure frequency, (b) TF-IDF, (c) frequency + exact-match bonus + depth penalty. The human chose option (c) as the best balance of simplicity and quality for a prototype. TF-IDF was deferred to the production recommendation.

---

## What Each Agent Contributed to the Final Codebase

| File | Primary Agent | Contributing Agents |
|------|--------------|---------------------|
| `crawler.py` | Crawler Agent | Indexer Agent (text pipeline), Storage Agent (persistence), Evaluation Agent (bug fixes) |
| `search_service.py` | Search Agent | Evaluation Agent (bucket routing, JSONDecodeError fix) |
| `app.py` | UI/CLI Agent | Storage Agent (resume on startup) |
| `demo/crawler.html` | UI/CLI Agent | — |
| `demo/status.html` | UI/CLI Agent | Evaluation Agent (back-pressure visualization) |
| `demo/search.html` | UI/CLI Agent | — |
| `stopwords.py` | Indexer Agent | — |
| `README.md` | Documentation Agent | — |
| `product_prd.md` | Documentation Agent | Architect Agent (original spec) |
| `recommendation.md` | Documentation Agent | Evaluation Agent (known limitations) |
| `agents/*.md` | Documentation Agent | All agents (source material) |
| `multi_agent_workflow.md` | Documentation Agent | — |

---

## Lessons Learned

**What worked well:**
- Strict phase ordering (design → implement → evaluate → document) prevented rework. No agent started implementation before the Architect Agent's spec was finalized.
- The Evaluation Agent catching the full-queue-resume bug before deployment was the highest-value intervention. This bug would have caused silent data loss that was difficult to detect at runtime.
- Separate agents for Crawler and Indexer clarified responsibility even though their code ended up in the same file.

**What would be done differently:**
- The Storage Agent should have been involved earlier in the Crawler Agent's design — the Storage Agent's lock primitives were defined late and caused a revision cycle.
- The Indexer Agent's proposal to create a separate file was worth exploring longer before merging into `crawler.py`. The merge made the file longer and harder to navigate.
- The Evaluation Agent should have run a load test (multiple concurrent crawlers) to verify the concurrency model under stress, not just code review.
