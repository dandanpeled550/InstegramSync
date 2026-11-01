#!/usr/bin/env python3
"""SubagentStop: a builder can't finish while its area's checks fail.

Checks per agent live in .claude/gates.json. A check is skipped (not failed) when its area or tool
doesn't exist yet, so the gate grows with the project. After MAX_BLOCKS failed attempts the agent is
allowed to stop, and must report `Status: blocked` with the failures — this avoids infinite loops.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import block, load_config, log_event, project_dir, read_input  # noqa: E402

MAX_BLOCKS = 3
TAIL_LINES = 60


def tail(text: str, n: int = TAIL_LINES) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:])


def main() -> None:
    data = read_input()
    agent = data.get("agent_type")
    if not agent:
        return
    gates = load_config(data, "gates.json")
    checks = gates.get(agent)
    if not checks:
        return

    root = Path(data.get("cwd") or project_dir(data))
    failures, skipped = [], []
    for check in checks:
        name = check["name"]
        workdir = root / check.get("workdir", ".")
        missing_paths = [p for p in check.get("only_if_exists", []) if not (root / p).exists()]
        missing_tools = [t for t in check.get("requires", []) if shutil.which(t) is None]
        if not workdir.exists() or missing_paths:
            skipped.append(f"{name} (area not created yet)")
            continue
        if missing_tools:
            skipped.append(f"{name} (missing tool: {', '.join(missing_tools)})")
            continue
        try:
            r = subprocess.run(
                check["run"], shell=True, cwd=str(workdir), capture_output=True, text=True,
                timeout=check.get("timeout", 600),
            )
            if r.returncode != 0:
                failures.append((name, check["run"], tail(r.stdout + "\n" + r.stderr)))
        except subprocess.TimeoutExpired:
            failures.append((name, check["run"], "timed out"))

    counter = project_dir(data) / ".claude" / "logs" / f"gate-{agent}-{data.get('agent_id', 'x')}.count"
    if not failures:
        if counter.exists():
            counter.unlink()
        log_event(data, f"GATE PASS {agent} skipped={skipped}")
        return

    counter.parent.mkdir(parents=True, exist_ok=True)
    previous = counter.read_text().strip() if counter.exists() else ""
    attempts = (int(previous) if previous.isdigit() else 0) + 1
    counter.write_text(str(attempts))

    report = "\n\n".join(f"### {name}\n$ {cmd}\n{out}" for name, cmd, out in failures)
    if attempts <= MAX_BLOCKS:
        log_event(data, f"GATE BLOCK {agent} attempt={attempts} failed={[f[0] for f in failures]}")
        block(
            f"Quality gate failed for {agent} (attempt {attempts}/{MAX_BLOCKS}). Fix these before finishing:\n\n"
            f"{report}\n\nSkipped: {', '.join(skipped) or 'none'}.\n"
            f"After {MAX_BLOCKS} failed attempts you'll be allowed to stop — then report `Status: blocked` "
            "with these failures in your handoff."
        )
    log_event(data, f"GATE GAVE UP {agent} failed={[f[0] for f in failures]}")


if __name__ == "__main__":
    main()
