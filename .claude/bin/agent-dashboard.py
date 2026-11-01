#!/usr/bin/env python3
"""Live status dashboard for `.claude/bin/agent-watch` (its default, no-arg mode): one row per
agent, redrawn in place, showing current status / last action / elapsed time instead of a
scrolling log — answers "what is each sub-agent doing right now" at a glance.

Reads .claude/logs/agents/all.log (written by .claude/hooks/agent-feed.py) via `tail -F`, so it
picks up new lines the moment a hook writes them; nothing here writes to that file.

Known limitation: a row is keyed by agent type, not agent_id, so two concurrent instances of the
same type (e.g. two pipeline-engineer builders in parallel worktrees) collapse into one row —
the log lines don't carry agent_id (see .claude/hooks/agent-feed.py), only the type.
"""

from __future__ import annotations

import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

REFRESH_SECONDS = 1.0
ACTION_WIDTH = 48
DIM = "\033[2m"
GREEN = "\033[32m"
RESET = "\033[0m"
CLEAR_HOME = "\033[H\033[2J"


def roster(root: Path) -> list:
    agents_dir = root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.md"))


def parse_line(line: str) -> Optional[tuple]:
    parts = line.rstrip("\n").split(" ", 3)
    if len(parts) < 3:
        return None
    _stamp, agent, tool = parts[0], parts[1], parts[2]
    summary = parts[3] if len(parts) > 3 else ""
    return agent, tool, summary


def fmt_elapsed(since: datetime, suffix: str = "") -> str:
    secs = max(0, int((datetime.now() - since).total_seconds()))
    if secs < 60:
        return f"{secs}s{suffix}"
    minutes, secs = divmod(secs, 60)
    if minutes < 60:
        return f"{minutes}:{secs:02d}{suffix}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}{suffix}"


def new_entry() -> dict:
    return {"status": "not_started", "last_action": "", "since": None}


def apply_event(state: dict, agent: str, tool: str, summary: str) -> None:
    entry = state.setdefault(agent, new_entry())
    now = datetime.now()
    if tool == "SubagentStart":
        entry["status"] = "running"
        entry["since"] = now
        entry["last_action"] = "spawned"
    elif tool == "SubagentStop":
        entry["status"] = "idle"
        entry["since"] = now
        entry["last_action"] = "finished"
    else:
        entry["last_action"] = f"{tool}: {summary}" if summary else tool
        if entry["status"] != "running":
            entry["status"] = "running"
            entry["since"] = entry["since"] or now


STATUS_ORDER = {"running": 0, "idle": 1, "not_started": 2}
STATUS_STYLE = {
    "running": ("●", "running", GREEN),
    "idle": ("✓", "idle", DIM),
    "not_started": ("—", "not started", DIM),
}


def render(state: dict) -> str:
    rows = sorted(state.items(), key=lambda kv: (STATUS_ORDER[kv[1]["status"]], kv[0]))
    name_width = max([len("AGENT")] + [len(name) for name in state])

    lines = [CLEAR_HOME]
    header = f"{'AGENT':<{name_width}}  {'STATUS':<11}  {'LAST ACTION':<{ACTION_WIDTH}}  ELAPSED"
    lines.append(header)
    lines.append("─" * len(header))

    for name, info in rows:
        status = info["status"]
        icon, label, color = STATUS_STYLE[status]

        action = info["last_action"] or ("not started yet" if status == "not_started" else "")
        if len(action) > ACTION_WIDTH:
            action = action[: ACTION_WIDTH - 1] + "…"

        if status == "running" and info["since"]:
            elapsed = fmt_elapsed(info["since"])
        elif status == "idle" and info["since"]:
            elapsed = fmt_elapsed(info["since"], " ago")
        else:
            elapsed = "—"

        name_field = f"{icon} {name}"
        lines.append(
            f"{color}{name_field:<{name_width + 2}}  {label:<11}  {action:<{ACTION_WIDTH}}  {elapsed}{RESET}"
        )

    lines.append("")
    lines.append(f"{DIM}Ctrl-C to exit · agent-watch <agent> for history · agent-watch handoffs{RESET}")
    return "\n".join(lines) + "\n"


def drain(q: "queue.Queue[str]", state: dict) -> None:
    while True:
        try:
            line = q.get_nowait()
        except queue.Empty:
            return
        parsed = parse_line(line)
        if parsed:
            apply_event(state, *parsed)


def pump(proc: subprocess.Popen, q: "queue.Queue[str]") -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        q.put(line)


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    log_dir = root / ".claude" / "logs" / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    all_log = log_dir / "all.log"
    all_log.touch()

    state = {name: new_entry() for name in roster(root)}

    proc = subprocess.Popen(
        ["tail", "-F", "-n", "0", str(all_log)], stdout=subprocess.PIPE, text=True, bufsize=1
    )
    event_queue: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=pump, args=(proc, event_queue), daemon=True).start()

    try:
        while True:
            drain(event_queue, state)
            sys.stdout.write(render(state))
            sys.stdout.flush()
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
