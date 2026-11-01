#!/usr/bin/env python3
"""PreToolUse (Edit|Write|MultiEdit|NotebookEdit): an agent may only write files it owns.

Ownership lives in .claude/ownership.json. Sessions without an agent_type (a human driving plain
`claude`) are not restricted. Paths nobody owns — .claude/**, CLAUDE.md, LICENSE — are human-only,
so agents can't loosen their own guardrails.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    block,
    git_common_dir,
    git_toplevel,
    is_temp_path,
    load_config,
    path_allowed,
    project_dir,
    read_input,
    real,
)


def main() -> None:
    data = read_input()
    agent = data.get("agent_type")
    if not agent:
        return

    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return

    path = Path(raw)
    if not path.is_absolute():
        path = Path(data.get("cwd") or project_dir(data)) / path
    path = real(path)

    if is_temp_path(path):
        return

    top = git_toplevel(path)
    project_common = git_common_dir(project_dir(data))
    if top is None or project_common is None or git_common_dir(top) != project_common:
        block(
            f"BLOCKED (ownership): {agent} may not write outside this repository: {path}. "
            "Use a temp directory for scratch files."
        )

    rel = path.relative_to(top).as_posix()

    for memory_root in (".claude/agent-memory/", ".claude/agent-memory-local/"):
        if rel.startswith(f"{memory_root}{agent}/"):
            return

    ownership = load_config(data, "ownership.json")
    owners = {k: v for k, v in ownership.items() if not k.startswith("_")}

    if agent not in owners:
        block(
            f"BLOCKED (ownership): agent '{agent}' is not registered in .claude/ownership.json, "
            "so it can't write files in this repo. Delegate to the owning agent instead."
        )

    if path_allowed(rel, owners[agent]):
        return

    owner = next((name for name, globs in owners.items() if path_allowed(rel, globs)), None)
    block(
        f"BLOCKED (ownership): {agent} may not edit '{rel}'. "
        f"Owner: {owner or 'humans only'}. "
        "Don't work around this — describe the change you need under 'Needs from others' in your handoff."
    )


if __name__ == "__main__":
    main()
