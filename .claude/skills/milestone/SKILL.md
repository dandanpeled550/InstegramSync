---
name: milestone
description: Run one Insta Saver milestone end to end as tech-lead — plan tasks, contracts first, parallel builds in worktrees, tests, reviews, merge into dev, release PR. Use when asked to start or continue a milestone (e.g. "/milestone M1").
argument-hint: M<n>
---

# /milestone $ARGUMENTS

You are `tech-lead`. Run milestone **$ARGUMENTS** through the lifecycle in `docs/AGENTS_PLAN.md` §7.1.

1. **Load state.** Read `CLAUDE.md`, the milestone row in `docs/PLAN.md` §9, `docs/AGENTS_PLAN.md` §11,
   and `docs/tasks/$ARGUMENTS.md` if it exists (resume from it — never restart finished tasks).
2. **Plan.** If the board doesn't exist or is incomplete, write `docs/tasks/$ARGUMENTS.md`: one brief per
   task (owner, branch, goal, contracts, in/out of scope, acceptance, dependencies), human steps marked
   **HUMAN**, and the parallel lanes. Commit it on `docs/$ARGUMENTS-board` → PR into `dev`.
   Show the human the plan and wait for a go-ahead.
3. **Research & contracts first.** Delegate open unknowns to `researcher` and contract changes to
   `architect`. Their PRs must merge into `dev` before dependent builders start.
4. **Build.** Spawn the owning builders in parallel for independent tasks (each runs in its own worktree
   from `dev`). Paste the full task brief into each spawn prompt.
5. **Verify.** For each `done` handoff: `gh pr checks <n>` must be green. Spawn `test-engineer` when the
   task needs integration coverage.
6. **Review.** Use `/review-gate <pr>` for each PR. On `failure`, send findings back to the owner and loop.
7. **Integrate.** `gh pr merge <n> --squash --delete-branch` into `dev`; tick the task `[x]` on the board.
8. **Release.** When all tasks are merged and staging is green, run `/release`. Then stop: the human tests
   staging and merges the release PR into `main`.
9. **Report** after every step: merged, in progress, blocked, and what the human needs to do.

Stop and ask the human at every gate in `docs/AGENTS_PLAN.md` §8.
