# 0004 — Local API: loopback bind, Host/Origin allowlists, CSRF header, server-checked sessions

- Status: accepted; decision 7 and the dev-proxy alternative under Consequences superseded by
  [0006](0006-dev-proxy-preserves-host-origin.md)
- Date: 2026-11-01
- Deciders: product owner (PLAN.md §7: local page, single password, `AUTH_ENABLED=false` for localhost);
  architect (proposed in PR #4 after security review) for how "localhost only" is enforced

## Context
- PLAN §7 serves the UI and `/api` from `python -m app.serve` on `http://localhost:8000`, protected by one
  password, and allows `AUTH_ENABLED=false` "for localhost". It does not say how "localhost" is enforced.
- Any web page the owner visits can attack a localhost server: **DNS rebinding** (a page rebinds its own
  hostname to 127.0.0.1 and becomes same-origin) and **CSRF** with CORS "simple requests". The bodyless
  `POST /api/process`, `POST /api/posts/{id}/retry` and `DELETE` need no preflight, and `SameSite=Strict`
  does not isolate by port — any other `localhost:<port>` dev server counts as same-site.
- A bind to `0.0.0.0` (common in Docker setups) would expose the API and a plain-HTTP password to the LAN.
- A stateless signed cookie with only a client-side `Max-Age` stays valid forever if copied.

## Decision
Normative rules in [api.md §1.1–§1.3](../contracts/api.md#11-network-boundary-localhost-only):
1. Bind `127.0.0.1` only; refuse to start on any other host. A future hosted mode needs a new ADR and must
   still refuse `AUTH_ENABLED=false` on a non-loopback bind.
2. `Host` allowlist on every request (`127.0.0.1:<port>`, `localhost:<port>`) → `421` otherwise.
3. `Origin`, when present, must be in the allowlist → `403` otherwise.
4. Every non-GET `/api/*` request, bodyless or not, carries `X-Requested-With: insta-saver` → `403`
   otherwise; requests with a body also need `Content-Type: application/json`.
5. No CORS at all.
6. Sessions: itsdangerous timed token, verified server-side with `max_age` = 30 days; key derived from
   `SESSION_SECRET` + a hash of `APP_PASSWORD`; rotating `SESSION_SECRET` is the kill switch. Fail closed at
   startup on an empty/short password or short secret. Login rate limit checked before the compare, keyed on
   the socket peer. CSP and related headers on every response.
7. An optional `API_DEV_ORIGIN` (loopback `http` only) lets the Vite dev server proxy `/api`.

## Alternatives considered
| Option | Why not |
|---|---|
| Rely on `SameSite=Strict` + JSON content type only | Bodyless POST/DELETE are simple requests; other localhost ports are same-site; useless with auth off |
| CSRF tokens (double-submit) | Works, but more moving parts than a custom header for a same-origin SPA with no CORS |
| `Sec-Fetch-Site` checks only | Not sent by every client; fine as an extra later, not as the only defence |
| Server-side session table | Needs storage and cleanup; a timed signed token + secret rotation covers one user |
| Allow LAN access (phone on Wi-Fi) now | Plain HTTP password on the LAN; PLAN §8 already plans a hosted deploy for phone use |

## Consequences
- Easier: a verbatim build is safe against rebinding/CSRF with auth on or off; every rule has a named test.
- Harder: the SPA must send the custom header; dev needs `API_DEV_ORIGIN` (or a proxy that rewrites
  `Host`/`Origin`); test clients must use `http://127.0.0.1:8000` as base URL; with a loopback bind the login
  rate limit is effectively global.
- Contracts: `api.md` §1.
- Agents: web-engineer (middleware, settings validation, SPA header, tests), devops-engineer (`API_HOST`,
  `API_PORT`, `API_DEV_ORIGIN`, `APP_PASSWORD`, `SESSION_SECRET` in `.env.example`), security-reviewer.
