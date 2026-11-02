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
   1. tech-lead fetches with full ref names and no tags,
      `git fetch --no-tags origin +refs/heads/dev:refs/remotes/origin/dev +refs/heads/main:refs/remotes/origin/main`,
      and branches `chore/back-merge-vX.Y.Z` (or `chore/back-merge-<hotfix-slug>`) from
      `refs/remotes/origin/dev`. Every git command in this flow names refs in full (`refs/remotes/origin/…`),
      never `origin/dev` or `origin/main` (why: 4.3).
   2. `git merge --no-ff refs/remotes/origin/main` on that branch, and nothing else: no other commits on the
      branch.
      Conflicts are resolved inside that merge commit (after a hotfix, with the human if the fix touches code
      that changed on `dev`). Push, then open a PR into `dev` titled
      `chore(devops): back-merge main into dev after vX.Y.Z` (or `after hotfix/<slug>`).
   3. **Back-merge check**, run right before merging, against the PR head **SHA** (not a local `HEAD`).
      Here `dev` and `main` mean the **branch tips on GitHub**, resolved as described below. The rule: the
      head commit `M` is a merge with **exactly two parents, `M^1` = the current `dev` tip and `M^2` = the
      current `main` tip**, and `git rev-list --first-parent M ^dev` prints exactly `M`. Counting merges in
      `dev..M` is wrong: after a release that range also holds the release merge commit `R` from `main`, so
      an "exactly one merge" rule fails every release back-merge. The exact-parent rule implies the rest:
      every commit in `dev..M` other than `M` is already on `main` (so nothing unreviewed rides along), and
      `main` is an ancestor of `M`. The first-parent
      line is redundant with it by construction and is kept as a second, independent statement of "nothing
      but `M`". Simulated on a scratch repo (macOS `/bin/bash` 3.2, git 2.56, a fake `gh` that answers from the
      scratch origin's branches) for the cases below, including a pushed `refs/tags/origin/main`.
      **Refs are resolved by full name only, and checked against GitHub.** A short name such as
      `origin/main` is resolved by git in the order `refs/origin/main`, `refs/tags/origin/main`,
      `refs/heads/origin/main`, `refs/remotes/origin/main`, so a tag named `origin/main` wins. Any agent can push
      one (`git push origin Z:refs/tags/origin/main`), and a plain `git fetch` copies it into every clone, where
      it stays. With short names, `M` = merge(`dev`, unreviewed `Z`) would pass as "a merge of `main`". So the
      check (a) fetches with `--no-tags` and an explicit refspec for `dev`, `main` and the head branch;
      (b) resolves only `refs/remotes/origin/<branch>^{commit}` with `git rev-parse --verify --quiet`; and
      (c) requires the `dev` and `main` SHAs to equal the branch SHAs from the GitHub API
      (`gh api repos/{owner}/{repo}/git/ref/heads/<branch>`), which has no tag/branch ambiguity. Every SHA used
      after that is a literal 40-hex value. The PR head must be a branch of this repository
      (`isCrossRepository == false`). **`ci/back-merge` follows the same rule**: it takes `dev` and `main` from
      the API (or full `refs/heads/…` / `refs/remotes/origin/…` names after a `--no-tags` fetch) and the head
      from the event's head SHA, and never passes a short ref name to git.

      The check is a **bash** script (bash ≥ 3.2, `gh`, `git` ≥ 2.36). Save it to a file **outside the repo**
      (for example `back-merge-check.sh` in a scratch directory) and run `bash back-merge-check.sh <PR>` from the
      repo root. Do not paste it into an interactive zsh: zsh treats `#` and some quoting differently. The
      script has no comments on purpose. It never merges; on success its last line is the exact merge command,
      with the literal head SHA, for the merge step (4.5):

      ```bash
      #!/usr/bin/env bash
      set -euo pipefail
      fail() { echo "BACK-MERGE CHECK FAILED: $*" >&2; exit 1; }
      pr="${1:-}"
      [[ "$pr" =~ ^[0-9]+$ ]] || fail "usage: bash back-merge-check.sh <PR number>"
      info=$(gh pr view "$pr" --json headRefName,baseRefName,headRefOid,isCrossRepository \
        -q '[.headRefName, .baseRefName, .headRefOid, (.isCrossRepository | tostring)] | @tsv') \
        || fail "gh pr view $pr failed"
      IFS=$'\t' read -r head_ref base_ref sha cross <<< "$info" || fail "unexpected gh output"
      [[ "$base_ref" == "dev" ]]                 || fail "base is $base_ref, not dev"
      [[ "$head_ref" == chore/back-merge-* ]]    || fail "head $head_ref is not chore/back-merge-*"
      [[ "$cross" == "false" ]]                  || fail "head branch is not in this repository"
      [[ "$sha" =~ ^[0-9a-f]{40}$ ]]             || fail "head SHA '$sha' is not a 40-hex SHA"
      git fetch --quiet --no-tags origin \
        "+refs/heads/dev:refs/remotes/origin/dev" \
        "+refs/heads/main:refs/remotes/origin/main" \
        "+refs/heads/$head_ref:refs/remotes/origin/$head_ref" || fail "git fetch failed"
      dev=$(git rev-parse --verify --quiet "refs/remotes/origin/dev^{commit}")   || fail "no refs/remotes/origin/dev"
      main=$(git rev-parse --verify --quiet "refs/remotes/origin/main^{commit}") || fail "no refs/remotes/origin/main"
      head=$(git rev-parse --verify --quiet "refs/remotes/origin/$head_ref^{commit}") \
        || fail "no refs/remotes/origin/$head_ref"
      api_dev=$(gh api "repos/{owner}/{repo}/git/ref/heads/dev" --jq .object.sha)   || fail "gh api dev failed"
      api_main=$(gh api "repos/{owner}/{repo}/git/ref/heads/main" --jq .object.sha) || fail "gh api main failed"
      [[ "$dev" == "$api_dev" ]]    || fail "local dev $dev differs from GitHub dev $api_dev"
      [[ "$main" == "$api_main" ]]  || fail "local main $main differs from GitHub main $api_main"
      [[ "$head" == "$sha" ]]       || fail "refs/remotes/origin/$head_ref is $head, not the PR head $sha"
      [[ "$(git rev-list --parents -n 1 "$sha")" == "$sha $dev $main" ]] \
        || fail "parents of $sha are not exactly (dev $dev, main $main)"
      [[ "$(git rev-list --first-parent "$sha" "^$dev")" == "$sha" ]] \
        || fail "first-parent history beyond dev is not exactly the merge"
      git merge-base --is-ancestor "$main" "$sha" || fail "main is not an ancestor of $sha"
      echo "BACK-MERGE CHECK OK: PR #$pr head=$sha M^1=dev=$dev M^2=main=$main (dev and main match the GitHub API)"
      echo "--- resolution summary (remerge-diff; empty for a clean merge) ---"
      git --no-pager show --remerge-diff --stat --summary --format='%H %s' "$sha"
      echo "--- resolution diff (remerge-diff, full) ---"
      git --no-pager show --remerge-diff --format= "$sha"
      echo "--- merge command for 4.5, valid for this head only ---"
      echo "gh pr merge $pr --merge --match-head-commit $sha"
      ```

      Paste the full output into the PR (summary **and** full resolution diff). After both reviews pass, run
      the printed `gh pr merge … --merge --match-head-commit <sha>` line as printed, with the literal SHA, never
      a shell variable: GitHub then refuses if the head moved after the check, and the strict up-to-date rule
      refuses if `dev` moved. Never merge from the web UI. If `main` moves between the check and the merge, the
      merge still succeeds (it only lacks the newer `main` commits); 4.6 then fails and tech-lead opens another
      back-merge.
      - **Release back-merge passes.** `dev` = `D2`. The release PR lands on `main` as `R` (parents `P` =
        old `main`, `D2`). The branch is cut from `D2`, then `git merge --no-ff refs/remotes/origin/main` gives `M`
        (parents `D2`, `R`). `--no-ff` is required here: `D2` is an ancestor of `R`, so a plain merge would
        fast-forward to `R` and there would be no `M`. `dev..M` = `M`, `R` (plus any other `main`
        commit not yet on `dev`), which is why a merge count sees two. Parents of `M` = (`D2` = `dev`, `R` =
        `main`) ✓; first-parent walk `M` → `D2` (excluded) prints `M` ✓; `R` ancestor of `M` ✓.
      - **Hotfix back-merge passes.** `main` = `H`, the squash commit of the hotfix on top of `R` (`R` is
        already on `dev` through the last back-merge). `dev` moved on to `D4`. The branch is cut from `D4`;
        `git merge --no-ff refs/remotes/origin/main` gives `M` (parents `D4`, `H`), with any conflict resolved inside `M`.
        Parents = (`D4`, `H`) ✓; first-parent prints `M` ✓; `H` ancestor of `M` ✓.
      - **Rejected: an extra commit on the branch.** The branch gets a commit `X` (say, a "small fix") on
        `D4` before the merge, so `M` has parents (`X`, `H`). Output:
        `BACK-MERGE CHECK FAILED: parents of <M> are not exactly (dev <D4>, main <H>)`. Also rejected the
        same way: a commit after `M` (head has one parent), "Update branch" after `dev` moved (head is a merge
        of (`M`, new `dev`)), and a branch cut before the latest `dev` or `main` commit.
      - **Rejected: a tag posing as `main`.** An unreviewed commit `Z` is pushed to any branch, a tag
        `refs/tags/origin/main` → `Z` is pushed, and the PR head is `M` = merge(`dev`, `Z`). The previous
        short-name version of this check printed `CHECK OK` here. Now `main` comes from
        `refs/remotes/origin/main` (the real branch), so the parent rule fails:
        `parents of <M> are not exactly (dev <D>, main <R>)`. If the local fetch itself is subverted (for
        example `origin` points to a mirror whose `main` is `Z`), the API cross-check fails instead:
        `local main <Z> differs from GitHub main <R>`. Also simulated: a fork head
        (`isCrossRepository` = true) is rejected; a stale local tag `origin/dev` and a branch named with the
        40-hex SHA of `M` change nothing (the check never uses short names, and git reads a full 40-hex
        value as an object id).
      If `dev` or `main` moved while the PR was open, do **not** use "Update branch" (it adds a second merge
      commit and the check fails): fetch again as in 4.1, re-cut the branch from `refs/remotes/origin/dev`,
      merge `refs/remotes/origin/main` again, force-push with `--force-with-lease`, and re-run the check. Until
      a CI status runs this exact check (devops-engineer follow-up: a `ci/back-merge` status on
      `chore/back-merge-*` heads, same rule including full refs and the API cross-check, run on the head SHA
      of the `pull_request` event), **tech-lead runs it by hand** and pastes the output into the PR before
      merging.
   4. **Reviews.** Both `agent-review/code` and `agent-review/security` are required on `dev`, so both
      reviewers post on every back-merge PR. Their scope is the check output plus the merge commit's own
      content, i.e. the conflict resolution. The commits coming from `main` were already reviewed there.
      - Reviewers read the **full** `git --no-pager show --remerge-diff M` (git ≥ 2.36; empty for a clean
        merge), not only `--stat`. It diffs the re-merged tree against `M`'s real tree, so an edit to a file
        neither side touched also shows up. A non-empty resolution is new code and is reviewed like any diff;
        security-reviewer reviews it in full when its paths cross the trust boundary.
      - A resolution that contains a **binary file, a mode change, a symlink or a submodule change** is
        rejected unless the human approves it in the PR: the diff shows these only as a header line
        (`Binary files differ`, `mode change`, `Subproject commit`), so a reviewer cannot read the content.
        The check prints `--summary` so they are visible.
      - Optional `ci/back-merge` rule (devops-engineer): fail when the resolution touches `.github/**`,
        `.claude/**`, `supabase/functions/**` or `supabase/migrations/**`, unless the human acknowledges it
        on the PR.
      - Merge-commit patches are still not secret-scanned (see "Secret scanning gap" below), so reviewers
        also read the resolution for secrets.
   5. Required checks and both reviews pass → tech-lead runs the exact `gh pr merge <PR> --merge
      --match-head-commit <sha>` line that 4.3 printed ("Create a merge commit").
      **Hook prerequisite.** The human-owned `.claude/hooks/git-guard.py` currently rejects every
      `gh pr merge` without `--squash`. **Until the human's hook change (Consequences) lands, tech-lead stops
      here and reports to the human; a back-merge PR is never squashed.** A squash would put the merge result
      on `dev` as a one-parent commit, so `main` is still not an ancestor of `dev`: the back-merge silently
      does nothing, 4.6 fails only after the commit is on `dev`, and the next release PR is again out of
      date or conflicting. The human may instead merge the PR with the printed command themselves.
   6. Check, after a fresh fetch as in 4.1:
      `git merge-base --is-ancestor refs/remotes/origin/main refs/remotes/origin/dev` succeeds. If it fails
      because `main` moved between the check and the merge (a hotfix landed), tech-lead opens another
      back-merge. The release flow runs this check again before it opens the next release PR.
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
    4.3 check (exact-parent rule, on the event's head SHA, `isCrossRepository` false, `dev` and `main` from
    the API or full refs after a `--no-tags` fetch, never short ref names) on `chore/back-merge-*` heads,
    optionally with the sensitive-path rule from 4.4; `ci/secrets` covering merge-commit patches.
  - code-reviewer, security-reviewer: review back-merge PRs as in 4.4.
  - tech-lead: release and back-merge flow, including running the 4.3 check by hand until `ci/back-merge`
    exists; `.claude/skills/release` and `.claude/skills/hotfix` should describe the `chore/back-merge-*`
    branch. Those files are human-owned. The hotfix skill today opens the
    back-merge with `--head main`.
  - Human: merges release (merge commit) and hotfix (squash) PRs into `main`. Decided that this ADR is the
    only source (AGENTS_PLAN §15.2 / §15.5 / §15.7 stay as they are, superseded). The two skills are
    human-owned and should point to this ADR.
  - Human: **update `.claude/hooks/git-guard.py`** (human-owned; today lines 306-309 reject any
    `gh pr merge` without `--squash`) to allow `gh pr merge <n> --merge --match-head-commit <40-hex sha>`
    only when the PR's base is `dev` and its head is `chore/back-merge-*` (looked up from GitHub, not taken
    from the command line). Every other `gh pr merge` by an agent stays squash-only; release PRs into `main`
    are merged by the human, so the hook needs no `main` exception. Until this lands, 4.5 stops at the
    human.
