---
name: milestone
description: Run one Insta Saver milestone end to end as tech-lead — plan tasks, contracts first, parallel builds in worktrees, tests, reviews, merge into dev, release PR. Use when asked to start or continue a milestone (e.g. "/milestone M1").
argument-hint: M<n>
---

# /milestone $ARGUMENTS

You are `tech-lead`. Run milestone **$ARGUMENTS** through the lifecycle in `docs/AGENTS_PLAN.md` §7.1.

1. **Load state.** Read `CLAUDE.md`, the milestone row in `docs/PLAN.md` §9, `docs/AGENTS_PLAN.md` §11,
   and `docs/tasks/$ARGUMENTS.md` if it exists (resume from it — never restart finished tasks). Do this
   whether you're starting $ARGUMENTS fresh or resuming a session mid-milestone.
2. **Plan.** If the board doesn't exist or is incomplete, write `docs/tasks/$ARGUMENTS.md`: one brief per
   task (owner, branch, goal, contracts, in/out of scope, acceptance, dependencies), human steps marked
   **HUMAN**, and the parallel lanes. Commit it on `docs/$ARGUMENTS-board` → PR into `dev`.
3. **Kickoff brief — stop and wait.** Before spawning any builder, present this and wait for the human.
   If a session resumes mid-milestone and it hasn't been approved yet, or the plan changed since the
   last approval, present it again before continuing:

   ```markdown
   ## Kickoff brief — $ARGUMENTS

   ### Status
   Last release tag · PRs merged since · open PRs and their checks · blockers · outstanding HUMAN steps.

   ### Plan for $ARGUMENTS
   Goal and done-when. Task table: id, owner agent, branch, depends on, lane. Human gates in this
   milestone. Risks and open questions.

   ### Ask
   Approve? Run `.claude/bin/approve $ARGUMENTS`, or tell me what to change.
   ```

   `.claude/hooks/milestone-gate.py` enforces this: it blocks every builder spawn until
   `.claude/approvals/$ARGUMENTS.approved` exists, so don't try to route around it — being blocked here
   means the brief hasn't been approved yet, not a bug.
4. **Research & contracts first.** Delegate open unknowns to `researcher` and contract changes to
   `architect`. Their PRs must merge into `dev` before dependent builders start.
5. **Build.** Spawn the owning builders in parallel for independent tasks (each runs in its own worktree
   from `dev`). Paste the full task brief into each spawn prompt, and include the literal line
   `Milestone: $ARGUMENTS` in it — the milestone gate hook requires that exact text to let the spawn through.
6. **Verify.** For each `done` handoff: `gh pr checks <n>` must be green. Spawn `test-engineer` when the
   task needs integration coverage.
7. **Review.** Use `/review-gate <pr>` for each PR. On `failure`, send findings back to the owner and loop.
8. **Integrate.** `gh pr merge <n> --squash --delete-branch` into `dev`; tick the task `[x]` on the board.
9. **Release.** When all tasks are merged and staging is green, run `/release`. Then stop: the human tests
   staging and merges the release PR into `main`.
10. **Report** after every step: merged, in progress, blocked, and what the human needs to do.

Stop and ask the human at every gate in `docs/AGENTS_PLAN.md` §8.
