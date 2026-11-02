# Contributing

The full rationale lives in [docs/AGENTS_PLAN.md §15](docs/AGENTS_PLAN.md). This is the short version
for humans.

## Branches

| Branch | Meaning | Who merges into it |
|---|---|---|
| `main` | Production — always live and working | The owner, via release or hotfix PRs only |
| `dev` (default) | Staging — where things are tested | `tech-lead` agent, after checks + reviews pass |
| `feat/…`, `fix/…`, `test/…`, `docs/…`, `chore/…`, `refactor/…` | One task each, from `dev` | — |
| `hotfix/…` | Urgent production fix, from `main` | — |

## Flow

1. `git switch dev && git pull --ff-only && git switch -c feat/m3-pipeline-stage0-1`
2. Commit with Conventional Commits: `feat(pipeline): add caption precheck`
3. `gh pr create --base dev --draft` — fill the template.
4. Mark ready when your local checks pass. CI + agent reviews must be green.
5. Feature PRs are **squash-merged** into `dev`. Merging into `dev` deploys to staging.
6. Release: PR `dev → main` titled `release: vX.Y.Z`, **merge commit** (never squash). Merging deploys
   to production and tags the release.
7. Hotfix: `hotfix/<slug>` from `main` → PR to `main` → then PR `main → dev` (back-merge).

## Checks

PRs run `ci/lint`, `ci/typecheck`, `ci/test` and `ci/secrets`; PRs into `main` also run `ci/source-branch`.
`security-gate` decides whether `agent-review/security` is needed (the `security` label or a trust-boundary
path such as `.github/**`, `scripts/**` or `supabase/**`). Fork PRs get a read-only token, so the gate status
cannot be posted and they stay blocked (fail-closed); maintainers re-open them from a branch in this repo.

Warning: re-pushing a fork PR's code into a branch of this repository gives that code a write-scoped token
in CI (a PR can modify its own workflows). Review the full diff, including `.github/**`, before doing it.

The security gate is not tamper-proof: a PR can modify its own gate. The `.github/**` path match only catches
honest mistakes. The backstop is human approval of each merge, plus the rule that any PR touching `.github/**`
or `security-gate.yml` gets `security-reviewer` and a human flag.

## Never

- Commit or push directly to `dev` or `main`.
- Force-push shared branches, use `--no-verify`, or rewrite shared history.
- Commit secrets, `.env*` files (except `.env.example`), personal data, media, or the real eval dataset.

## A secret leaked into git

1. **Rotate it immediately** at the provider (Meta, Supabase, Google, TypeSafe). The repo is public; bots
   scan new commits within minutes, so deleting the commit is not enough.
2. Update the secret in Supabase / GitHub Environments / local `.env.*`.
3. Remove it from the code in a normal PR; open a `security` issue describing what was rotated.

## Local setup

See the `Makefile` (`make help`) and `.env.example`.

### Local Supabase exposes ports on all interfaces

The local Supabase stack (CLI 2.122.0) publishes its ports on all network interfaces, not just localhost:
54321 (API), 54322 (Postgres), 54323 (Studio, no login) and 54324 (Mailpit). The local demo keys are well
known, so anyone on the same network could reach your local database. On Docker Desktop for Mac the
listener is Docker Desktop's own proxy (`com.docker.backend`), so neither Docker's `"ip"` setting nor
network options change it (verified 2026-11-02, Docker Desktop 4.54.0).

What to do instead:

- Run the stack only on trusted networks, and run `supabase stop` when you are done.
- Keep only synthetic data in the local database.
- Optional, untested: block incoming connections for Docker in the macOS firewall (System Settings,
  Network, Firewall, Options).

See what is actually exposed:

```sh
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':5432[0-9]'   # "*:5432x" means all interfaces
```

On Linux use `sudo lsof -nP -iTCP -sTCP:LISTEN` or `ss -ltn`.
