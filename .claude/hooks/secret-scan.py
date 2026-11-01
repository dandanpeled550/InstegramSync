#!/usr/bin/env python3
"""PreToolUse (Edit|Write|MultiEdit|NotebookEdit): keep secrets out of a public repo.

- Agents may never write `.env*` files (except `.env.example`).
- Content that looks like a credential is blocked inside the repo. Humans may still write it into a
  gitignored file (e.g. `.env.local`). A line containing `pragma: allowlist secret` is exempt.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import block, git, git_toplevel, is_temp_path, project_dir, read_input, real  # noqa: E402

PATTERNS = [
    ("Meta/Facebook access token", r"EAA[A-Za-z0-9]{30,}"),
    ("Instagram access token", r"IG(?:AA|QV|QW)[A-Za-z0-9_\-]{30,}"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI-style secret key", r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ("Supabase secret key", r"sb_secret_[A-Za-z0-9_\-]{20,}"),
    ("Private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("JWT (e.g. Supabase service-role key)", r"eyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{20,}"),
]
COMPILED = [(name, re.compile(rx)) for name, rx in PATTERNS]
ENV_FILE = re.compile(r"^\.env(\..+)?$")


def new_text(tool_input: dict) -> str:
    parts = [tool_input.get("content"), tool_input.get("new_string"), tool_input.get("new_source")]
    for edit in tool_input.get("edits") or []:
        parts.append(edit.get("new_string"))
    return "\n".join(p for p in parts if isinstance(p, str))


def main() -> None:
    data = read_input()
    agent = data.get("agent_type")
    tool_input = data.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return

    path = Path(raw)
    if not path.is_absolute():
        path = Path(data.get("cwd") or project_dir(data)) / path
    path = real(path)

    if agent and ENV_FILE.match(path.name) and path.name != ".env.example":
        block(f"BLOCKED (secrets): agents never write env files ({path.name}). Only .env.example, with placeholders.")

    if is_temp_path(path):
        return
    top = git_toplevel(path)
    if top is None:
        return

    hits = []
    for line in new_text(tool_input).splitlines():
        if "pragma: allowlist secret" in line:
            continue
        hits.extend(name for name, rx in COMPILED if rx.search(line))
    if not hits:
        return

    ignored = git(["check-ignore", "-q", str(path)], top) is not None
    if not agent and ignored:
        return

    kinds = ", ".join(sorted(set(hits)))
    block(
        f"BLOCKED (secrets): the content for {path.name} looks like it contains a credential ({kinds}). "
        "This repo is public. Read secrets from the environment instead; use obvious placeholders in "
        "examples and fixtures. Do not print or repeat the value."
    )


if __name__ == "__main__":
    main()
