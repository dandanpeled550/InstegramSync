# Local API contract — v0

- Version: v0 (M0.1) · 2026-11-01 · owner: `architect`
- Implemented by `web-engineer` (FastAPI, `backend/app/api/**`, served by `python -m app.serve` on
  `http://localhost:8000`); consumed by the Vite/React SPA served from the same origin.
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
| 404 | `not_found` | unknown post id |
| 409 | `invalid_state` | action not allowed in the post's current status |
| 409 | `already_running` | a worker run is already in progress |
| 415 | `unsupported_media_type` | mutating request without `Content-Type: application/json` (when it has a body) |
| 422 | `validation_error` | well-formed request with invalid values (unknown category, `q` too long, ...) |
| 429 | `rate_limited` | too many failed logins |
| 502 | `storage_error` | Supabase Storage call failed |
| 503 | `database_unavailable` | Postgres unreachable |
| 500 | `internal` | anything else (no stack traces or secrets in `message`) |

### Auth
- `AUTH_ENABLED` (default **true**). When true, every `/api/*` route except `POST /api/login` requires a
  valid session cookie, else `401 unauthorized`. `AUTH_ENABLED=false` is allowed for localhost only and is
  never the default.
- Session cookie `session`: value signed with `SESSION_SECRET` (e.g. itsdangerous), `HttpOnly`,
  `SameSite=Strict`, `Path=/`, `Max-Age=2592000` (30 days), `Secure` when served over HTTPS. Stateless; no
  server-side session table.
- CSRF: `SameSite=Strict` plus the JSON content-type requirement on mutating requests that carry a body.
- The SPA treats any `401 unauthorized` as "show the login screen".

### Post object

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
| `permalink` | string \| null | "Open on Instagram ↗" hidden when null |
| `confidence`, `relevant`, `informativeness`, `decided_at_stage` | as in schema.md, or null | |
| `review_reason` | `below_threshold` \| `cross_check_mismatch` \| `no_evidence` \| null | from `evidence.review_reason` |
| `error` | string \| null | short error for `failed` (or a receiver `media_copy_*` code) |

## 2. Endpoints

### `POST /api/login`
Body: `{ "password": "…" }` (compared in constant time with `APP_PASSWORD`).

| Result | Response |
|---|---|
| correct | `204`, `Set-Cookie: session=…` |
| wrong | `401 invalid_password` |
| > 5 failures in 5 min from one client | `429 rate_limited` |
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
- Sets `category_id`, sets `status = 'done'` (clears needs-review), writes `evidence.manual_override =
  {category, previous_category, at}`. Other result fields are left unchanged. No DM is sent.
- `200` + the updated Post object. Unknown slug → `422`; unknown id → `404`.

### `POST /api/posts/{id}/retry`
Re-run the cascade. No body.

- Allowed when status is `done`, `needs_review` or `failed`; `received` / `analyzing` → `409 invalid_state`.
- Resets the row to `received` (schema.md §3), then starts a worker run as `POST /api/process` does; if a run
  is already going, that run picks the post up — this is **not** an error.
- `202` + the updated Post object (`status: "received"`).
- Media of `done`/`needs_review` posts is already deleted, so their retry reuses stored vision evidence
  (interfaces.md §6); `failed` posts keep their media and re-run vision.

### `DELETE /api/posts/{id}`
- Deletes Storage objects under `{id}/`, then the row (storage.md §4). Allowed in any status (a worker that
  had it claimed drops its result).
- `204`. Unknown id → `404`. Storage failure → `502 storage_error`, row kept.

## 3. Static files
Every non-`/api` `GET` serves the built SPA (`frontend/dist`), with `index.html` as fallback for client-side
routes. Static files need no session; their data comes from `/api`.

## 4. Open questions
- **Logout:** PLAN §7 has no logout endpoint; the cookie simply expires after 30 days. Add
  `POST /api/logout` (clears the cookie) if wanted — small, additive contract change.
- **Edit title:** not in PLAN §7 actions; not supported in v0.
