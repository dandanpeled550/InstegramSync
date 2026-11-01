---
name: review-gate
description: Run the agent review gate on an Insta Saver PR — code-reviewer always, security-reviewer when the PR crosses the trust boundary — and collect the agent-review/* statuses. Use before merging any PR into dev and on release PRs.
argument-hint: <pr-number>
---

# /review-gate $ARGUMENTS

1. `gh pr view $ARGUMENTS --json number,title,labels,baseRefName,headRefOid,files` and `gh pr checks $ARGUMENTS`.
   If required CI checks aren't green yet, stop and report — don't review a red PR.
2. Decide whether security review is needed: label `security`, base `main`, or any changed file under
   `supabase/functions/`, `supabase/migrations/`, `backend/app/api/`, `backend/app/meta/`, `.github/workflows/`,
   `fixtures/`, `prompts/`, or anything touching auth, secrets, storage or CI.
3. Spawn `code-reviewer` (and `security-reviewer` if needed) in parallel with: the PR number, the head SHA,
   the linked task brief, and the contracts the diff touches.
4. Each reviewer posts its PR comment and sets `agent-review/code` / `agent-review/security` on the head SHA.
5. Report the verdicts. On any `failure`, send the blocking findings to the owning agent and re-run this
   gate after their fix (statuses are per commit, so a new push needs a new review).
