#!/usr/bin/env bash
# Guard for `make process-prod`. Exits 0 only when this checkout is:
#   * on branch main, working tree clean,
#   * exactly equal to the REMOTE main tip (git ls-remote, not the possibly stale local origin/main),
#   * on exactly one strict SemVer tag (^v[0-9]+\.[0-9]+\.[0-9]+$) that also exists on the remote at the same commit.
# Prints the tag on success.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

refuse() { echo "process-prod: refusing, $1" >&2; exit 1; }

git fetch --quiet origin main || refuse "git fetch origin main failed"
branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || refuse "on '$branch' (need main)"
[[ -z "$(git status --porcelain)" ]] || refuse "working tree not clean"
head="$(git rev-parse HEAD)"
remote_main="$(git ls-remote origin refs/heads/main | awk 'NR==1{print $1}')" || refuse "git ls-remote origin failed"
[[ -n "$remote_main" ]] || refuse "could not read origin main"
[[ "$head" == "$remote_main" ]] || refuse "HEAD is not the remote main tip"

tag=""; count=0
while IFS= read -r t; do
  if [[ "$t" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then tag="$t"; count=$((count + 1)); fi
done < <(git tag --points-at HEAD)
[[ $count -le 1 ]] || refuse "more than one SemVer tag points at HEAD (ambiguous release)"
[[ -n "$tag" ]] || refuse "HEAD has no strict SemVer tag (vX.Y.Z)"

# Annotated tags list the tag object plus a peeled ^{} line; the peeled commit (or the lightweight ref) must equal HEAD.
remote="$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" | awk 'END{print $1}')"
[[ "$remote" == "$head" ]] || refuse "tag $tag is not on the remote at HEAD"

echo "process-prod: checks passed ($tag)"
