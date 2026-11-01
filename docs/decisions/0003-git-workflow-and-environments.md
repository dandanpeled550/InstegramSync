# 0003 — Git workflow, environments and backward-compatible migrations

- Status: accepted; decision 2 (merges) superseded by [0005](0005-merge-methods-with-back-merges.md)
- Date: 2026-11-01
- Deciders: product owner (AGENTS_PLAN.md §15); architect (proposed in PR #4) for the migration rules (5)

## Context
- Many agents build in parallel in worktrees; their work must integrate safely and stay revertable.
- Production (the real bot's webhook) must always work; changes need a place to be tested first.
- Deploys touch live infrastructure and must not depend on anyone's laptop state.
- The deployed Edge Function and the laptop worker can run different code versions at the same time, against
  the same database.
- The repo is public (so branch protection is free on GitHub Free) — everything committed is world-readable.

## Decision
1. **Branches:** `main` = production, always live; `dev` = staging and the default branch. All work branches
   from `origin/dev` as `feat/<milestone>-<slug>`, `fix/`, `test/`, `docs/`, `chore/`, `refactor/`; hotfixes
   branch from `main` as `hotfix/<slug>` and are back-merged into `dev`.
2. **Merges:** feature → `dev` by **squash** (tech-lead, after required checks + agent reviews);
   `dev` → `main` by **merge commit** through a `release: vX.Y.Z` PR that only the human merges.
3. **Commits:** Conventional Commits with an area scope; agents add a `Co-Authored-By` model trailer. Never
   commit/push to `dev`/`main`, force-push (except `--force-with-lease` on one's own branch) or `--no-verify`.
4. **Environments:** local (`supabase start`, fixture replay) · staging (`dev` → `insta-saver-dev`) ·
   production (`main` → `insta-saver-prod`). **CI is the only deployer**: merge to `dev` deploys staging;
   merge to `main` validates the version, deploys production, then tags and publishes release notes.
   `make process-prod` runs only from a clean, tagged `main` checkout.
5. **Migrations are backward-compatible: expand → migrate → contract.** Additive changes ship first; code
   switches next; removals come in a later release and need an ADR + human approval. Applied migrations are
   never edited — fix forward. Rules in [schema.md §6](../contracts/schema.md#6-migration-rules-expand--migrate--contract).
6. **Contracts first:** contract and ADR PRs (`docs/…` branches, scope `contracts`/`docs`) merge into `dev`
   before dependent feature branches start.
7. **Public-repo hygiene:** no secrets, personal data, real Instagram content, media or the real eval set in
   git; fixtures are synthetic or scrubbed; workflows use `pull_request`, never `pull_request_target`. Secrets
   live only in: GitHub Environments (CI), Supabase secrets (Edge Functions), the laptop's gitignored
   `.env.<env>` files (service-role key, `DATABASE_URL`, `APP_PASSWORD`, `SESSION_SECRET`, model API keys),
   and the `app_secrets` table (the Instagram token, service-role only).

## Alternatives considered
| Option | Why not |
|---|---|
| Trunk-based (only `main`) | No staging soak; every merge hits the real bot |
| GitFlow with long-lived release branches | Too much ceremony for one human; optional `release/vX.Y.Z` covers the rare freeze |
| Squash `dev` → `main` | Breaks shared history; the next release PR would re-show old commits |
| Deploys from a laptop (`supabase db push` by hand) | Unreproducible, unaudited; bypasses checks |
| Migrations that rename/drop in one step | Breaks whichever of receiver/worker is still on the old version |
| Private repo | Branch protection/rulesets would need a paid plan |

## Consequences
- Easier: every change is one revertable commit on `dev`; production only moves on an explicit human merge;
  staging mirrors production; rollback = revert PR + redeploy previous tag; DB problems are fixed forward.
- Harder: schema changes take two or three releases; contract PRs gate builders; reviewer agents post
  statuses rather than real approvals (shared `gh` identity — see M0 open question Q2).
- Contracts: `schema.md` §6 (migration rules).
- Agents: all builders (branching, commits, PRs), devops-engineer (CI, deploy workflows, branch protection),
  data-engineer (migration discipline), tech-lead (merges, releases), human (merges to `main`, secrets).
