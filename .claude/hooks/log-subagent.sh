#!/usr/bin/env bash
# SubagentStart / SubagentStop: append a line to .claude/logs/activity.log (gitignored).
set -u
input=$(cat)
event=$(printf '%s' "$input" | jq -r '.hook_event_name // "?"' 2>/dev/null)
agent=$(printf '%s' "$input" | jq -r '.agent_type // "?"' 2>/dev/null)
id=$(printf '%s' "$input" | jq -r '.agent_id // "?"' 2>/dev/null)
dir="${CLAUDE_PROJECT_DIR:-.}/.claude/logs"
mkdir -p "$dir" 2>/dev/null
printf '%s %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$agent" "$id" >> "$dir/activity.log" 2>/dev/null
exit 0
