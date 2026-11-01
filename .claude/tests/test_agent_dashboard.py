"""Tests for .claude/bin/agent-dashboard.py's pure logic: line parsing, state transitions, and
rendering. The live tail/redraw loop in main() isn't exercised here (it owns a subprocess and an
infinite loop); it was verified manually by appending to a real log and watching the dashboard
update, including that Ctrl-C/SIGTERM both clean up the `tail -F` child process.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timedelta
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
_spec = importlib.util.spec_from_file_location("agent_dashboard", BIN_DIR / "agent-dashboard.py")
agent_dashboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_dashboard)


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def test_parse_line_with_summary() -> None:
    line = "10:00:01 pipeline-engineer Bash pytest -q tests/pipeline\n"
    assert agent_dashboard.parse_line(line) == ("pipeline-engineer", "Bash", "pytest -q tests/pipeline")


def test_parse_line_without_summary() -> None:
    line = "10:00:00 pipeline-engineer SubagentStart\n"
    assert agent_dashboard.parse_line(line) == ("pipeline-engineer", "SubagentStart", "")


def test_parse_line_too_few_fields_returns_none() -> None:
    assert agent_dashboard.parse_line("10:00:00 pipeline-engineer\n") is None
    assert agent_dashboard.parse_line("\n") is None


def test_apply_event_start_sets_running() -> None:
    state: dict = {}
    agent_dashboard.apply_event(state, "ai-engineer", "SubagentStart", "")
    assert state["ai-engineer"]["status"] == "running"
    assert state["ai-engineer"]["last_action"] == "spawned"


def test_apply_event_stop_sets_idle() -> None:
    state: dict = {}
    agent_dashboard.apply_event(state, "ai-engineer", "SubagentStart", "")
    agent_dashboard.apply_event(state, "ai-engineer", "SubagentStop", "")
    assert state["ai-engineer"]["status"] == "idle"
    assert state["ai-engineer"]["last_action"] == "finished"


def test_apply_event_tool_call_sets_running_and_last_action() -> None:
    state: dict = {}
    agent_dashboard.apply_event(state, "web-engineer", "Bash", "npm test")
    assert state["web-engineer"]["status"] == "running"
    assert state["web-engineer"]["last_action"] == "Bash: npm test"


def test_apply_event_preserves_since_across_tool_calls() -> None:
    state: dict = {}
    agent_dashboard.apply_event(state, "web-engineer", "SubagentStart", "")
    start_time = state["web-engineer"]["since"]
    agent_dashboard.apply_event(state, "web-engineer", "Bash", "npm test")
    assert state["web-engineer"]["since"] == start_time


def test_fmt_elapsed_seconds_minutes_hours() -> None:
    now = datetime.now()
    assert agent_dashboard.fmt_elapsed(now - timedelta(seconds=5)) == "5s"
    assert agent_dashboard.fmt_elapsed(now - timedelta(seconds=90)) == "1:30"
    assert agent_dashboard.fmt_elapsed(now - timedelta(hours=1, minutes=2, seconds=3)) == "1:02:03"
    assert agent_dashboard.fmt_elapsed(now - timedelta(seconds=5), " ago") == "5s ago"


def test_render_sorts_running_before_idle_before_not_started() -> None:
    state = {
        "architect": agent_dashboard.new_entry(),
        "ai-engineer": {"status": "running", "last_action": "Bash: x", "since": datetime.now()},
        "pipeline-engineer": {"status": "idle", "last_action": "finished", "since": datetime.now()},
    }
    clean = strip_ansi(agent_dashboard.render(state))
    assert clean.index("ai-engineer") < clean.index("pipeline-engineer") < clean.index("architect")


def test_render_truncates_long_action() -> None:
    state = {"devops-engineer": {"status": "running", "last_action": "Bash: " + "x" * 100, "since": datetime.now()}}
    clean = strip_ansi(agent_dashboard.render(state))
    line = next(l for l in clean.splitlines() if "devops-engineer" in l)
    assert "…" in line
    assert "x" * 100 not in line


def test_render_shows_not_started_agents() -> None:
    state = {"architect": agent_dashboard.new_entry()}
    clean = strip_ansi(agent_dashboard.render(state))
    assert "not started" in clean
