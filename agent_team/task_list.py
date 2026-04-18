"""
Shared Task List — Agent Teams implementation.

Provides a file-locked, shared task queue that all agents read from and write to.
Mirrors the Claude Code Agent Teams architecture:
- Tasks have states: pending → in_progress → completed / blocked
- Tasks can declare dependencies on other tasks
- File locking prevents race conditions when multiple agents claim simultaneously
- Any agent can read the full task list to understand team progress
"""

import json
import os
import time
import fcntl
from datetime import datetime
from typing import Optional

TASK_LIST_PATH = os.path.join(os.path.dirname(__file__), "shared", "task_list.json")


def _ensure_dir():
    os.makedirs(os.path.dirname(TASK_LIST_PATH), exist_ok=True)


def _read_locked(f) -> list[dict]:
    f.seek(0)
    content = f.read()
    if not content.strip():
        return []
    return json.loads(content)


def _write_locked(f, tasks: list[dict]):
    f.seek(0)
    f.truncate()
    f.write(json.dumps(tasks, indent=2, ensure_ascii=False))
    f.flush()


def initialize(tasks: list[dict]):
    """Create the task list with initial tasks. Call once at team startup."""
    _ensure_dir()
    now = datetime.now().isoformat()
    initialized = []
    for i, t in enumerate(tasks):
        initialized.append({
            "id": t.get("id", f"task_{i+1:02d}"),
            "title": t["title"],
            "description": t["description"],
            "assigned_to": t.get("assigned_to"),        # None = any agent can claim
            "depends_on": t.get("depends_on", []),       # list of task ids
            "status": "pending",                          # pending | in_progress | completed | blocked
            "claimed_by": None,
            "result_summary": None,
            "created_at": now,
            "claimed_at": None,
            "completed_at": None,
        })
    with open(TASK_LIST_PATH, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        _write_locked(f, initialized)
        fcntl.flock(f, fcntl.LOCK_UN)


def read_all() -> list[dict]:
    """Read current task list (shared read — no write lock needed)."""
    _ensure_dir()
    if not os.path.exists(TASK_LIST_PATH):
        return []
    with open(TASK_LIST_PATH, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        tasks = _read_locked(f)
        fcntl.flock(f, fcntl.LOCK_UN)
    return tasks


def claim(agent_name: str, task_id: Optional[str] = None) -> Optional[dict]:
    """
    Atomically claim a task for agent_name.
    If task_id is given, claim that specific task.
    If task_id is None, claim the first available unblocked pending task.
    Returns the claimed task dict, or None if nothing is available.
    """
    _ensure_dir()
    if not os.path.exists(TASK_LIST_PATH):
        return None

    with open(TASK_LIST_PATH, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        tasks = _read_locked(f)

        completed_ids = {t["id"] for t in tasks if t["status"] == "completed"}

        claimed = None
        for t in tasks:
            if task_id and t["id"] != task_id:
                continue
            if t["status"] != "pending":
                continue
            if t["assigned_to"] and t["assigned_to"] != agent_name:
                continue
            # Check all dependencies are completed
            deps_met = all(dep in completed_ids for dep in t.get("depends_on", []))
            if not deps_met:
                continue
            # Claim it
            t["status"] = "in_progress"
            t["claimed_by"] = agent_name
            t["claimed_at"] = datetime.now().isoformat()
            claimed = t
            break

        if claimed:
            _write_locked(f, tasks)
        fcntl.flock(f, fcntl.LOCK_UN)

    return claimed


def complete(task_id: str, agent_name: str, result_summary: str):
    """Mark a task as completed and store the result summary."""
    _ensure_dir()
    with open(TASK_LIST_PATH, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        tasks = _read_locked(f)
        for t in tasks:
            if t["id"] == task_id and t["claimed_by"] == agent_name:
                t["status"] = "completed"
                t["result_summary"] = result_summary
                t["completed_at"] = datetime.now().isoformat()
                break
        _write_locked(f, tasks)
        fcntl.flock(f, fcntl.LOCK_UN)


def status_summary() -> str:
    """Return a human-readable summary of all task statuses."""
    tasks = read_all()
    lines = ["=== SHARED TASK LIST ==="]
    for t in tasks:
        icon = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "blocked": "🚫"}.get(t["status"], "?")
        agent = f" [{t['claimed_by']}]" if t["claimed_by"] else ""
        dep_str = f" (depends: {t['depends_on']})" if t.get("depends_on") else ""
        lines.append(f"{icon} [{t['id']}] {t['title']}{agent}{dep_str}")
        if t.get("result_summary"):
            # show first 120 chars of result
            summary = t["result_summary"][:120].replace("\n", " ")
            lines.append(f"   └─ {summary}...")
    return "\n".join(lines)
