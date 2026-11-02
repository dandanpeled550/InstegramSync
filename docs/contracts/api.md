# Local API contract — v0

- Version: v0.1 (M0.1b) · 2026-11-01 · owner: `architect` — v0.1: `OPTIONS` answered before Origin/CSRF,
  GET/HEAD side-effect rule, exact `API_DEV_ORIGIN` and Vite proxy rules ([ADR 0006](../decisions/0006-dev-proxy-preserves-host-origin.md)),
  rate-limit wording, `insta_saver_session` cookie, single session key, in-process `rerun_requested`
  · round 2: Vite `cors: false`, `preview.*`, `127.0.0.1` dev host, cookie residual risk, async handlers for
  `rerun_requested` · round 3: Vite exact pin on a supported major maintained by Dependabot + `npm audit`
  (replaces the 6.0.9 floor), tests for the background task's final step · round 4: CI installs with
  `npm ci` from the committed lockfile
- Implemented by `web-engineer` (FastAPI, `backend/app/api/**`, served by `python -m app.serve` on
  `http://127.0.0.1:8000`, also reachable as `http://localhost:8000`); consumed by the Vite/React SPA served
  from the same origin. The network boundary (§1.1) and auth (§1.2) rules are normative.
- Source: [PLAN.md §7](../PLAN.md#7-ui--local-web-page).

## 1. Conventions

- Base path `/api`. JSON in and out (`Content-Type: application/json; charset=utf-8`), UTF-8, field names
  `snake_case`. Timestamps are ISO-8601 UTC with `Z` (`"2026-11-01T09:58:41Z"`). Ids are UUID strings.
- Every non-2xx response has this body:

  ```json
  { "error": { "code": "not_found", "message": "Post not found" } }
  ```

  `code` is stable and machine-readable; `message` is for humans and may change. FastAPI's default
  `{"detail": ...}` validation body is replaced by this envelope (`422` + `validation_error`).

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | malformed JSON, bad cursor |
| 401 | `unauthorized` | missing/invalid/expired session (auth enabled) |
| 401 | `invalid_password` | wrong password on login |
| 403 | `forbidden_origin` | `Origin` header present but not in the allowlist (§1.1) |
| 403 | `missing_csrf_header` | non-GET `/api/*` request without `X-Requested-With: insta-saver` (§1.1) |
| 404 | `not_found` | unknown post id |
| 405 | `method_not_allowed` | unsupported method, including every `OPTIONS` preflight (§1.1) |
| 409 | `invalid_state` | action not allowed in the post's current status |
| 409 | `already_running` | a worker run is already in progress |
| 415 | `unsupported_media_type` | request with a body whose `Content-Type` is not `application/json` |
| 421 | `invalid_host` | `Host` header not in the allowlist (§1.1) — applies to static files too |
| 422 | `validation_error` | well-formed request with invalid values (unknown category, `q` too long, ...) |
| 429 | `rate_limited` | too many failed logins (§1.2); response has `Retry-After` |
| 502 | `storage_error` | Supabase Storage call failed |
| 503 | `database_unavailable` | Postgres unreachable |
| 500 | `internal` | anything else (no stack traces or secrets in `message`) |

### 1.1 Network boundary ("localhost only")

The server is reachable only from this machine, and only pages it served itself can drive it. Checks run in
this order, before auth and before any handler. The first failing check answers:

1. **Bind.** `serve.py` binds `API_HOST` (default and only supported v0 value `127.0.0.1`) on `API_PORT`
   (default `8000`). It refuses to start (non-zero exit, clear message) for any other `API_HOST` — in
   particular `0.0.0.0`, `::` or a LAN address. A future hosted mode (PLAN §8 "UI from
   your phone") is a contract change with an ADR; even then, a non-loopback bind with `AUTH_ENABLED=false`
   refuses to start. The URL `serve.py` prints, and the one docs use, is `http://127.0.0.1:<API_PORT>`
   (not `localhost`, which may resolve to `::1`, where another local process could be listening).
2. **Host allowlist** (DNS-rebinding defence), every request incl. static files: `Host` must equal
   `127.0.0.1:<API_PORT>` or `localhost:<API_PORT>` (plus the dev origin's host, below). Anything else,
   or a missing `Host` → `421 invalid_host`.
3. **No CORS.** `OPTIONS` on any path → `405 method_not_allowed`, before the Origin and CSRF checks, so every
   preflight gets the same answer whatever its `Origin`. No CORS middleware and no `Access-Control-*` header on
   any response. Same-origin only.
4. **Origin allowlist**, every `/api/*` request: if `Origin` is present it must equal
   `http://127.0.0.1:<API_PORT>` or `http://localhost:<API_PORT>` (plus the dev origin); anything else,
   including `Origin: null` → `403 forbidden_origin`. A request without `Origin` (curl, tests) passes this
   check.
5. **CSRF header**, every non-`GET`/`HEAD` `/api/*` request — `POST /api/login`, `PATCH`, and **the bodyless
   ones** (`POST /api/process`, `POST /api/posts/{id}/retry`, `DELETE`): it must carry
   `X-Requested-With: insta-saver`, else `403 missing_csrf_header`. A custom header makes every cross-site
   request a CORS preflight, which fails (rule 3). Requests with a body additionally need
   `Content-Type: application/json`, else `415`.

**`GET` and `HEAD` never change state.** No handler for them writes to the database or Storage, starts a
worker run, sets a cookie, or touches the login rate limit. The CSRF exemption in rule 5 depends on this. The
only `GET` routes are `/api/categories`, `/api/posts`, `/api/queue` and the static files (§3). Adding one is a
contract change.

**Dev server** (`API_DEV_ORIGIN`, unset by default). The Vite dev server proxies `/api` to the API:
- `API_DEV_ORIGIN` must be exactly `http://<host>:<port>` with `<host>` = `localhost` or `127.0.0.1` and an
  explicit port: no path (not even a trailing `/`), query, fragment or userinfo, and no other scheme.
  Anything else → `serve.py` refuses to start.
- When set, the origin string is added to the Origin allowlist and `<host>:<port>` to the Host allowlist.
  Both are compared as **whole strings** — never prefix, suffix or substring matches (`http://localhost:5173`
  does not admit `http://localhost:51730`).
- The Vite proxy keeps the browser's `Host` and `Origin` (`changeOrigin: false`, Vite's default, and no
  header rewriting), so the API's own checks still see a rebound hostname. Rules for `frontend/vite.config.*`
  (web-engineer, [ADR 0006](../decisions/0006-dev-proxy-preserves-host-origin.md)):
  - `server.host: "127.0.0.1"` (never `true`, `0.0.0.0` or `localhost`, which may resolve to `::1` — same
    reason as rule 1). The documented dev setup is `API_DEV_ORIGIN=http://127.0.0.1:5173`.
  - `server.allowedHosts` is never `true` (Vite's host check stays on).
  - `server.strictPort: true`, so Vite never drifts to a port that doesn't match `API_DEV_ORIGIN`.
  - `server.cors: false`. Vite's default CORS middleware runs before the proxy and admits any
    `localhost` / `127.0.0.1` origin on any port; with it on, Vite answers `/api` preflights itself and adds
    `Access-Control-Allow-Origin` to proxied responses, breaking rule 3 in dev.
  - `vite preview` follows the same rules (`preview.host: "127.0.0.1"`, `preview.allowedHosts` never `true`,
    `preview.strictPort: true`, `preview.cors: false`), since preview reuses `server.proxy`.
  - **Vite version:** an **exact pin** (no `^` / `~` range) in `frontend/package.json` to the latest patch of
    a **currently supported major** that has no open GitHub security advisory at pin time (as of 2026-11-02
    that means 7.3.7+ or 8.3.3+, per the PR #13 security review). These numbers are an example, not a floor: the
    pin is **maintained by Dependabot** (devops-engineer adds the `npm` ecosystem for `frontend/` to
    `.github/dependabot.yml`) and checked by `npm audit --audit-level=moderate` in CI, which fails on any
    advisory against the pinned version. `frontend/package-lock.json` is committed and CI installs with
    `npm ci` (never `npm install`), so the audit and the build see exactly the locked tree, including
    transitive dependencies. The restricted CORS default and host check this file relies on
    arrived in 6.0.9 (CVE-2025-24010); later advisories (e.g. `server.fs.deny` bypasses, dev-server file read)
    are why an old pin is not enough. web-engineer chooses the version; devops-engineer adds it after human
    approval of the dependency.

### 1.2 Auth and session

- `AUTH_ENABLED` (default **true**; only the exact value `false` disables it — anything else, including
  unset or a typo, means true). When true, every `/api/*` route except `POST /api/login` requires a valid
  session cookie, else `401 unauthorized`. `AUTH_ENABLED=false` is allowed only with a loopback bind (§1.1).
- **Fail closed at startup** when auth is enabled: `serve.py` refuses to start if `APP_PASSWORD` is empty or
  shorter than 12 characters, or if `SESSION_SECRET` is shorter than 32 bytes (generate with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- **Session cookie** `insta_saver_session` (a name no other localhost app uses: cookies are not isolated by
  port, so every server on `localhost` receives it and could overwrite a generic `session`): an itsdangerous
  `URLSafeTimedSerializer` token carrying its issued-at time,
  `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age=2592000`, `Secure` when served over HTTPS (never in v0).
  The **server** enforces the 30 days: it verifies with `loads(token, max_age=2592000)`, so an old cookie is
  rejected even if a client keeps it. The signing key is **one** key derived from `SESSION_SECRET` **and** a
  SHA-256 of `APP_PASSWORD` (e.g. `HMAC-SHA256(key=SESSION_SECRET, msg=SHA-256(APP_PASSWORD))`), so changing
  either one invalidates every session. Pass itsdangerous that single key, **never a list**: a list means
  rotation keys, any one of them verifies, and a password change would not log anyone out. Stateless; no
  server-side session table.
- **Accepted residual risk — cookies are not port-scoped.** The browser sends `insta_saver_session` to every
  server on `127.0.0.1` / `localhost`, whatever the port. Another local server the owner runs could read (and
  replay) it. The unique name only prevents accidental overwrites. Accepted for v0: the threat model is a
  single-user laptop, where a malicious local process already has more direct access (the `.env` with
  `DATABASE_URL`). A hosted mode (PLAN §8) must revisit this (e.g. `__Host-` prefix over HTTPS).
- **Kill switch / logout:** rotating `SESSION_SECRET` (and restarting the server) revokes every session.
- **Login** compares `hmac.compare_digest(given.encode("utf-8"), APP_PASSWORD.encode("utf-8"))` — non-ASCII
  input is a normal wrong password (`401`), never a `500`.
- **Rate limit** is checked **before** the password compare. The server keeps the times of failed logins
  (`401 invalid_password`) from the last 5 minutes. When **5 or more** are recorded, every login attempt —
  even with the correct password — gets `429 rate_limited`, with `Retry-After` = whole seconds (≥ 1) until the
  oldest of them is 5 minutes old. So after 5 failures within 5 minutes, the 6th attempt gets `429`. A `429`
  is not itself a failure (it doesn't extend the lockout); a successful login clears the record. The
  client key is the socket peer address (`request.client.host`), never `X-Forwarded-For` or any other
  header. With a loopback bind this is effectively one global limit — intended. In-process only.
- **Security headers** on every response (SPA and API): `Content-Security-Policy: default-src 'self';
  script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none';
  base-uri 'none'; frame-ancestors 'none'; form-action 'self'` (no inline script), plus
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- The SPA sends `X-Requested-With: insta-saver` on every non-GET request and treats any `401 unauthorized`
  as "show the login screen".

### 1.3 Tests `web-engineer` must write (`tests/api/`, no network)

Test clients use `base_url="http://127.0.0.1:8000"` (not `testserver`) and the CSRF header unless the test
is about it.

| Rule | Test |
|---|---|
| Bind | settings validation refuses `API_HOST` = `0.0.0.0`, `::`, `192.168.1.10`; accepts `127.0.0.1` |
| Dev origin parsing | `API_DEV_ORIGIN` = `http://192.168.1.10:5173`, `https://localhost:5173`, `http://localhost`, `http://localhost:5173/`, `http://localhost:5173/app`, `http://user@localhost:5173`, `http://localhost.evil.example:5173` → refused; `http://localhost:5173` and `http://127.0.0.1:5173` accepted |
| Vite config | (here or as a frontend test) parse `frontend/vite.config.*` (static read or by importing the config object): `server.host` and `preview.host` = `"127.0.0.1"`, `server.cors` and `preview.cors` = `false`, `strictPort: true` on both, no `allowedHosts: true`, no `changeOrigin: true` and no header-rewriting hook on the `/api` proxy; the `vite` entry in `frontend/package.json` is an exact version (matches `^[0-9]+\.[0-9]+\.[0-9]+$`, no range); CI's `npm audit --audit-level=moderate` for `frontend/` passes (devops, not this test) |
| Dev origin exact match | with `API_DEV_ORIGIN=http://localhost:5173`: `Origin: http://localhost:5173` + `Host: localhost:5173` pass; `Origin: http://localhost:51730` → `403`; `Host: localhost:51730` → `421`; `Origin: http://localhost:5173.evil.example` → `403` |
| Fail closed | auth on + `APP_PASSWORD` empty / 11 chars → refuses; `SESSION_SECRET` 31 bytes → refuses; `AUTH_ENABLED` unset, `"False"`, `"0"`, `"no"` → auth on |
| Host | `Host: evil.example:8000`, `Host: 127.0.0.1:9999`, missing Host → `421` on `GET /api/posts` and `GET /`; both allowed hosts pass |
| Origin | `Origin: http://evil.example`, `http://localhost:5173` (dev origin unset), `null` → `403` on a GET and on every non-GET endpoint; allowed origins and no Origin pass |
| CSRF header | each of `POST /api/login`, `POST /api/process`, `POST /api/posts/{id}/retry`, `PATCH`, `DELETE` without the header → `403 missing_csrf_header`; wrong value → `403` |
| Content-Type | `PATCH` / `POST /api/login` with `text/plain` body → `415` |
| No CORS | `OPTIONS` on `/api/posts` and on `/` with `Access-Control-Request-Method` and (a) no `Origin`, (b) an allowed `Origin`, (c) `Origin: http://evil.example` → `405 method_not_allowed` in all three cases; no response in the whole suite has any `Access-Control-*` header |
| GET has no side effects | enumerate the app's routes: the `GET`/`HEAD` routes are exactly `/api/categories`, `/api/posts`, `/api/queue` and the static/SPA fallback; calling each one leaves the DB fakes, the worker starter and the rate-limit state untouched and sets no cookie |
| Session | tampered cookie → `401`; cookie issued 30 days + 1 s ago (frozen clock) → `401`; cookie signed with a previous `SESSION_SECRET` → `401`; cookie issued before an `APP_PASSWORD` change → `401`; a cookie named `session` (not `insta_saver_session`) is ignored → `401` |
| Login | correct → `204` + `insta_saver_session` cookie with the attributes above; wrong → `401`; non-ASCII password → `401` |
| Rate limit | 5 wrong passwords within 5 minutes (frozen clock), then the **correct** password as the 6th attempt → `429` + `Retry-After` ≥ 1; further attempts during the lockout don't extend it — once the oldest failure is 5 min + 1 s old, the correct password → `204`; 4 wrong then correct → `204`, and the record is cleared (4 more wrong then correct → `204`); varying `X-Forwarded-For` does not reset the limit |
| Headers | CSP and the other headers present on `GET /` and `GET /api/queue` |
| Envelope | every error above uses the `{"error": {...}}` body |

### 1.4 Post object

Returned by list and mutation endpoints. Never includes `raw_payload`, `evidence`, `sender_id`,
`search_text`, `media_path`, `claimed_at` or `message_mid`.

```json
{
  "id": "6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00",
  "title": "Crispy smashed potatoes",
  "caption": "Crispy smashed potatoes 🥔 boil, smash, roast at 220°C #recipe",
  "category": { "slug": "food", "label": "Food" },
  "status": "done",
  "kind": "reel",
  "permalink": "https://www.instagram.com/reel/SyntheticCode1/",
  "confidence": 0.93,
  "relevant": true,
  "informativeness": 3,
  "decided_at_stage": 1,
  "review_reason": null,
  "error": null,
  "created_at": "2026-11-01T09:58:41Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string \| null | null → UI shows "Untitled". Untrusted text |
| `caption` | string \| null | untrusted text |
| `category` | `{slug,label}` \| null | null until decided (or `no_evidence`) |
| `status` | `received` \| `analyzing` \| `done` \| `needs_review` \| `failed` | |
| `kind` | `post` \| `carousel` \| `reel` \| null | null until parsed |
| `permalink` | string \| null | "Open on Instagram ↗" hidden when null or not matching `PERMALINK_RE` |
| `confidence`, `relevant`, `informativeness`, `decided_at_stage` | as in schema.md, or null | |
| `review_reason` | `below_threshold` \| `cross_check_mismatch` \| `no_evidence` \| null | `evidence.review_reason` when `status = needs_review`, otherwise always `null` |
| `error` | string \| null | a code from [schema.md §3.1](schema.md#31-postserror-codes) (`failed`, or a receiver `media_copy_*` code) |

For `received` / `analyzing` / `failed` rows, the result fields may hold a previous run's values (schema.md §3,
"—" in the per-status table); the UI shows them dimmed or not at all, never as the current result.
`permalink` is rendered as a link only when it matches `PERMALINK_RE` (interfaces.md §1) — in practice it
starts with `https://www.instagram.com/` — with `rel="noopener noreferrer"`; otherwise the link is hidden.

## 2. Endpoints

### `POST /api/login`
Body: `{ "password": "…" }` (compared in constant time with `APP_PASSWORD`, §1.2).

| Result | Response |
|---|---|
| rate limit active (checked first) | `429 rate_limited` — even for the correct password |
| correct | `204`, `Set-Cookie: insta_saver_session=…` |
| wrong | `401 invalid_password` |
| `AUTH_ENABLED=false` | `204` (no cookie needed) |

### `GET /api/categories`
Sidebar data. All counts are over **all statuses**, and match what `GET /api/posts` returns for the same filter.

```json
{
  "categories": [
    { "slug": "food",   "label": "Food",   "count": 12 },
    { "slug": "travel", "label": "Travel", "count": 7 }
  ],
  "total": 23,
  "by_status": { "received": 2, "analyzing": 0, "done": 17, "needs_review": 3, "failed": 1 }
}
```

`categories` ordered by `label`. Sidebar mapping: All = `total`, Food/Travel = `categories[].count`,
Needs review = `by_status.needs_review`.

### `GET /api/posts?category=&status=&q=&cursor=&limit=`
List and search, newest first unless searching.

| Param | Type | Default | Notes |
|---|---|---|---|
| `category` | slug | — | unknown slug → `422 validation_error` |
| `status` | one of the 5 statuses | — | added beyond PLAN §7 so the sidebar's "Needs review" (`status=needs_review`) and failed posts can be listed |
| `q` | string | — | trimmed; empty = no search; > 200 chars → `422`. Matches full-text (`search_tsv @@ websearch_to_tsquery('simple', q)`) **or** typo-tolerant title similarity (`pg_trgm`) |
| `cursor` | opaque string | — | from a previous `next_cursor`; invalid → `400 bad_request` |
| `limit` | int 1–100 | 30 | |

Filters combine with AND. Order: without `q` → `created_at desc, id desc`; with `q` → relevance desc, then
`created_at desc`. The cursor encoding is the server's choice (keyset or offset) and clients never parse it.

```json
{
  "items": [ { "...": "Post object" } ],
  "next_cursor": "eyJvIjozMH0"
}
```
`next_cursor` is `null` on the last page.

### `GET /api/queue`
Polled by the badge ("N waiting to process") and while "Process now" runs.

```json
{ "received": 3, "analyzing": 1, "running": true }
```
`running` = a worker run started by this server process is in progress (a CLI run elsewhere shows up only
through `analyzing`).

### `POST /api/process`
Starts `process.run_worker()` (interfaces.md §8) as a background task in the server process. No body.

| Result | Response |
|---|---|
| started | `202` `{ "running": true }` |
| a run started by this server is still going | `409 already_running` |

Progress = poll `GET /api/queue` until `running` is false. A run that crashes is logged; the next
`GET /api/queue` shows `running: false`.

### `PATCH /api/posts/{id}`
Change category (the only editable field in v0). Body: `{ "category": "travel" }`.

- Allowed when status is `done` or `needs_review`; else `409 invalid_state`.
- Sets `category_id`, sets `status = 'done'`; in `evidence` sets `needs_review = false`,
  `review_reason = null`, and **sets** (overwrites) `manual_override = {category, previous_category,
  previous_review_reason, at}` (interfaces.md §6). Other result fields are left unchanged (so
  `decided_at_stage` etc. stay `null` on a former `no_evidence` post — schema.md §3). The write is
  conditional on the status (schema.md §3); a status change in between → `409`. No DM is sent.
- `200` + the updated Post object. Unknown slug → `422`; unknown id → `404`.

### `POST /api/posts/{id}/retry`
Re-run the cascade. No body.

- Allowed when status is `done`, `needs_review` or `failed`; `received` / `analyzing` → `409 invalid_state`.
- Resets the row to `received` (conditional write, schema.md §3), then makes sure this server processes it:
  if no run is active it starts one as `POST /api/process` does; if a run is active it sets a server-side
  `rerun_requested` flag. The background task checks the flag after `run_worker()` returns and, if it is
  set, clears it and calls `run_worker()` again — so the retried post is always processed without another
  click, even if the active run had already stopped claiming. An active run is **not** an error here.
- `running` and `rerun_requested` are **in-process** state of this server (app state), never persisted — no
  DB column. Each read-and-update of them is one synchronous step with no `await` in between: the retry
  handler's "if `running` then set `rerun_requested`, else set `running` and start the task", and the
  background task's final "if `rerun_requested` then clear it and loop, else set `running = false`". So a
  retry cannot fall into a gap between the last check and `running = false`. If `run_worker()` raises, the
  task logs it and then does the same final step (a set flag still causes exactly one more run).
  "No `await` in between" is atomic only on the event-loop thread. So the `retry` and `process` handlers are
  `async def`, and both read-and-update steps run on the event loop (`run_worker()` itself may run in a
  threadpool; the final step runs after it returns, back on the loop). If either step ever has to run in
  another thread (a sync `def` handler, or the final step inside the threadpool), both steps take one
  shared `threading.Lock` instead. Tests: (1) the retry and process handlers **and** the background task
  callable are coroutine functions (`inspect.iscoroutinefunction`); (2) with a fake `run_worker()` run in
  the threadpool that blocks on an event, the task's final step records `threading.get_ident()` equal to the
  event-loop thread's id; (3) a retry while the fake is blocked sets `rerun_requested`; releasing it gives
  exactly one more run and then `running = false`; (4) the fake raising still runs the final step (one more
  run if the flag was set, else `running = false`).
- `202` + the updated Post object (`status: "received"`).
- Media of `done`/`needs_review` posts is already deleted (or being deleted — an empty prefix counts as no
  media, storage.md §4), so their retry reuses stored vision evidence (interfaces.md §6); `failed` posts keep
  their media and re-run vision.
- Tests: a retry while a run is active (and past its last claim) leads to a second `run_worker()` call; the
  same when the first `run_worker()` raises; with no retry during the run, `run_worker()` is called once and
  `GET /api/queue` then shows `running: false`.

### `DELETE /api/posts/{id}`
- Deletes Storage objects under `{id}/`, then the row (storage.md §4). Allowed in any status (a worker that
  had it claimed drops its result).
- `204`. Unknown id → `404`. Storage failure → `502 storage_error`, row kept.

## 3. Static files
Every non-`/api` `GET` serves the built SPA (`frontend/dist`), with `index.html` as fallback for client-side
routes. Static files need no session; their data comes from `/api`. The `Host` check and the security
headers (§1.1, §1.2) apply to them too.

## 4. Open questions
- **Logout:** PLAN §7 has no logout endpoint; the session expires server-side after 30 days, and rotating
  `SESSION_SECRET` revokes all sessions (§1.2). Add `POST /api/logout` (clears the cookie) if wanted —
  small, additive contract change.
- **Edit title:** not in PLAN §7 actions; not supported in v0.
