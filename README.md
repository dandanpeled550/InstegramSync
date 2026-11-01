# Insta Saver

Save Instagram recipes and travel spots by sharing them to a bot account. Each post is categorized
(food / travel), titled, and made searchable on a private web page.

```
Instagram share → bot DM → Supabase Edge Function (always on, free)
                              → Postgres queue → laptop worker (Jev + Gemini) → searchable web page
```

| Doc | What's in it |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | Product + architecture plan |
| [docs/AGENTS_PLAN.md](docs/AGENTS_PLAN.md) | How the project is built by a team of Claude Code sub-agents |
| [CLAUDE.md](CLAUDE.md) | Rules every agent follows |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow for humans |
| [docs/tasks/](docs/tasks/) | Milestone task boards |

## Status

**M0 — setup** in progress. See [docs/tasks/M0.md](docs/tasks/M0.md).

## Working on it

```bash
claude --agent tech-lead
```

Then ask it to run `/milestone M0`. The tech lead plans tasks, delegates them to specialist agents,
and stops for your approval at every human gate.

## Watching the agents

Every sub-agent writes a line per tool call to `.claude/logs/agents/<agent>.log` and
`.claude/logs/agents/all.log` (`.claude/hooks/agent-feed.py`), and its final message to a file under
`.claude/logs/handoffs/` when it finishes. None of this is git-tracked — it's local, live state.

**Ghostty layout.** Run `tech-lead` in the main pane, then split panes for the feed:

| Pane | Command | Shows |
|---|---|---|
| Main | `claude --agent tech-lead` | the orchestrator you're driving |
| Split (`Cmd+D`) | `.claude/bin/agent-watch` | every agent's activity, one color each |
| Split (`Cmd+Shift+D`) | `.claude/bin/agent-watch prs` | open PRs + checks, refreshed every 30s |
| Extra split per agent | `.claude/bin/agent-watch <agent>` | e.g. `agent-watch pipeline-engineer` |

`.claude/bin/agent-watch handoffs` lists the 10 newest handoff reports and prints the latest in full —
useful right after a builder finishes, before you decide what to review next.

**Built-in agent panel.** Inside the `tech-lead` session itself, press `↑`/`↓` then `Enter` to open
Claude Code's agent panel and inspect a running sub-agent directly, without leaving the pane.

**Handoffs.** `.claude/logs/handoffs/<UTC timestamp>-<agent>.md` is each sub-agent's final report, with
its transcript path at the top — the fastest way to see exactly what an agent did and why, after the fact.
