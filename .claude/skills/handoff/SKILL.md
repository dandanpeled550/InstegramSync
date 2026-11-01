---
name: handoff
description: Produce the standard Insta Saver handoff report at the end of a task from the branch diff, PR and gate results. Use as the last step of every builder task.
---

# /handoff

Gather facts, don't guess:

1. `git status --short` (must be clean — commit or explain leftovers)
2. `git log --oneline origin/dev..HEAD`
3. `git diff --stat origin/dev...HEAD`
4. `gh pr view --json url,isDraft,title` and `gh pr checks`
5. The commands you ran for your gate and their results.

Then return exactly:

```markdown
Status: done | blocked | partial
Branch / PR: <branch> → <url> (draft | ready)
Summary: 2–3 sentences
Files changed: <from diff --stat>
Contracts touched: none | <file> (ADR: …)
Checks run: <commands> → results
Open issues / risks: …
Needs from others: <agent>: <what and why>
```

`done` only when the gate passed and the PR is ready. Otherwise `blocked` or `partial`, with the reason.
