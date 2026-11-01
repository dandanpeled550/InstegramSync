#!/usr/bin/env bash
# PostToolUse (Edit|Write|MultiEdit): format the touched file with the area's formatter, if installed.
# Never fails the tool call.
set -u
file=$(jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
[ -n "$file" ] && [ -f "$file" ] || exit 0

case "$file" in
  *.py)
    command -v ruff >/dev/null 2>&1 && ruff format --quiet "$file" >/dev/null 2>&1 ;;
  */supabase/functions/*.ts|*/supabase/functions/*.tsx)
    command -v deno >/dev/null 2>&1 && deno fmt --quiet "$file" >/dev/null 2>&1 ;;
  */frontend/*.ts|*/frontend/*.tsx|*/frontend/*.css|*/frontend/*.json)
    root="${file%%/frontend/*}/frontend"
    [ -x "$root/node_modules/.bin/prettier" ] && "$root/node_modules/.bin/prettier" --write --log-level silent "$file" >/dev/null 2>&1 ;;
esac
exit 0
