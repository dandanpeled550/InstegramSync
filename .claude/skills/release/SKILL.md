---
name: release
description: Open an Insta Saver release PR from dev to main with a changelog built from conventional commits and staging evidence. Use at the end of a milestone, as tech-lead. The human merges it.
argument-hint: "[vX.Y.Z]"
---

# /release $ARGUMENTS

1. `git fetch origin --tags`. Last release: `git describe --tags --abbrev=0 origin/main` (none → `v0.0.0`).
2. Version: `$ARGUMENTS` if given; otherwise SemVer from commits since the last tag on `origin/dev`
   (`feat` → minor, `fix` only → patch; stay on `v0.x` until M6 is accepted).
3. Changelog: `git log --pretty='%s (%h)' <last-tag>..origin/dev`, grouped by type (Features, Fixes,
   Docs, Tests, Chores). Update `CHANGELOG.md` on `docs/release-<version>` → PR into `dev` → squash-merge.
4. Staging evidence: latest `deploy-staging` run on `dev` (`gh run list --branch dev --limit 3`) and the
   smoke-test result.
5. Open the release PR (merge commit, never squash):
   ```bash
   gh pr create --base main --head dev --title "release: <version>" --body "<changelog + staging evidence + risk/rollback>"
   ```
6. Run `/review-gate <pr>` — security review is mandatory for releases.
7. **Stop.** Tell the human: test on staging, then merge with **"Create a merge commit"**. CI tags and
   deploys production. Never merge into `main` yourself.
