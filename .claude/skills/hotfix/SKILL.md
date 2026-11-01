---
name: hotfix
description: Prepare an urgent Insta Saver production fix — branch from main, PR into main, then a back-merge PR into dev. Use only when production (main) is broken.
argument-hint: <slug>
---

# /hotfix $ARGUMENTS

Production is broken. First check whether a simple **revert** of the last release merge on `main` is the
safer fix — if so, propose that to the human instead.

1. `git fetch origin && git switch -c hotfix/$ARGUMENTS origin/main`
2. Delegate the minimal fix to the owning agent with an explicit brief: smallest change, test that
   reproduces the bug, no refactors.
3. PR into `main`: `gh pr create --base main --title "fix(<scope>): <summary>" --label security` and run
   `/review-gate <pr>`.
4. **Stop** — the human merges into `main` (squash). CI deploys production.
5. Back-merge so the fix isn't lost on the next release:
   `gh pr create --base dev --head main --title "chore: back-merge main into dev after hotfix/$ARGUMENTS"`
   (merge commit). Report both PR links.
