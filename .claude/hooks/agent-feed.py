#!/usr/bin/env python3
"""PostToolUse (*) / SubagentStart / SubagentStop: a live, per-agent activity feed for humans to tail.

Only fires when `agent_type` is set (plain human sessions are not logged). Appends one redacted,
content-free line to `.claude/logs/agents/<agent>.log` and `.claude/logs/agents/all.log` — never the
tool's actual file contents, only what it touched. On SubagentStop it also files the subagent's final
message as a handoff under `.claude/logs/handoffs/`.

Never blocks: this is an observability hook, not a guardrail, so it always exits 0.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import SECRET_PATTERNS_COMPILED, project_dir, read_input  # noqa: E402

SUMMARY_MAX = 140
PATH_TOOLS = {"Edit", "Write", "Read", "MultiEdit", "NotebookEdit"}
PATTERN_TOOLS = {"Grep", "Glob"}
SPAWN_TOOLS = {"Agent", "Task"}
URL_TOOLS = {"WebFetch", "WebSearch"}


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def rel_path(raw: str, root: Path) -> str:
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        return raw
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def summarize(tool: str, tool_input: Dict[str, Any], root: Path) -> str:
    if tool == "Bash":
        return truncate((tool_input.get("command") or "").replace("\n", " "), SUMMARY_MAX)
    if tool in PATH_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return rel_path(raw, root)
    if tool in PATTERN_TOOLS:
        return tool_input.get("pattern") or ""
    if tool in SPAWN_TOOLS:
        return f"{tool_input.get('subagent_type') or '?'}: {tool_input.get('description') or ''}"
    if tool in URL_TOOLS:
        return tool_input.get("url") or tool_input.get("query") or ""
    if tool == "Skill":
        return tool_input.get("skill") or ""
    return ""


def redact(line: str) -> str:
    for _name, pattern in SECRET_PATTERNS_COMPILED:
        line = pattern.sub("[REDACTED]", line)
    return line


def append_line(root: Path, agent: str, line: str) -> None:
    log_dir = root / ".claude" / "logs" / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    for name in (f"{agent}.log", "all.log"):
        with open(log_dir / name, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def save_handoff(data: Dict[str, Any], root: Path, agent: str) -> None:
    message = data.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return
    transcript = data.get("agent_transcript_path") or data.get("transcript_path") or "unknown"
    out_dir = root / ".claude" / "logs" / "handoffs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    path = out_dir / f"{stamp}-{agent}.md"
    body = redact(f"agent_transcript_path: {transcript}\n\n{message}\n")
    path.write_text(body, encoding="utf-8")


def main() -> None:
    try:
        data = read_input()
        agent = data.get("agent_type")
        if not agent:
            return

        event = data.get("hook_event_name") or ""
        if event == "PostToolUse":
            tool = data.get("tool_name") or "?"
            summary = summarize(tool, data.get("tool_input") or {}, project_dir(data))
        elif event in ("SubagentStart", "SubagentStop"):
            tool, summary = event, ""
        else:
            return

        root = project_dir(data)
        stamp = datetime.now().strftime("%H:%M:%S")
        line = redact(f"{stamp} {agent} {tool} {summary}".rstrip())
        append_line(root, agent, line)

        if event == "SubagentStop":
            save_handoff(data, root, agent)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
