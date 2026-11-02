# 0005 — Merge methods: back-merges into `dev`, squash hotfixes into `main`

- Status: accepted
- Date: 2026-11-01
- Deciders: product owner (chose option A on 2026-11-01, M0 board Q3); architect (recorded the rules and flow)
- Supersedes: [ADR 0003](0003-git-workflow-and-environments.md) decision 2 (merges). The rest of ADR 0003
  stands.

## Context
- ADR 0003 #2 (and [AGENTS_PLAN.md](../AGENTS_PLAN.md) §15.2 / §15.5) allow only **squash** on `dev` and only
  **merge commits** on `main`, and both branches require "branch up to date before merge" (strict status
  checks).
- **Deadlock after the first release.** The release PR `dev → main` is merged with a merge commit `M`. `M` is
  on `main` but not on `dev`. If `dev` accepts only squash, a back-merge `main → dev` arrives on `dev` as a
  new squash commit, and `M` is still not an ancestor of `dev`. Every later release PR `dev → main` is
  therefore permanently "out of date" with `main`. GitHub's "Update branch" would fix it by merging `main`
  into `dev`, which is a direct push to `dev`, so protection blocks that too. The release can never be
  merged without turning protection off.
- **Hotfixes contradict the rules.** AGENTS_PLAN §15.2 says hotfix → `main` by squash, but §15.5 allows only
  merge commits on `main`. A hotfix squash on `main` creates a commit `H` that `dev` also never gets
  unless it is back-merged with ancestry preserved.
- GitHub rulesets set the allowed merge methods per branch. They cannot allow a method only for some PRs.

## Decision
1. **`dev` allows squash and merge commits.**
   - Feature, fix, docs, test, chore and refactor PRs → **squash** (unchanged; tech-lead merges).
   - **Merge commits are used only for `main → dev` back-merge PRs** (below): "Create a merge commit" into
     `dev` only when the head branch matches `chore/back-merge-*` **and** the back-merge check (4.3) passed.
     Squashing a back-merge is forbidden: it drops the `main` parent and brings the deadlock back.
   - Why the restriction matters beyond tidiness: a feature PR merged with a merge commit lands all its
     intermediate commits in public `dev` history for good. gitleaks catches pattern-matching secrets in them,
     but not personal data, captions or media that were committed and later removed on the branch.
2. **`main` allows merge commits and squash.**
   - Release PRs `dev → main` (`release: vX.Y.Z`) → **merge commit** (unchanged; only the human merges).
   - Hotfix PRs `hotfix/<slug> → main` → **squash** (human-led, as before).
3. **"Require branch up to date before merge" stays on `main`** (and on `dev`, as in AGENTS_PLAN §15.5).
   With the back-merge below, a release PR is up to date whenever no hotfix landed since the last back-merge.
4. **Back-merge after every release and every hotfix**, before the next PR into `main` is merged:
   1. tech-lead branches `chore/back-merge-vX.Y.Z` (or `chore/back-merge-<hotfix-slug>`) from `origin/dev`.
   2. `git merge --no-ff origin/main` on that branch, and nothing else: no other commits on the branch.
      Conflicts are resolved inside that merge commit (after a hotfix, with the human if the fix touches code
      that changed on `dev`). Push, then open a PR into `dev` titled
      `chore(devops): back-merge main into dev after vX.Y.Z` (or `after hotfix/<slug>`).
   3. **Back-merge check**, run right before merging (after `git fetch origin`, on the PR head):
      - `git rev-list --no-merges origin/dev..HEAD --not origin/main` prints nothing (every non-merge commit
        on the branch is already on `main`);
      - `git rev-list --merges origin/dev..HEAD` prints exactly one commit `M`;
      - `git merge-base --is-ancestor M^1 origin/dev` and `git merge-base --is-ancestor M^2 origin/main`
        both succeed (first parent from `dev`, second parent on `main`);
      - `git merge-base --is-ancestor origin/main HEAD` succeeds (the branch contains all of `main`).
      If `dev` moved while the PR was open, do **not** use "Update branch" (it adds a second merge commit and
      the check fails): re-cut the branch from the new `origin/dev`, merge `origin/main` again, force-push
      with `--force-with-lease`, and re-run the check. Until a CI status runs this check (devops-engineer
      follow-up: a `ci/back-merge` status on `chore/back-merge-*` heads), **tech-lead runs it by hand** and
      pastes the output into the PR before merging.
   4. **Reviews.** Both `agent-review/code` and `agent-review/security` are required on `dev`, so both
      reviewers post on every back-merge PR. Their scope is the check output plus the merge commit's own
      content, i.e. the conflict resolution: `git show --remerge-diff M` (git ≥ 2.36; empty for a clean merge). The
      commits coming from `main` were already reviewed there. A non-empty resolution is new code and is
      reviewed like any diff; security-reviewer reviews it in full when its paths cross the trust boundary.
   5. Required checks pass → tech-lead merges with **"Create a merge commit"**.
   6. Check: `git merge-base --is-ancestor origin/main origin/dev` succeeds. The release flow runs this check
      again before it opens the next release PR.
   The branch starts from `dev`, not `main`, so it follows the normal branching rule. A PR with `main` itself
   as the head would usually be out of date, and updating it would mean pushing to `main`.
   **Secret scanning gap.** The `ci/secrets` range scan (`git log -p`, without `-m` / `--cc`, PR #12) skips
   merge-commit patches, so a conflict resolution inside `M` is not range-scanned. Until that scan covers
   merge commits (devops-engineer, PR #12 follow-up: `--cc` / `-m`, or a scheduled all-refs scan), the
   resolution relies on the working-tree scan (pre-commit hook and CI) and on the reviewers reading
   `--remerge-diff`.
5. **Flows.**
   - Release: release PR `dev → main` (human, merge commit) → CI tags and deploys production → back-merge
     PR into `dev` (tech-lead, merge commit).
   - Hotfix: `hotfix/<slug>` from `main` → PR into `main` (human, squash) → CI deploys production →
     back-merge PR into `dev` (tech-lead, merge commit).
6. The merge-method-per-PR rules in 1–2 are a **process rule** (tech-lead for `dev`, the human for `main`),
   because rulesets cannot enforce them. The back-merge check (4.3) is the mechanical part; `ci/source-branch`
   still limits who can open PRs into `main`.

This supersedes the merge rules in AGENTS_PLAN.md §15.2 (merge strategy table), §15.5 ("Allowed merge
method" row) and §15.7 (hotfix line). That file is human-owned and still describes the old rules; until the
human updates it, this ADR wins where they differ.

## Alternatives considered
| Option | Why not |
|---|---|
| Keep squash-only `dev` and merge-only `main` (ADR 0003 #2) | Release PRs deadlock after release 1 (Context); a hotfix squash is forbidden on `main` |
| Drop "require up to date" on `main` | Removes the deadlock symptom, but a release could merge a `dev` that was never tested together with a hotfix already on `main` |
| Squash releases into `main` too | Same problem in the other direction: `main` commits never become ancestors of `dev`, every release PR re-shows old commits |
| Rebase-merge everywhere | Rewrites commit ids, so `main` and `dev` still diverge; release history becomes hard to read |
| Back-merge PR with `main` as the head branch | Usually out of date with `dev`, and "Update branch" would push to `main`; a `chore/back-merge-*` branch avoids both |
| Allow merge commits on `dev` for all PRs | Loses the one-commit-per-task history on `dev` that makes reverts easy |

## Consequences
- Easier: release PRs stay mergeable with strict checks on; a hotfix can't be lost on the next release; the
  ancestry check gives one command that says whether `dev` is in sync with `main`.
- Harder: one extra PR after every release and hotfix; the "merge commit only for back-merges" and "squash
  only for hotfixes" rules depend on discipline, since GitHub allows both methods on both branches. A wrong
  method is recoverable: a squashed back-merge is fixed by a new, correct back-merge; a squashed release by
  back-merging `main` again.
- Contracts: none.
- Agents and owners:
  - devops-engineer: `scripts/setup-branch-protection.sh` allows squash + merge on both branches and keeps
    strict checks on `main` (M0.2b, already in progress). Follow-ups: a `ci/back-merge` status that runs the
    4.3 check on `chore/back-merge-*` heads; `ci/secrets` covering merge-commit patches.
  - code-reviewer, security-reviewer: review back-merge PRs as in 4.4.
  - tech-lead: release and back-merge flow, including running the 4.3 check by hand until `ci/back-merge`
    exists; `.claude/skills/release` and `.claude/skills/hotfix` should describe the `chore/back-merge-*`
    branch. Those files are human-owned. The hotfix skill today opens the
    back-merge with `--head main`.
  - Human: merges release (merge commit) and hotfix (squash) PRs into `main`; updates AGENTS_PLAN §15.2,
    §15.5 and §15.7 and the two skills, or confirms this ADR is the only source.
