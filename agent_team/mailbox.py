"""
Mailbox — Direct agent-to-agent messaging.

Implements the Claude Code Agent Teams communication model:
- Any agent can send a message to any other agent by name
- Messages are delivered automatically (no human relay)
- Broadcast: send to all agents simultaneously
- Each agent has its own inbox file (one file per agent = no contention)
- Agents poll their inbox before each turn to see new messages
"""

import json
import os
import fcntl
from datetime import datetime

MAILBOX_DIR = os.path.join(os.path.dirname(__file__), "shared", "mailboxes")


def _inbox_path(agent_name: str) -> str:
    os.makedirs(MAILBOX_DIR, exist_ok=True)
    safe = agent_name.lower().replace(" ", "_")
    return os.path.join(MAILBOX_DIR, f"{safe}.json")


def send(from_agent: str, to_agent: str, message: str, subject: str = ""):
    """Send a direct message from one agent to another."""
    path = _inbox_path(to_agent)
    msg = {
        "from": from_agent,
        "to": to_agent,
        "subject": subject,
        "message": message,
        "sent_at": datetime.now().isoformat(),
        "read": False,
    }
    _append_message(path, msg)


def broadcast(from_agent: str, all_agents: list[str], message: str, subject: str = ""):
    """Send the same message to all agents simultaneously."""
    for agent in all_agents:
        if agent != from_agent:
            send(from_agent, agent, message, subject=f"[BROADCAST] {subject}")


def read_inbox(agent_name: str, mark_read: bool = True) -> list[dict]:
    """Read all messages in an agent's inbox. Marks them as read by default."""
    path = _inbox_path(agent_name)
    if not os.path.exists(path):
        return []
    with open(path, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read().strip()
        messages = json.loads(content) if content else []
        if mark_read:
            for m in messages:
                m["read"] = True
            f.seek(0)
            f.truncate()
            f.write(json.dumps(messages, indent=2, ensure_ascii=False))
            f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return messages


def unread_messages(agent_name: str) -> list[dict]:
    """Return only unread messages without marking them read."""
    return [m for m in read_inbox(agent_name, mark_read=False) if not m.get("read")]


def format_inbox(messages: list[dict]) -> str:
    """Format inbox messages for inclusion in an agent's context."""
    if not messages:
        return ""
    lines = ["--- INCOMING MESSAGES ---"]
    for m in messages:
        lines.append(f"FROM: {m['from']}  |  {m['sent_at'][:16]}")
        if m.get("subject"):
            lines.append(f"SUBJECT: {m['subject']}")
        lines.append(m["message"])
        lines.append("---")
    return "\n".join(lines)


def _append_message(path: str, msg: dict):
    """Append a message to an inbox file under exclusive lock."""
    if os.path.exists(path):
        with open(path, "r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            content = f.read().strip()
            messages = json.loads(content) if content else []
            messages.append(msg)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(messages, indent=2, ensure_ascii=False))
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
    else:
        with open(path, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps([msg], indent=2, ensure_ascii=False))
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
