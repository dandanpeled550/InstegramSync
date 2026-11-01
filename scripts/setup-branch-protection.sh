#!/usr/bin/env bash
# One-time (and re-runnable) GitHub setup per docs/AGENTS_PLAN.md §15.5 and §15.10. Run by the HUMAN, not by agents.
#
#   scripts/setup-branch-protection.sh --dry-run   # read-only: print what would change
#   scripts/setup-branch-protection.sh             # apply
#
# Idempotent: rulesets are looked up by name and updated in place, otherwise created.
# Needs: gh (logged in as a repo admin), jq. Override the target with REPO=owner/name.
#
# Rulesets (no bypass actors):
#   protect-main: PR required, merge-commit only, required checks (incl. ci/source-branch), up to date,
#                 no force push, no deletion.
#   protect-dev : same but squash only and without ci/source-branch.
# `agent-review/security` is required unconditionally; .github/workflows/security-gate.yml posts
# `success: not required` when the PR does not touch the trust boundary.
# `ci/*` required checks are bound to GitHub Actions (integration_id 15368) so no other app can satisfy them.
# Tag ruleset protect-release-tags: no deletion, no moving of v* tags (see the notice about actor scoping).
# Repo settings: auto-delete head branches; approval for workflows from outside contributors; default workflow
# token read-only; Actions may not create/approve PRs; SHA-pinning of actions required (when the API allows).
#
# HONEST LIMITS: none of this stops a PR from changing its own workflows (a PR can add a workflow with
# `statuses: write` that forges any status). The backstop today is human approval of each merge plus the
# tech-lead rule that any PR touching .github/** or security-gate.yml gets security-reviewer and a human flag
# (accepted risk, board item Q2).
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
info="$(gh api "repos/$REPO")"
OWNER_TYPE="$(jq -r '.owner.type' <<<"$info")"
REPO_ID="$(jq -r '.id' <<<"$info")"
DEFAULT_BRANCH="$(jq -r '.default_branch' <<<"$info")"

echo "Repository: $REPO (owner type: $OWNER_TYPE, default branch: $DEFAULT_BRANCH)"
[[ $DRY_RUN -eq 1 ]] && echo "DRY RUN: nothing will be changed."
[[ "$DEFAULT_BRANCH" == "dev" ]] || echo "WARNING: default branch is '$DEFAULT_BRANCH', expected 'dev'."

COMMON_CHECKS=("ci/lint" "ci/typecheck" "ci/test" "ci/migrations" "ci/secrets" "agent-review/code" "agent-review/security")

# "Require workflows" rules are only offered to organization-owned repositories.
WORKFLOW_RULE_SUPPORTED=0
if [[ "$OWNER_TYPE" == "Organization" ]]; then
  WORKFLOW_RULE_SUPPORTED=1
  echo "Require-workflows rule: supported (organization-owned). security-gate.yml will be pinned to dev."
else
  echo "NOTICE: 'require workflows' rule NOT available (repo is owned by a $OWNER_TYPE, not an organization)."
  echo "        A PR can therefore modify its own gate, and could add a workflow with 'statuses: write' that"
  echo "        forges ANY status. The .github/** path match only catches honest mistakes. The real backstop is"
  echo "        human approval of each merge plus the rule that .github/** PRs get security-reviewer and a human"
  echo "        flag (accepted risk, board item Q2)."
fi

# build_ruleset <name> <branch> <merge_method> <extra-check-or-empty> <with-workflows 0|1>
build_ruleset() {
  local name="$1" branch="$2" method="$3" extra="$4" with_wf="$5"
  local checks=("${COMMON_CHECKS[@]}")
  [[ -n "$extra" ]] && checks+=("$extra")
  printf '%s\n' "${checks[@]}" | jq -R . | jq -s \
    --arg name "$name" --arg ref "refs/heads/$branch" --arg method "$method" \
    --argjson wf "$with_wf" --argjson repo_id "$REPO_ID" '
    {
      name: $name,
      target: "branch",
      enforcement: "active",
      bypass_actors: [],
      conditions: { ref_name: { include: [$ref], exclude: [] } },
      rules: ([
        { type: "deletion" },
        { type: "non_fast_forward" },
        { type: "pull_request", parameters: {
            required_approving_review_count: 0,
            dismiss_stale_reviews_on_push: false,
            require_code_owner_review: false,
            require_last_push_approval: false,
            required_review_thread_resolution: false,
            allowed_merge_methods: [$method] } },
        { type: "required_status_checks", parameters: {
            strict_required_status_checks_policy: true,
            do_not_enforce_on_create: false,
            required_status_checks: (map(if startswith("ci/")
              then { context: ., integration_id: 15368 } else { context: . } end)) } }
      ] + (if $wf == 1 then [
        { type: "workflows", parameters: { workflows: [
          { repository_id: $repo_id, path: ".github/workflows/security-gate.yml", ref: "refs/heads/dev" } ] } }
      ] else [] end))
    }'
}

apply_ruleset() { # json
  local json="$1" name id
  name="$(jq -r .name <<<"$json")"
  id="$(gh api --paginate "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$name\") | .id" | head -1)"
  if [[ -n "$id" ]]; then echo "== ruleset '$name': UPDATE (id $id)"; else echo "== ruleset '$name': CREATE"; fi
  jq -c '{name, target, enforcement, ref: .conditions.ref_name.include[0],
          merge_methods: ([.rules[] | select(.type=="pull_request") | .parameters.allowed_merge_methods] | first),
          required_checks: ([.rules[] | select(.type=="required_status_checks")
            | [.parameters.required_status_checks[] | if .integration_id then "\(.context)@actions" else .context end]] | first),
          rules: [.rules[].type]}' <<<"$json"
  [[ $DRY_RUN -eq 1 ]] && return 0
  if [[ -n "$id" ]]; then
    gh api -X PUT "repos/$REPO/rulesets/$id" --input - <<<"$json" >/dev/null
  else
    gh api -X POST "repos/$REPO/rulesets" --input - <<<"$json" >/dev/null
  fi
  echo "   applied."
}

apply_with_fallback() { # name branch method extra
  local json
  json="$(build_ruleset "$1" "$2" "$3" "$4" "$WORKFLOW_RULE_SUPPORTED")"
  if [[ $WORKFLOW_RULE_SUPPORTED -eq 1 && $DRY_RUN -eq 0 ]]; then
    if ! apply_ruleset "$json"; then
      echo "NOTICE: applying with the workflows rule failed; retrying without it."
      apply_ruleset "$(build_ruleset "$1" "$2" "$3" "$4" 0)"
    fi
  else
    apply_ruleset "$json"
  fi
}

apply_with_fallback "protect-main" "main" "merge" "ci/source-branch"
apply_with_fallback "protect-dev" "dev" "squash" ""

# Release tags: nobody may delete or move a published v* tag. The release workflow only creates tags, so
# creation stays open. A user-owned repo cannot scope this rule by actor, so anyone with write access can still
# CREATE a v* tag; that is why scripts/prod-guard.sh also requires HEAD == origin/main on that tag.
TAG_RULESET='{
  "name": "protect-release-tags", "target": "tag", "enforcement": "active", "bypass_actors": [],
  "conditions": { "ref_name": { "include": ["refs/tags/v*"], "exclude": [] } },
  "rules": [ { "type": "deletion" }, { "type": "non_fast_forward" }, { "type": "update" } ]
}'
apply_ruleset "$TAG_RULESET"
if [[ "$OWNER_TYPE" != "Organization" ]]; then
  echo "NOTICE: tag rule cannot be limited to the release workflow on a user-owned repo; v* tags are"
  echo "        protected against deletion and moving, but tag CREATION is not restricted to CI."
fi

echo "== repo setting: delete head branches after merge -> true"
if [[ $DRY_RUN -eq 0 ]]; then
  gh api -X PATCH "repos/$REPO" -F delete_branch_on_merge=true >/dev/null
fi

echo "== repo setting: require approval for workflows from all outside contributors"
if [[ $DRY_RUN -eq 0 ]]; then
  gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
    -f approval_policy=all_external_contributors >/dev/null \
    || echo "NOTICE: could not set fork-PR approval; set it in Settings -> Actions -> General."
fi

echo "== repo setting: default workflow token read-only; Actions may not create or approve PRs"
if [[ $DRY_RUN -eq 0 ]]; then
  gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
    -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false >/dev/null \
    || echo "NOTICE: could not set workflow permissions; set them in Settings -> Actions -> General."
fi

echo "== repo setting: require actions to be pinned to a full commit SHA"
if [[ $DRY_RUN -eq 0 ]]; then
  perms="$(gh api "repos/$REPO/actions/permissions")"
  if jq -e 'has("sha_pinning_required")' <<<"$perms" >/dev/null; then
    jq '{enabled, allowed_actions, sha_pinning_required: true}' <<<"$perms" \
      | gh api -X PUT "repos/$REPO/actions/permissions" --input - >/dev/null \
      || echo "NOTICE: could not enable SHA pinning; set it in Settings -> Actions -> General."
  else
    echo "NOTICE: the API does not expose sha_pinning_required for this repo; enable it in Settings -> Actions -> General if offered."
  fi
fi

[[ $DRY_RUN -eq 1 ]] && echo "Dry run complete. Re-run without --dry-run to apply (after M0.2 and M0.6 have merged)."
exit 0
