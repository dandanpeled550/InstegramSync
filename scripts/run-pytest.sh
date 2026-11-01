#!/usr/bin/env bash
# Run pytest from the repository root so --ignore / paths mean what they say.
#   scripts/run-pytest.sh unit   # everything under tests/ except tests/db
#   scripts/run-pytest.sh db     # tests/db only (needs a running local Supabase)
# Config comes from backend/pyproject.toml (-c) with the repo root as rootdir.
# While there are no test files yet, the run counts as success. Pytest exit code 5 (nothing collected) is
# accepted; every other non-zero code (including 4, a usage error) fails. A missing tests directory is
# handled up front (skip), so exit 4 can only mean a real usage error.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

mode="${1:-unit}"
case "$mode" in
  unit) target=tests; extra=(--ignore=tests/db) ;;
  db)   target=tests/db; extra=() ;;
  *) echo "usage: $0 unit|db" >&2; exit 2 ;;
esac

if [[ ! -d "$target" ]] || [[ -z "$(find "$target" \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | head -1)" ]]; then
  echo "pytest($mode): no test files under $target yet, skipping."
  exit 0
fi

rc=0
uv run --project backend pytest -c backend/pyproject.toml --rootdir . ${extra[@]+"${extra[@]}"} "$target" || rc=$?
if [[ $rc -eq 5 ]]; then
  echo "pytest($mode): no tests collected, treating as success."
  exit 0
fi
exit "$rc"
