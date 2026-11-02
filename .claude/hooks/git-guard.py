#!/usr/bin/env python3
"""PreToolUse (Bash): enforce the git workflow (docs/AGENTS_PLAN.md §15.8).

Everyone:   no force push (--force-with-lease is fine), no --no-verify, no deleting dev/main remotely.
Agents:     no commit/merge/rebase/reset --hard on dev/main, no push to dev/main, no branch surgery on
            dev/main, no disabling git hooks, no reading .env files through the shell.
gh:         only tech-lead merges PRs, only with --squash, never into main, never with --admin.
Read-only agents (researcher, reviewers, human-tasks) may only run git/gh and a few read-only utilities.

Best effort: it parses the command text. GitHub branch protection is the backstop.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    PROTECTED_BRANCHES,
    block,
    current_branch,
    path_allowed,
    project_dir,
    read_input,
)

RESTRICTED_SHELL = {
    "researcher": {"git", "gh", "cd"},
    "code-reviewer": {
        "git",
        "gh",
        "cd",
        "head",
        "tail",
        "wc",
        "grep",
        "sort",
        "uniq",
        "jq",
        "ls",
    },
    "security-reviewer": {
        "git",
        "gh",
        "cd",
        "head",
        "tail",
        "wc",
        "grep",
        "sort",
        "uniq",
        "jq",
        "ls",
    },
    "human-tasks": {
        "git",
        "gh",
        "cd",
        "head",
        "tail",
        "wc",
        "grep",
        "sort",
        "uniq",
        "jq",
        "ls",
    },
}
SHELLS = {"bash", "sh", "zsh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
ENV_TOKEN = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_-]+)?$")
APPROVAL_PATHS = (".claude/approvals", ".claude/bin/approve")
# Q2 (docs/tasks/M0.md): all agents share one `gh` identity, so only this hook stops one agent from
# forging another's review verdict, dodging the security gate, or merging a change to its own guardrails.
REVIEW_CONTEXT_OWNER = {
    "agent-review/code": "code-reviewer",
    "agent-review/security": "security-reviewer",
}
SENSITIVE_MERGE_PATHS = (".github/workflows/**", ".claude/**")
GIT_GLOBAL_WITH_ARG = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
}
PUSH_OPTS_WITH_ARG = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
COMMIT_LIKE = {"commit", "merge", "rebase", "cherry-pick", "revert", "am"}


def tokenize(cmd: str) -> list[list[str]]:
    """Split a shell command into segments of tokens, respecting quotes."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""
        tokens = list(lex)
    except ValueError:
        tokens = cmd.split()
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok and set(tok) <= set(";&|"):
            segments.append([])
        else:
            segments[-1].append(tok)
    return [s for s in segments if s]


def program_index(seg: list[str]) -> int:
    i = 0
    while i < len(seg) and (
        ASSIGNMENT.match(seg[i]) or seg[i] in {"env", "command", "time", "nohup"}
    ):
        i += 1
    return i


def strip_ref(ref: str) -> str:
    ref = ref.lstrip("+")
    return ref.removeprefix("refs/heads/")


class Guard:
    def __init__(self, agent: str | None, cwd: Path) -> None:
        self.agent = agent
        self.cwd = cwd

    def deny(self, msg: str) -> None:
        block(f"BLOCKED (git-guard): {msg} See CLAUDE.md → Git rules.")

    def check(self, cmd: str, depth: int = 0) -> None:
        for seg in tokenize(cmd):
            self.check_segment(seg, depth)

    def check_segment(self, seg: list[str], depth: int) -> None:
        start = program_index(seg)
        if start >= len(seg):
            return
        prog = Path(seg[start]).name

        if self.agent in RESTRICTED_SHELL and prog not in RESTRICTED_SHELL[self.agent]:
            self.deny(
                f"{self.agent} may only run: {', '.join(sorted(RESTRICTED_SHELL[self.agent]))} (got '{prog}')."
            )

        if self.agent and any(
            ENV_TOKEN.search(t) and not t.endswith(".env.example") for t in seg
        ):
            self.deny("agents never read or source .env files through the shell.")

        if self.agent and any(p in t for t in seg for p in APPROVAL_PATHS):
            self.deny(
                "agents never touch .claude/approvals or .claude/bin/approve — milestone approval is a "
                "human-only gate. Ask the human to run it."
            )

        if "--no-verify" in seg:
            self.deny("--no-verify skips the safety hooks.")

        # Walk the segment: track `cd`, recurse into `bash -c`, check each git/gh invocation.
        i = start
        while i < len(seg):
            tok = Path(seg[i]).name
            if tok == "cd" and i + 1 < len(seg):
                self.cwd = (self.cwd / seg[i + 1]).resolve()
                i += 2
                continue
            if tok in SHELLS and i + 2 < len(seg) and seg[i + 1] == "-c" and depth < 3:
                self.check(seg[i + 2], depth + 1)
                i += 3
                continue
            if tok in {"git", "gh"}:
                end = i + 1
                while end < len(seg) and Path(seg[end]).name not in {"git", "gh", "cd"}:
                    end += 1
                (self.check_git if tok == "git" else self.check_gh)(seg[i:end])
                i = end
                continue
            i += 1

    # ---- git -----------------------------------------------------------------------------
    def check_git(self, args: list[str]) -> None:
        where = self.cwd
        i = 1
        while i < len(args) and args[i].startswith("-"):
            if args[i] == "-C" and i + 1 < len(args):
                where = (where / args[i + 1]).resolve()
            i += 2 if args[i] in GIT_GLOBAL_WITH_ARG else 1
        if i >= len(args):
            return
        sub, rest = args[i], args[i + 1 :]
        branch = current_branch(where)

        if sub == "commit" and any(
            re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", a)
            for a in rest
            if not a.startswith("--")
        ):
            self.deny("`git commit -n` skips the safety hooks.")

        if sub == "push":
            self.check_push(rest, branch)

        if not self.agent:
            return

        if sub in COMMIT_LIKE and branch in PROTECTED_BRANCHES:
            self.deny(
                f"agents never `git {sub}` on '{branch}'. Create a branch from origin/dev first."
            )
        if sub == "pull" and branch in PROTECTED_BRANCHES and "--ff-only" not in rest:
            self.deny(f"on '{branch}' only `git pull --ff-only` is allowed.")
        if sub == "reset" and "--hard" in rest and branch in PROTECTED_BRANCHES:
            self.deny(f"agents never `git reset --hard` on '{branch}'.")
        if (
            sub == "branch"
            and set(rest)
            & {
                "-D",
                "-d",
                "--delete",
                "-m",
                "-M",
                "--move",
                "-f",
                "--force",
            }
            and set(map(strip_ref, rest)) & PROTECTED_BRANCHES
        ):
            self.deny("agents never delete, move or force-reset dev/main.")
        if (
            sub in {"checkout", "switch"}
            and set(rest) & {"-B", "-C", "--force-create"}
            and set(rest) & PROTECTED_BRANCHES
        ):
            self.deny("agents never recreate dev/main.")
        if sub == "update-ref" and any(
            strip_ref(a) in PROTECTED_BRANCHES for a in rest
        ):
            self.deny("agents never move dev/main with update-ref.")
        if (
            sub == "config"
            and any("hookspath" in a.lower() for a in rest)
            and "--get" not in rest
        ):
            self.deny("agents never change core.hooksPath.")

    def check_push(self, rest: list[str], branch: str | None) -> None:
        positional: list[str] = []
        flags: list[str] = []
        i = 0
        while i < len(rest):
            a = rest[i]
            if a in PUSH_OPTS_WITH_ARG:
                i += 2
                continue
            (flags if a.startswith("-") else positional).append(a)
            i += 1

        force = (
            {"--force", "-f", "--mirror"} & set(flags)
            or any(re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", f) for f in flags)
            or any(p.startswith("+") for p in positional[1:])
        )
        if force:
            self.deny(
                "force pushes are not allowed; use --force-with-lease on your own feature branch."
            )

        refspecs = positional[1:]
        deleting = bool({"--delete", "-d"} & set(flags))
        targets = set()
        for spec in refspecs:
            if ":" in spec:
                src, dst = spec.split(":", 1)
                targets.add(strip_ref(dst or src))
                if not src:
                    deleting = True
            else:
                targets.add(branch if spec == "HEAD" else strip_ref(spec))
        if deleting and targets & PROTECTED_BRANCHES:
            self.deny("dev/main can't be deleted.")

        if not self.agent:
            return
        if {"--all", "--branches"} & set(flags):
            self.deny("agents push only their own branch (no --all).")
        if not refspecs:
            targets.add(branch)
        hit = targets & PROTECTED_BRANCHES
        if hit:
            self.deny(
                f"agents never push to {', '.join(sorted(hit))}. Push your feature branch and open a PR."
            )

    # ---- gh ------------------------------------------------------------------------------
    def check_gh(self, args: list[str]) -> None:
        if not self.agent or len(args) < 3:
            return
        group, action, rest = args[1], args[2], args[3:]

        if (
            group == "secret"
            or group == "variable"
            or (group == "repo" and action in {"delete", "edit", "rename", "archive"})
        ):
            self.deny(f"`gh {group} {action}` is a human gate.")

        if group == "api":
            self.check_gh_api(rest)
        if group == "pr" and action == "edit":
            self.check_pr_edit(rest)

        if group != "pr" or action != "merge":
            return
        if self.agent != "tech-lead":
            self.deny("only tech-lead merges PRs.")
        if "--admin" in rest:
            self.deny("--admin bypasses branch protection.")
        if "--squash" not in rest and "-s" not in rest:
            self.deny(
                "feature PRs are squash-merged into dev: use `gh pr merge <n> --squash --delete-branch`."
            )
        pr = next((a for a in rest if not a.startswith("-")), None)
        base = self.pr_base(pr)
        if base is None:
            self.deny("couldn't confirm the PR's base branch; merge refused.")
        if base == "main":
            self.deny("only the human merges into main.")
        files = self.pr_files(pr)
        if files is None:
            self.deny("couldn't confirm the PR's changed files; merge refused.")
        if any(path_allowed(f, SENSITIVE_MERGE_PATHS) for f in files):
            self.deny(
                "PRs touching .github/workflows/** or .claude/** need a human to merge — agents never "
                "merge changes to their own guardrails or CI (Q2, docs/tasks/M0.md)."
            )

    def check_gh_api(self, rest: list[str]) -> None:
        context = next(
            (a.split("=", 1)[1] for a in rest if a.startswith("context=")), None
        )
        if context is None:
            return
        owner = REVIEW_CONTEXT_OWNER.get(context)
        if owner is not None and self.agent != owner:
            self.deny(f"only {owner} may set the '{context}' status.")

    def check_pr_edit(self, rest: list[str]) -> None:
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok == "--remove-label" and i + 1 < len(rest):
                value, i = rest[i + 1], i + 2
            elif tok.startswith("--remove-label="):
                value, i = tok.split("=", 1)[1], i + 1
            else:
                i += 1
                continue
            labels = {label.strip() for label in value.split(",")}
            if "security" in labels and self.agent != "security-reviewer":
                self.deny(
                    "only security-reviewer may remove the 'security' label (Q2, docs/tasks/M0.md)."
                )

    def pr_files(self, pr: str | None) -> list[str] | None:
        cmd = [
            "gh",
            "pr",
            "view",
            *([pr] if pr else []),
            "--json",
            "files",
            "-q",
            ".files[].path",
        ]
        try:
            r = subprocess.run(
                cmd,
                check=False,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:  # noqa: BLE001 — best effort, see module docstring
            return None
        if r.returncode != 0:
            return None
        return [line for line in r.stdout.splitlines() if line]

    def pr_base(self, pr: str | None) -> str | None:
        cmd = [
            "gh",
            "pr",
            "view",
            *([pr] if pr else []),
            "--json",
            "baseRefName",
            "-q",
            ".baseRefName",
        ]
        try:
            r = subprocess.run(
                cmd,
                check=False,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:  # noqa: BLE001 — best effort, see module docstring
            return None
        if r.returncode != 0:
            return None
        return r.stdout.strip() or None


def main() -> None:
    data = read_input()
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return
    Guard(data.get("agent_type"), Path(data.get("cwd") or project_dir(data))).check(cmd)


if __name__ == "__main__":
    main()
