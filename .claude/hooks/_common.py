"""Shared helpers for Insta Saver's Claude Code hooks (stdlib only, Python 3.9+)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROTECTED_BRANCHES = {"main", "dev"}


def read_input() -> Dict[str, Any]:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def block(message: str) -> None:
    """Exit code 2 blocks the tool call; stderr is shown to the agent."""
    print(message, file=sys.stderr)
    sys.exit(2)


def project_dir(data: Dict[str, Any]) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())


def load_config(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    path = project_dir(data) / ".claude" / name
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def real(path: Path) -> Path:
    return Path(os.path.realpath(str(path)))


def nearest_existing_dir(path: Path) -> Path:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return p if p.is_dir() else p.parent


def git(args: List[str], cwd: Path, timeout: int = 15) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout
        )
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_toplevel(path: Path) -> Optional[Path]:
    out = git(["rev-parse", "--show-toplevel"], nearest_existing_dir(path))
    return real(Path(out)) if out else None


def git_common_dir(path: Path) -> Optional[Path]:
    start = nearest_existing_dir(path)
    out = git(["rev-parse", "--git-common-dir"], start)
    if not out:
        return None
    p = Path(out)
    return real(p if p.is_absolute() else start / p)


def current_branch(cwd: Path) -> Optional[str]:
    return git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)


def is_temp_path(path: Path) -> bool:
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/private/var/folders"}
    s = str(path)
    return any(s == r or s.startswith(r.rstrip("/") + "/") for r in map(lambda x: str(real(Path(x))), roots))


def glob_to_regex(pattern: str) -> "re.Pattern[str]":
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def path_allowed(rel: str, patterns: List[str]) -> bool:
    """Positive globs grant access; globs starting with '!' carve out exceptions."""
    allowed = any(glob_to_regex(p).match(rel) for p in patterns if not p.startswith("!"))
    denied = any(glob_to_regex(p[1:]).match(rel) for p in patterns if p.startswith("!"))
    return allowed and not denied


def log_event(data: Dict[str, Any], message: str) -> None:
    try:
        log_dir = project_dir(data) / ".claude" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_dir / "activity.log", "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except Exception:
        pass
