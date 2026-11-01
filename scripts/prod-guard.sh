#!/usr/bin/env bash
# Guard for `make process-prod`. Exits 0 only when this checkout is:
#   * on branch main, working tree clean,
#   * exactly equal to origin/main (after a fresh fetch),
#   * on a strict SemVer tag (^v[0-9]+\.[0-9]+\.[0-9]+$) that also exists on the remote at the same commit.
# Prints the tag on success.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

refuse() { echo "process-prod: refusing, $1" >&2; exit 1; }

git fetch --quiet origin main || refuse "git fetch origin main failed"
branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || refuse "on '$branch' (need main)"
[[ -z "$(git status --porcelain)" ]] || refuse "working tree not clean"
head="$(git rev-parse HEAD)"
[[ "$head" == "$(git rev-parse origin/main)" ]] || refuse "HEAD is not origin/main"

tag=""
while IFS= read -r t; do
  [[ "$t" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] && tag="$t"
done < <(git tag --points-at HEAD)
[[ -n "$tag" ]] || refuse "HEAD has no strict SemVer tag (vX.Y.Z)"

# Annotated tags list the tag object plus a peeled ^{} line; the peeled commit (or the lightweight ref) must equal HEAD.
remote="$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" | awk 'END{print $1}')"
[[ "$remote" == "$head" ]] || refuse "tag $tag is not on the remote at HEAD"

echo "process-prod: checks passed ($tag)"
