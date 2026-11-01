# Local API contract — v0

- Version: v0 (M0.1) · 2026-11-01 · owner: `architect`
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
this order, before auth and before any handler:

1. **Bind.** `serve.py` binds `API_HOST` (default and only supported v0 value `127.0.0.1`) on `API_PORT`
   (default `8000`). It refuses to start (non-zero exit, clear message) for any other `API_HOST` — in
   particular `0.0.0.0`, `::` or a LAN address. A future hosted mode (PLAN §8 "UI from
   your phone") is a contract change with an ADR; even then, a non-loopback bind with `AUTH_ENABLED=false`
   refuses to start.
2. **Host allowlist** (DNS-rebinding defence), every request incl. static files: `Host` must equal
   `127.0.0.1:<API_PORT>` or `localhost:<API_PORT>` (plus the dev origin's host, below). Anything else,
   or a missing `Host` → `421 invalid_host`.
3. **Origin allowlist**, every `/api/*` request: if `Origin` is present it must equal
   `http://127.0.0.1:<API_PORT>` or `http://localhost:<API_PORT>` (plus the dev origin); anything else,
   including `Origin: null` → `403 forbidden_origin`. A request without `Origin` (curl, tests) passes this
   check.
4. **CSRF header**, every non-`GET`/`HEAD` `/api/*` request — `POST /api/login`, `PATCH`, and **the bodyless
   ones** (`POST /api/process`, `POST /api/posts/{id}/retry`, `DELETE`): it must carry
   `X-Requested-With: insta-saver`, else `403 missing_csrf_header`. A custom header makes every cross-site
   request a CORS preflight, which fails (rule 5). Requests with a body additionally need
   `Content-Type: application/json`, else `415`.
5. **No CORS.** No CORS middleware, no `Access-Control-*` header on any response, `OPTIONS` → `405`.
   Same-origin only.

Dev server: when `API_DEV_ORIGIN` is set (e.g. `http://localhost:5173`, the Vite dev server that proxies
`/api`), that origin and its `host:port` are added to the two allowlists. It must be an `http` origin on a
loopback host, else `serve.py` refuses to start. Unset by default.

### 1.2 Auth and session

- `AUTH_ENABLED` (default **true**; only the exact value `false` disables it — anything else, including
  unset or a typo, means true). When true, every `/api/*` route except `POST /api/login` requires a valid
  session cookie, else `401 unauthorized`. `AUTH_ENABLED=false` is allowed only with a loopback bind (§1.1).
- **Fail closed at startup** when auth is enabled: `serve.py` refuses to start if `APP_PASSWORD` is empty or
  shorter than 12 characters, or if `SESSION_SECRET` is shorter than 32 bytes (generate with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
- **Session cookie** `session`: an itsdangerous `URLSafeTimedSerializer` token carrying its issued-at time,
  `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age=2592000`, `Secure` when served over HTTPS (never in v0).
  The **server** enforces the 30 days: it verifies with `loads(token, max_age=2592000)`, so an old cookie is
  rejected even if a client keeps it. The signing key is derived from `SESSION_SECRET` **and** a SHA-256 of
  `APP_PASSWORD`, so changing either one invalidates every session. Stateless; no server-side session table.
- **Kill switch / logout:** rotating `SESSION_SECRET` (and restarting the server) revokes every session.
- **Login** compares `hmac.compare_digest(given.encode("utf-8"), APP_PASSWORD.encode("utf-8"))` — non-ASCII
  input is a normal wrong password (`401`), never a `500`.
- **Rate limit** is checked **before** the password compare: more than 5 failed logins within 5 minutes →
  every login attempt, even with the correct password, gets `429 rate_limited` until the window passes.
  The client key is the socket peer address (`request.client.host`), never `X-Forwarded-For` or any other
  header. With a loopback bind this is effectively one global limit — intended.
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
| Bind | settings validation refuses `API_HOST` = `0.0.0.0`, `::`, `192.168.1.10`; accepts `127.0.0.1`. `API_DEV_ORIGIN` = `http://192.168.1.10:5173` or `https://localhost:5173` refused |
| Fail closed | auth on + `APP_PASSWORD` empty / 11 chars → refuses; `SESSION_SECRET` 31 bytes → refuses; `AUTH_ENABLED` unset, `"False"`, `"0"`, `"no"` → auth on |
| Host | `Host: evil.example:8000`, `Host: 127.0.0.1:9999`, missing Host → `421` on `GET /api/posts` and `GET /`; both allowed hosts pass |
| Origin | `Origin: http://evil.example`, `http://localhost:5173` (dev origin unset), `null` → `403` on a GET and on every non-GET endpoint; allowed origins and no Origin pass |
| CSRF header | each of `POST /api/login`, `POST /api/process`, `POST /api/posts/{id}/retry`, `PATCH`, `DELETE` without the header → `403 missing_csrf_header`; wrong value → `403` |
| Content-Type | `PATCH` / `POST /api/login` with `text/plain` body → `415` |
| No CORS | no response (incl. `OPTIONS` with `Origin` + `Access-Control-Request-Method`, which gets `405`) has any `Access-Control-*` header |
| Session | tampered cookie → `401`; cookie issued 30 days + 1 s ago (frozen clock) → `401`; cookie signed with a previous `SESSION_SECRET` → `401`; cookie issued before an `APP_PASSWORD` change → `401` |
| Login | correct → `204` + cookie with the attributes above; wrong → `401`; non-ASCII password → `401`; 6th attempt after 5 failures with the **correct** password → `429` + `Retry-After`; varying `X-Forwarded-For` does not reset the limit |
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
| correct | `204`, `Set-Cookie: session=…` |
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
- `202` + the updated Post object (`status: "received"`).
- Media of `done`/`needs_review` posts is already deleted (or being deleted — an empty prefix counts as no
  media, storage.md §4), so their retry reuses stored vision evidence (interfaces.md §6); `failed` posts keep
  their media and re-run vision.
- Test: a retry while a run is active (and past its last claim) leads to a second `run_worker()` call.

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
