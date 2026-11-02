# 0006 — Dev proxy keeps the browser's Host and Origin; `API_DEV_ORIGIN` is matched exactly

- Status: accepted
- Date: 2026-11-01
- Deciders: product owner (the human; accepts it by approving PR #13, as for every ADR in a contract PR);
  architect (security review R2-2 on PR #4 and SF3 on PR #13)
- Supersedes: the dev-server parts of [ADR 0004](0004-local-api-network-boundary.md), namely decision 7 and
  the "or a proxy that rewrites `Host`/`Origin`" option under Consequences. The rest of ADR 0004 stands.

## Context
- ADR 0004 lets the Vite dev server proxy `/api` and lists two ways to make that pass the API's checks: set
  `API_DEV_ORIGIN`, **or** use a proxy that rewrites `Host`/`Origin`.
- A proxy with `changeOrigin: true` plus an `Origin` rewrite makes every proxied request look like
  `127.0.0.1:8000`. The API's `Host` and `Origin` checks then never see a rebound hostname, and the only
  DNS-rebinding defence left is Vite's own host check.
- Attack: dev runs with `AUTH_ENABLED=false`, and Vite's host check is off (`server.allowedHosts: true`) or
  missing (old Vite). A rebound page on `evil.example:5173` is then same-origin with Vite. It can send the
  custom CSRF header and read, retry or delete every post through the proxy.
- ADR 0004 says `API_DEV_ORIGIN` must be a loopback `http` origin but doesn't say how it is compared. A
  prefix match would let `http://localhost:51730` (or `http://localhost:5173.evil.example`) through.

## Decision
1. The only supported dev setup is `API_DEV_ORIGIN` plus a Vite proxy that **keeps** the browser's `Host` and
   `Origin`: `changeOrigin: false` (Vite's default) and no header rewriting. The API checks them as usual.
2. Vite's `server.host` is `"127.0.0.1"` (never `true` / `0.0.0.0`, and not `localhost`, which may resolve
   to `::1`), its host check stays on (`server.allowedHosts` is never `true`), and `server.cors: false`
   (Vite's default CORS middleware runs before the proxy and admits any local origin on any port). `vite
   preview` gets the same rules (`preview.host`, `preview.allowedHosts`, `preview.strictPort`,
   `preview.cors: false`), because it reuses `server.proxy`. Vite is pinned to an exact version: the latest
   patch of a currently supported major with no open security advisory at pin time, kept current by
   Dependabot and checked by `npm audit` in CI (api.md §1.1). No fixed version is recorded here as a floor:
   the host check and restricted CORS default date from 6.0.9 (CVE-2025-24010), but later advisories make
   any fixed floor stale. This is defence in depth, not the main control.
3. `API_DEV_ORIGIN` is exactly `http://<localhost|127.0.0.1>:<port>`: explicit port, no path (not even `/`),
   query, fragment or userinfo. Anything else → `serve.py` refuses to start. The origin and its
   `<host>:<port>` are compared with the request's `Origin` and `Host` as **whole strings**, never as
   prefixes.

Normative text and tests: [api.md §1.1, §1.3](../contracts/api.md#11-network-boundary-localhost-only).

## Alternatives considered
| Option | Why not |
|---|---|
| Proxy that rewrites `Host`/`Origin` (ADR 0004's second option) | Hides rebound hostnames from the API; only Vite's host check remains (Context) |
| Prefix or `startswith` match on `API_DEV_ORIGIN` | Admits `localhost:51730` and `localhost:5173.evil.example` |
| No dev proxy: the SPA calls `127.0.0.1:8000` directly | Cross-origin, so it would need CORS, which ADR 0004 forbids |

## Consequences
- Easier: the API's checks stay the single source of truth in dev too; misconfiguration fails at startup.
- Harder: the dev URL must match `API_DEV_ORIGIN` exactly (use `strictPort` so Vite doesn't drift to
  another port, otherwise requests get `421`/`403`).
- Contracts: `api.md` §1.1 (dev server rules), §1.3 (three new test rows: origin parsing, exact match, Vite
  config).
- Agents: web-engineer (`serve.py` settings validation, middleware, `frontend/vite.config.*`, tests),
  devops-engineer (`.env.example` comment for `API_DEV_ORIGIN`), security-reviewer.
