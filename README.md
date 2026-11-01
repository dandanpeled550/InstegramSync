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
