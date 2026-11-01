#!/usr/bin/env python3
"""PreToolUse (Agent|Task): a builder can't be spawned for a milestone that hasn't been approved.

The spawn prompt must say "Milestone: M<n>" (tech-lead puts this in every builder brief — see
docs/AGENTS_PLAN.md §7.2) and .claude/approvals/M<n>.approved must exist (written by the human via
`.claude/bin/approve`, never by an agent — git-guard.py blocks agents from touching it).

architect, researcher and the reviewers plan/verify rather than build, so they're never gated.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import block, project_dir, read_input  # noqa: E402

BUILDERS = {
    "receiver-engineer",
    "data-engineer",
    "pipeline-engineer",
    "ai-engineer",
    "web-engineer",
    "devops-engineer",
    "test-engineer",
}
MILESTONE_RE = re.compile(r"Milestone:\s*(M\d+)")
ASK_MESSAGE = "Present the milestone kickoff brief and ask the human to run .claude/bin/approve M<n>."


def main() -> None:
    data = read_input()
    tool_input = data.get("tool_input") or {}
    if tool_input.get("subagent_type") not in BUILDERS:
        return

    match = MILESTONE_RE.search(tool_input.get("prompt") or "")
    if not match:
        block(ASK_MESSAGE)

    milestone = match.group(1)
    approval = project_dir(data) / ".claude" / "approvals" / f"{milestone}.approved"
    if not approval.exists():
        block(
            f"Present the milestone kickoff brief and ask the human to run .claude/bin/approve {milestone}."
        )


if __name__ == "__main__":
    main()
