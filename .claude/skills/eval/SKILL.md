---
name: eval
description: Run Insta Saver's AI eval harness and write a before/after report for a prompt, rubric, threshold or model change. Use as ai-engineer before any PR that changes model behavior.
argument-hint: <change-slug>
---

# /eval $ARGUMENTS

1. Estimate cost first: posts × stages × tokens × price (from `docs/research/`). If it exceeds
   `evals/budget.md`, stop and ask the human via your handoff.
2. Run the baseline on `origin/dev` and the candidate on your branch: `make eval` (falls back to
   `evals/sample.jsonl` when `evals/private/` is absent).
3. Write `evals/reports/<YYYY-MM-DD>-$ARGUMENTS.md`:
   - Category accuracy, needs-review rate, `decided_at_stage` distribution, title-quality sample,
     cost and latency per post — baseline vs candidate in one table.
   - Notable regressions with example IDs (synthetic or private IDs only — never paste real captions).
4. Link the report in the PR under "How it was tested".
