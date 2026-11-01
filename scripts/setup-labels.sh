#!/usr/bin/env bash
# Create / update the GitHub labels used by PRs (idempotent). Needs `gh` logged in with repo access.
# Usage: scripts/setup-labels.sh [--dry-run]
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

label() { # name color description
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "would ensure label: $1"
  else
    gh label create "$1" --color "$2" --description "$3" --force >/dev/null
    echo "ok: $1"
  fi
}

for n in 0 1 2 3 4 5 6; do
  label "M$n" "1d76db" "Milestone M$n"
done

# Scopes from CLAUDE.md (commit scopes).
for scope in receiver db pipeline ai web devops contracts research tasks evals tests; do
  label "area:$scope" "0e8a16" "Area: $scope"
done

# One label per agent definition.
for f in "$ROOT"/.claude/agents/*.md; do
  name="$(basename "$f" .md)"
  label "agent:$name" "5319e7" "Authored by the $name agent"
done

label "security" "d93f0b" "Crosses the trust boundary; needs agent-review/security"
