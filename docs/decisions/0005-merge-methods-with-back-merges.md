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
3. **"Require branch up to date before merge" stays on `main`** (and on `dev`, as today).
   With the back-merge below, a release PR is up to date whenever no hotfix landed since the last back-merge.
4. **Back-merge after every release and every hotfix**, before the next PR into `main` is merged:
   1. tech-lead branches `chore/back-merge-vX.Y.Z` (or `chore/back-merge-<hotfix-slug>`) from `origin/dev`.
   2. `git merge --no-ff origin/main` on that branch, and nothing else: no other commits on the branch.
      Conflicts are resolved inside that merge commit (after a hotfix, with the human if the fix touches code
      that changed on `dev`). Push, then open a PR into `dev` titled
      `chore(devops): back-merge main into dev after vX.Y.Z` (or `after hotfix/<slug>`).
   3. **Back-merge check**, run right before merging, against the PR head **SHA** (not a local `HEAD`).
      The rule: the head commit `M` is a merge with **exactly two parents, `M^1` = the current `origin/dev`
      tip and `M^2` = the current `origin/main` tip**, and `git rev-list --first-parent origin/dev..M` prints
      exactly `M`. Counting merges in `origin/dev..M` is wrong: after a release that range also holds the
      release merge commit `R` from `main`, so a "exactly one merge" rule fails every release back-merge.
      The exact-parent rule implies the rest: every commit in `origin/dev..M` other than `M` is already on
      `main` (so nothing unreviewed rides along), and `origin/main` is an ancestor of `M`. The first-parent
      line is redundant with it by construction and is kept as a second, independent statement of "nothing
      but `M`". Simulated on a scratch repo for the three cases below before this ADR was accepted.
      Copy-paste, with `PR` set to the back-merge PR number (bash, needs `gh` and `git` ≥ 2.36):

      ```bash
      PR=123   # the back-merge PR number
      (
        set -euo pipefail
        fail() { echo "BACK-MERGE CHECK FAILED: $*" >&2; exit 1; }
        read -r head_ref base_ref sha < <(gh pr view "$PR" --json headRefName,baseRefName,headRefOid \
          -q '[.headRefName, .baseRefName, .headRefOid] | @tsv')
        git fetch --quiet origin
        dev=$(git rev-parse origin/dev)
        main=$(git rev-parse origin/main)
        [[ "$base_ref" == "dev" ]]                             || fail "base is $base_ref, not dev"
        [[ "$head_ref" == chore/back-merge-* ]]                || fail "head $head_ref is not chore/back-merge-*"
        [[ "$(git rev-parse "origin/$head_ref")" == "$sha" ]]  || fail "origin/$head_ref is not the PR head $sha"
        [[ "$(git rev-list --parents -n 1 "$sha")" == "$sha $dev $main" ]] \
          || fail "parents of $sha are not exactly (origin/dev $dev, origin/main $main)"
        [[ "$(git rev-list --first-parent "$dev..$sha")" == "$sha" ]] \
          || fail "first-parent history beyond origin/dev is not exactly the merge"
        git merge-base --is-ancestor "$main" "$sha"            || fail "origin/main is not an ancestor of $sha"
        echo "BACK-MERGE CHECK OK: PR #$PR head=$sha M^1=origin/dev=$dev M^2=origin/main=$main"
        git show --remerge-diff --stat --format='%H %s' "$sha"   # resolution files; none for a clean merge
      )
      ```

      Paste the full output into the PR. Then merge **that SHA only**:
      `gh pr merge "$PR" --merge --match-head-commit "$sha"` (GitHub refuses if the head moved after the
      check; if `dev` moved, the strict up-to-date rule refuses too). Never merge from the web UI.
      - **Release back-merge passes.** `dev` = `D2`. The release PR lands on `main` as `R` (parents `P` =
        old `main`, `D2`). The branch is cut from `D2`, then `git merge --no-ff origin/main` gives `M`
        (parents `D2`, `R`). `--no-ff` is required here: `D2` is an ancestor of `R`, so a plain merge would
        fast-forward to `R` and there would be no `M`. `origin/dev..M` = `M`, `R` (plus any other `main`
        commit not yet on `dev`), which is why a merge count sees two. Parents of `M` = (`D2` = `origin/dev`, `R` =
        `origin/main`) ✓; first-parent walk `M` → `D2` (excluded) prints `M` ✓; `R` ancestor of `M` ✓.
      - **Hotfix back-merge passes.** `main` = `H`, the squash commit of the hotfix on top of `R` (`R` is
        already on `dev` through the last back-merge). `dev` moved on to `D4`. The branch is cut from `D4`;
        `git merge --no-ff origin/main` gives `M` (parents `D4`, `H`), with any conflict resolved inside `M`.
        Parents = (`D4`, `H`) ✓; first-parent prints `M` ✓; `H` ancestor of `M` ✓.
      - **Rejected: an extra commit on the branch.** The branch gets a commit `X` (say, a "small fix") on
        `D4` before the merge, so `M` has parents (`X`, `H`). Output:
        `BACK-MERGE CHECK FAILED: parents of <M> are not exactly (origin/dev <D4>, origin/main <H>)`. Also
        rejected the same way: a commit after `M` (head has one parent), "Update branch" after `dev` moved
        (head is a merge of (`M`, new `dev`)), and a branch cut before the latest `dev` or `main` commit.
      If `dev` or `main` moved while the PR was open, do **not** use "Update branch" (it adds a second merge
      commit and the check fails): re-cut the branch from the new `origin/dev`, merge `origin/main` again,
      force-push with `--force-with-lease`, and re-run the check. Until a CI status runs this exact check
      (devops-engineer follow-up: a `ci/back-merge` status on `chore/back-merge-*` heads, same rule, run on
      the head SHA of the `pull_request` event), **tech-lead runs it by hand** and pastes the output into the
      PR before merging.
   4. **Reviews.** Both `agent-review/code` and `agent-review/security` are required on `dev`, so both
      reviewers post on every back-merge PR. Their scope is the check output plus the merge commit's own
      content, i.e. the conflict resolution: `git show --remerge-diff M` (git ≥ 2.36; empty for a clean merge). The
      commits coming from `main` were already reviewed there. A non-empty resolution is new code and is
      reviewed like any diff; security-reviewer reviews it in full when its paths cross the trust boundary.
   5. Required checks pass → tech-lead merges with **"Create a merge commit"**, using the
      `gh pr merge --merge --match-head-commit` command from 4.3.
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

**This ADR is the only source for merge methods and back-merges** (human decision, 2026-11-02, PR #13
round 3). It supersedes the merge rules in AGENTS_PLAN.md §15.2 (merge strategy table), §15.5 ("Allowed
merge method" row) and §15.7 (hotfix line). Those sections **will not be updated**; they stay as written
and are superseded by this ADR. Any agent or skill that needs merge methods or the back-merge flow reads
this ADR, not AGENTS_PLAN §15.

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
    4.3 check (exact-parent rule, on the head SHA) on `chore/back-merge-*` heads; `ci/secrets` covering merge-commit patches.
  - code-reviewer, security-reviewer: review back-merge PRs as in 4.4.
  - tech-lead: release and back-merge flow, including running the 4.3 check by hand until `ci/back-merge`
    exists; `.claude/skills/release` and `.claude/skills/hotfix` should describe the `chore/back-merge-*`
    branch. Those files are human-owned. The hotfix skill today opens the
    back-merge with `--head main`.
  - Human: merges release (merge commit) and hotfix (squash) PRs into `main`. Decided that this ADR is the
    only source (AGENTS_PLAN §15.2 / §15.5 / §15.7 stay as they are, superseded). The two skills are
    human-owned and should point to this ADR.
