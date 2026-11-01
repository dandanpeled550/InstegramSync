"""Tests for .claude/hooks/*.py.

Each hook is invoked as a real subprocess (synthetic JSON on stdin, exactly like Claude Code's hook
runner), never imported, so these exercise the actual contract. Hooks that read/write under the repo
root (ownership, gates, approvals, logs) are run from a throwaway temp git repo with its own copy of
.claude/hooks/* — project_dir() in _common.py derives the root from each hook file's own location, so
copying the hooks there makes them behave exactly as they would inside a real git worktree, and keeps
every test isolated from this real repo's state.

git-guard.py doesn't need the copied-hooks trick (it uses tool_input.cwd directly), but it still gets a
throwaway repo per test so branch-protection checks never touch this repo's real branches.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REAL_HOOKS_DIR = TESTS_DIR.parent / "hooks"
# _common.is_temp_path() treats the OS tempdir (and pytest's tmp_path, which lives under it on macOS)
# as scratch space that ownership/secret-scan skip on purpose. Throwaway repos need to live somewhere
# that isn't exempt, so hook enforcement actually runs during the test.
SCRATCH_BASE = TESTS_DIR / ".tmp"


def git(args, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def hook_repo():
    SCRATCH_BASE.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(dir=SCRATCH_BASE))
    try:
        hooks_dst = repo / ".claude" / "hooks"
        hooks_dst.mkdir(parents=True)
        for f in REAL_HOOKS_DIR.glob("*.py"):
            shutil.copy(f, hooks_dst / f.name)

        git(["init", "-q", "-b", "main"], repo)
        git(["config", "user.email", "test@example.com"], repo)
        git(["config", "user.name", "Test"], repo)
        (repo / "README.md").write_text("fixture repo\n")
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", "init"], repo)
        yield repo
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def run_hook(
    repo: Path,
    hook_name: str,
    data: Dict[str, Any],
    cwd: Optional[Path] = None,
    raw_stdin: Optional[str] = None,
) -> subprocess.CompletedProcess:
    hook_path = repo / ".claude" / "hooks" / hook_name
    return subprocess.run(
        [sys.executable, str(hook_path)],
        input=raw_stdin if raw_stdin is not None else json.dumps(data),
        cwd=str(cwd or repo),
        capture_output=True,
        text=True,
        timeout=30,
    )


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------------------------------
# enforce-ownership.py
# ---------------------------------------------------------------------------------------------------

OWNERSHIP = {
    "_comment": "fixture",
    "alpha-engineer": ["alpha/**"],
    "beta-engineer": ["beta/**"],
    "code-reviewer": [],
}


def test_ownership_allows_agent_in_its_own_glob(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "ownership.json", OWNERSHIP)
    r = run_hook(
        hook_repo,
        "enforce-ownership.py",
        {"agent_type": "alpha-engineer", "cwd": str(hook_repo), "tool_input": {"file_path": "alpha/x.py"}},
    )
    assert r.returncode == 0, r.stderr


def test_ownership_blocks_agent_outside_its_glob(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "ownership.json", OWNERSHIP)
    r = run_hook(
        hook_repo,
        "enforce-ownership.py",
        {"agent_type": "alpha-engineer", "cwd": str(hook_repo), "tool_input": {"file_path": "beta/x.py"}},
    )
    assert r.returncode == 2
    assert "beta-engineer" in r.stderr


def test_ownership_blocks_unregistered_agent(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "ownership.json", OWNERSHIP)
    r = run_hook(
        hook_repo,
        "enforce-ownership.py",
        {"agent_type": "ghost-engineer", "cwd": str(hook_repo), "tool_input": {"file_path": "alpha/x.py"}},
    )
    assert r.returncode == 2
    assert "not registered" in r.stderr


def test_ownership_allows_human_anywhere(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "ownership.json", OWNERSHIP)
    r = run_hook(
        hook_repo,
        "enforce-ownership.py",
        {"cwd": str(hook_repo), "tool_input": {"file_path": "beta/x.py"}},
    )
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------------------------------
# secret-scan.py
# ---------------------------------------------------------------------------------------------------

FAKE_TOKEN = "ghp_" + "a" * 36


def test_secret_scan_blocks_credential_looking_content(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "secret-scan.py",
        {
            "agent_type": "devops-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"file_path": "config.py", "content": f"TOKEN = '{FAKE_TOKEN}'"},
        },
    )
    assert r.returncode == 2
    assert "credential" in r.stderr


def test_secret_scan_allows_clean_content(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "secret-scan.py",
        {
            "agent_type": "devops-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"file_path": "config.py", "content": "DEBUG = True"},
        },
    )
    assert r.returncode == 0, r.stderr


def test_secret_scan_blocks_env_file_from_agent(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "secret-scan.py",
        {
            "agent_type": "devops-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"file_path": ".env", "content": "FOO=bar"},
        },
    )
    assert r.returncode == 2
    assert "env files" in r.stderr


def test_secret_scan_allows_env_example(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "secret-scan.py",
        {
            "agent_type": "devops-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"file_path": ".env.example", "content": "FOO=placeholder"},
        },
    )
    assert r.returncode == 0, r.stderr


def test_secret_scan_allows_human_writing_secret_to_ignored_file(hook_repo: Path) -> None:
    (hook_repo / ".gitignore").write_text("*.local\n")
    git(["add", "-A"], hook_repo)
    git(["commit", "-q", "-m", "gitignore"], hook_repo)
    r = run_hook(
        hook_repo,
        "secret-scan.py",
        {"cwd": str(hook_repo), "tool_input": {"file_path": "secret.local", "content": FAKE_TOKEN}},
    )
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------------------------------
# git-guard.py
# ---------------------------------------------------------------------------------------------------


def test_git_guard_blocks_commit_on_main(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {"agent_type": "pipeline-engineer", "cwd": str(hook_repo), "tool_input": {"command": "git commit -am x"}},
    )
    assert r.returncode == 2
    assert "main" in r.stderr


def test_git_guard_allows_commit_on_feature_branch(hook_repo: Path) -> None:
    git(["checkout", "-q", "-b", "feat/x"], hook_repo)
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {"agent_type": "pipeline-engineer", "cwd": str(hook_repo), "tool_input": {"command": "git commit -am x"}},
    )
    assert r.returncode == 0, r.stderr


def test_git_guard_blocks_push_to_main(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {
            "agent_type": "pipeline-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"command": "git push origin main"},
        },
    )
    assert r.returncode == 2
    assert "main" in r.stderr


def test_git_guard_blocks_force_push_even_without_agent(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {"cwd": str(hook_repo), "tool_input": {"command": "git push --force origin feat/x"}},
    )
    assert r.returncode == 2
    assert "force" in r.stderr


def test_git_guard_blocks_no_verify(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {
            "agent_type": "pipeline-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"command": "git commit --no-verify -am x"},
        },
    )
    assert r.returncode == 2
    assert "no-verify" in r.stderr


def test_git_guard_blocks_agent_reading_approvals(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {
            "agent_type": "tech-lead",
            "cwd": str(hook_repo),
            "tool_input": {"command": "cat .claude/approvals/M1.approved"},
        },
    )
    assert r.returncode == 2
    assert "approvals" in r.stderr


def test_git_guard_blocks_agent_running_approve(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {
            "agent_type": "pipeline-engineer",
            "cwd": str(hook_repo),
            "tool_input": {"command": ".claude/bin/approve M1"},
        },
    )
    assert r.returncode == 2
    assert "approve" in r.stderr


def test_git_guard_allows_human_running_approve(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {"cwd": str(hook_repo), "tool_input": {"command": ".claude/bin/approve M1 looks good"}},
    )
    assert r.returncode == 0, r.stderr


def test_git_guard_restricts_researcher_shell(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "git-guard.py",
        {"agent_type": "researcher", "cwd": str(hook_repo), "tool_input": {"command": "rm -rf alpha/"}},
    )
    assert r.returncode == 2
    assert "may only run" in r.stderr


# ---------------------------------------------------------------------------------------------------
# quality-gate.py
# ---------------------------------------------------------------------------------------------------


def test_quality_gate_passes_when_checks_pass(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "gates.json", {"fake-agent": [{"name": "ok", "run": "true"}]})
    r = run_hook(
        hook_repo,
        "quality-gate.py",
        {"agent_type": "fake-agent", "agent_id": "a1", "cwd": str(hook_repo)},
    )
    assert r.returncode == 0, r.stderr


def test_quality_gate_blocks_on_failing_check(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "gates.json", {"fake-agent": [{"name": "boom", "run": "false"}]})
    r = run_hook(
        hook_repo,
        "quality-gate.py",
        {"agent_type": "fake-agent", "agent_id": "a2", "cwd": str(hook_repo)},
    )
    assert r.returncode == 2
    assert "boom" in r.stderr
    assert (hook_repo / ".claude" / "logs" / "gate-fake-agent-a2.count").read_text().strip() == "1"


def test_quality_gate_gives_up_after_max_blocks(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "gates.json", {"fake-agent": [{"name": "boom", "run": "false"}]})
    data = {"agent_type": "fake-agent", "agent_id": "a3", "cwd": str(hook_repo)}
    results = [run_hook(hook_repo, "quality-gate.py", data) for _ in range(4)]
    assert [r.returncode for r in results] == [2, 2, 2, 0]


def test_quality_gate_skips_check_when_area_missing(hook_repo: Path) -> None:
    write_json(
        hook_repo / ".claude" / "gates.json",
        {"fake-agent": [{"name": "skip me", "only_if_exists": ["nope"], "run": "false"}]},
    )
    r = run_hook(
        hook_repo,
        "quality-gate.py",
        {"agent_type": "fake-agent", "agent_id": "a4", "cwd": str(hook_repo)},
    )
    assert r.returncode == 0, r.stderr


def test_quality_gate_noop_for_agent_without_checks(hook_repo: Path) -> None:
    write_json(hook_repo / ".claude" / "gates.json", {"fake-agent": [{"name": "boom", "run": "false"}]})
    r = run_hook(
        hook_repo,
        "quality-gate.py",
        {"agent_type": "other-agent", "agent_id": "a5", "cwd": str(hook_repo)},
    )
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------------------------------
# milestone-gate.py
# ---------------------------------------------------------------------------------------------------


def spawn(subagent_type: str, prompt: str) -> Dict[str, Any]:
    return {"tool_input": {"subagent_type": subagent_type, "prompt": prompt}}


def test_milestone_gate_blocks_builder_without_milestone_line(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "milestone-gate.py", spawn("pipeline-engineer", "Do the thing"))
    assert r.returncode == 2
    assert "approve" in r.stderr


def test_milestone_gate_blocks_builder_without_approval_file(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "milestone-gate.py", spawn("pipeline-engineer", "Milestone: M1\nDo the thing"))
    assert r.returncode == 2
    assert "M1" in r.stderr


def test_milestone_gate_allows_builder_once_approved(hook_repo: Path) -> None:
    approvals = hook_repo / ".claude" / "approvals"
    approvals.mkdir(parents=True)
    (approvals / "M1.approved").write_text("approved_at=now\n")
    r = run_hook(hook_repo, "milestone-gate.py", spawn("pipeline-engineer", "Milestone: M1\nDo the thing"))
    assert r.returncode == 0, r.stderr


def test_milestone_gate_never_gates_architect(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "milestone-gate.py", spawn("architect", "Write the contract"))
    assert r.returncode == 0, r.stderr


def test_milestone_gate_never_gates_reviewers(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "milestone-gate.py", spawn("code-reviewer", "Review this PR"))
    assert r.returncode == 0, r.stderr


def test_milestone_gate_ignores_non_spawn_subagent_types(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "milestone-gate.py", {"tool_input": {}})
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------------------------------
# agent-feed.py
# ---------------------------------------------------------------------------------------------------


def read_all_log(repo: Path) -> str:
    path = repo / ".claude" / "logs" / "agents" / "all.log"
    return path.read_text() if path.exists() else ""


def test_agent_feed_writes_per_agent_and_all_log(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "agent-feed.py",
        {
            "hook_event_name": "PostToolUse",
            "agent_type": "pipeline-engineer",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q tests/pipeline"},
        },
    )
    assert r.returncode == 0, r.stderr
    all_log = read_all_log(hook_repo)
    agent_log = (hook_repo / ".claude" / "logs" / "agents" / "pipeline-engineer.log").read_text()
    for text in (all_log, agent_log):
        assert "pipeline-engineer Bash pytest -q tests/pipeline" in text


def test_agent_feed_redacts_secret_in_command(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "agent-feed.py",
        {
            "hook_event_name": "PostToolUse",
            "agent_type": "devops-engineer",
            "tool_name": "Bash",
            "tool_input": {"command": f"echo {FAKE_TOKEN}"},
        },
    )
    assert r.returncode == 0, r.stderr
    log = read_all_log(hook_repo)
    assert FAKE_TOKEN not in log
    assert "[REDACTED]" in log


def test_agent_feed_skips_when_no_agent_type(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "agent-feed.py",
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert r.returncode == 0, r.stderr
    assert not (hook_repo / ".claude" / "logs" / "agents").exists()


def test_agent_feed_exits_zero_on_malformed_input(hook_repo: Path) -> None:
    r = run_hook(hook_repo, "agent-feed.py", {}, raw_stdin="not json at all")
    assert r.returncode == 0, r.stderr


def test_agent_feed_saves_redacted_handoff_on_subagent_stop(hook_repo: Path) -> None:
    r = run_hook(
        hook_repo,
        "agent-feed.py",
        {
            "hook_event_name": "SubagentStop",
            "agent_type": "devops-engineer",
            "last_assistant_message": f"Done. token={FAKE_TOKEN}",
            "agent_transcript_path": "/tmp/fake-transcript.jsonl",
        },
    )
    assert r.returncode == 0, r.stderr
    handoffs = list((hook_repo / ".claude" / "logs" / "handoffs").glob("*-devops-engineer.md"))
    assert len(handoffs) == 1
    body = handoffs[0].read_text()
    assert body.startswith("agent_transcript_path: /tmp/fake-transcript.jsonl")
    assert FAKE_TOKEN not in body
    assert "[REDACTED]" in body
