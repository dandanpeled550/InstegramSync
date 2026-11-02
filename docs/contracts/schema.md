# Schema contract — v0

- Version: v0.1 (M0.1b) · 2026-11-01 · owner: `architect` — v0.1 adds the migration role guard, the owner and
  extension checks, the receiver media write and the exact PATCH statement (follow-ups from the PR #4 reviews);
  the read-only remote catalog check, CLI pin and connection rules from the migration-role research (PR #13
  round 2) · round 3: read-only login attributes, `seed.sql` scan matching, CLI `version:` input vs action
  SHA, placeholder `sqlstate` may be `unknown`
- Mirrors: `supabase/migrations/` (implemented by `data-engineer` in M0.5). Where this file and a migration
  disagree, the migration is a bug or this file needs an ADR — never silently "fix" one to match the other.
- Source: [PLAN.md §6](../PLAN.md#6-store--supabase), [ADR 0001](../decisions/0001-supabase-receiver-laptop-worker.md).

## 1. Extensions

| Extension | Schema | Why |
|---|---|---|
| `pg_trgm` | `extensions` | Typo-tolerant title search (`posts_title_trgm`) |

`gen_random_uuid()` is built into Postgres 13+; no `pgcrypto` needed. On Supabase, create extensions
`with schema extensions` and reference the operator class as `extensions.gin_trgm_ops` if the migration's
`search_path` does not include `extensions`. (`pg_cron` / `pg_net` arrive in M2 with their own migration.)

**No extension lives in `public`.** Every extension is created as
`create extension if not exists <name> with schema extensions;` — or, when the extension's control file
fixes its schema (e.g. M2's `pg_cron`, `pg_net`), with exactly that schema. A bare `create extension` is
never used: where it lands depends on `search_path` ([research](../research/supabase-migration-role.md)). An extension in `public` would put RPC-callable functions on the PostgREST
surface. `tests/db` asserts this (§5).

## 2. Tables

All tables live in schema `public`. Constraint names are part of the contract (later migrations drop/replace
them by name — see §6).

### 2.1 `categories`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | `serial` | no | sequence | primary key |
| `slug` | `text` | no | — | `unique`; machine name used in API/JSON (`food`, `travel`) |
| `label` | `text` | no | — | human label (`Food`, `Travel`) |

Constraints:
- `categories_slug_key` — `unique (slug)`
- `categories_slug_format` — `check (slug ~ '^[a-z][a-z0-9_]*$')`

**Reference rows (inserted by the migration itself, not `seed.sql`)** — production needs them and
`supabase db push` does not run `seed.sql`:

| slug | label |
|---|---|
| `food` | `Food` |
| `travel` | `Travel` |

Insert with `on conflict (slug) do nothing`. Code must look categories up by `slug`, never assume `id` values.

### 2.2 `posts`

One row per shared Instagram message. The table is also the work queue (see §3).

| Column | Type | Null | Default | Written by | Notes |
|---|---|---|---|---|---|
| `id` | `uuid` | no | `gen_random_uuid()` | DB | primary key; also the Storage folder name |
| `message_mid` | `text` | no | — | receiver | Meta message id; `unique` → dedupes double deliveries |
| `sender_id` | `text` | no | — | receiver | Instagram-scoped id of the sender (already allow-listed) |
| `ig_media_id` | `text` | yes | — | worker | from `raw_payload` via `parser.py` |
| `kind` | `text` | yes | — | worker | `post` \| `carousel` \| `reel` |
| `permalink` | `text` | yes | — | worker | Instagram link; only a value matching `PERMALINK_RE` ([interfaces.md §1](interfaces.md#1-posts--dbmodelspy-ingestparserpy)) is stored, else `null` (derivation verified in M1) |
| `caption` | `text` | yes | — | worker | raw caption as found in the payload |
| `media_path` | `text` | yes | — | receiver, worker | Storage folder prefix `"{id}/"` in bucket `media`; `null` = no media stored (never stored, or deleted after processing). See [storage.md](storage.md) |
| `title` | `text` | yes | — | worker | ≤ 60 characters; `null` = UI shows "Untitled" |
| `search_text` | `text` | yes | — | worker | caption + every stage's description/transcript/on-screen text |
| `category_id` | `int` | yes | — | worker, API | FK → `categories(id)` (no cascade) |
| `confidence` | `real` | yes | — | worker | category confidence of the deciding stage, 0–1 |
| `relevant` | `boolean` | yes | — | worker | deciding stage: is the text about this post |
| `informativeness` | `smallint` | yes | — | worker | deciding stage, rubric score 0–3 |
| `decided_at_stage` | `smallint` | yes | — | worker | last cascade stage that ran: 1 \| 2 \| 3 |
| `evidence` | `jsonb` | yes | — | worker, API | accumulated evidence, shape in [interfaces.md §6](interfaces.md#evidence-json-postsevidence) |
| `status` | `text` | no | `'received'` | all | state machine, §3 |
| `current_stage` | `smallint` | yes | — | worker | stage in progress while `analyzing` (0–3) |
| `claimed_at` | `timestamptz` | yes | — | worker | set on claim; used for stuck-row recovery |
| `error` | `text` | yes | — | receiver, worker | exactly one of the §3.1 forms — never raw exception text, secrets, tokens, URLs or post content; ≤ 500 chars |
| `raw_payload` | `jsonb` | no | — | receiver | the webhook `messaging` event exactly as received (shape: `payloads.md`, M1), **or** the receiver's placeholder `{"insta_saver_placeholder": "insert_rejected", "sqlstate": "<SQLSTATE or unknown>"}` when Postgres (or PostgREST, `PGRST102`) rejected the event permanently ([receiver.md §6](receiver.md#6-insert-and-dedupe)) |
| `created_at` | `timestamptz` | no | `now()` | DB | time the receiver stored the row |
| `search_tsv` | `tsvector` | — | generated | DB | `generated always as (to_tsvector('simple', coalesce(title,'') \|\| ' ' \|\| coalesce(search_text,''))) stored` |

Constraints (named):

| Name | Definition |
|---|---|
| `posts_pkey` | `primary key (id)` |
| `posts_message_mid_key` | `unique (message_mid)` |
| `posts_category_id_fkey` | `foreign key (category_id) references categories(id)` |
| `posts_status_check` | `check (status in ('received','analyzing','done','needs_review','failed'))` |
| `posts_kind_check` | `check (kind is null or kind in ('post','carousel','reel'))` |
| `posts_decided_at_stage_check` | `check (decided_at_stage is null or decided_at_stage between 1 and 3)` |
| `posts_current_stage_check` | `check (current_stage is null or current_stage between 0 and 3)` |
| `posts_informativeness_check` | `check (informativeness is null or informativeness between 0 and 3)` |
| `posts_confidence_check` | `check (confidence is null or (confidence >= 0 and confidence <= 1))` |
| `posts_title_length_check` | `check (title is null or char_length(title) <= 60)` |

Why `text` + `check` instead of Postgres enums: adding a status/kind later is a constraint swap in one
migration (expand-friendly), whereas enum values can't be removed. Recorded in ADR 0001.

### 2.3 `app_secrets`

Server-side secrets that Edge Functions must read **and rotate** at run time (so they can't live in
`supabase secrets`). Readable only with the service role.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `key` | `text` | no | — | primary key |
| `value` | `text` | no | — | the secret; never logged, never returned by any API |
| `expires_at` | `timestamptz` | yes | — | `null` = no known expiry |

Known keys (v0):

| key | Written by | Read by |
|---|---|---|
| `ig_access_token` | human (initial, one-time SQL in the dashboard — human gate), `refresh-token` function (rotation) | `ig-webhook` (ack DM), worker `meta/client.py` ("Saved" DM), `refresh-token` |

The migration creates the table **empty**. `seed.sql` may insert a synthetic value
(`'local-dev-not-a-token'`) for local development only. After the human enters the real token in the
dashboard SQL editor, they delete that query from the editor's history/snippets.

Forward reference (M2 entry condition, not v0): pg_cron's call to `refresh-token` reads its credential from
Supabase Vault at run time and the function checks a dedicated `CRON_SECRET`; no key or token ever appears
in migration SQL. Moving `app_secrets` out of the PostgREST-exposed `public` schema (or into Vault) is
considered in the same M2 contract update.

## 3. `posts.status` state machine

```
             receiver INSERT
                   │
                   ▼
   ┌──────────► received ◄──────────────────────────────┐
   │               │ worker claim                       │ API retry
   │ worker        ▼                                    │ (from done | needs_review | failed)
   │ recover   analyzing ──► done ◄──── API PATCH ──┐   │
   │ (stuck     │    │                              │   │
   │  > 30 min) │    └──► needs_review ─────────────┘   │
   └────────────┘    └──► failed ───────────────────────┘
```

"Result columns" below = `ig_media_id, kind, permalink, caption, title, search_text, category_id, confidence,
relevant, informativeness, decided_at_stage, evidence`.

| From | To | Actor | Exact write |
|---|---|---|---|
| — | `received` | receiver | `insert (message_mid, sender_id, raw_payload) … on conflict (message_mid) do nothing returning id` — with the event, or with the placeholder `raw_payload` after a permanent rejection (receiver.md §6) |
| `received` | `received` | receiver media write (M2, [receiver.md §6](receiver.md#6-insert-and-dedupe)) | once per new row, after all attachments were attempted: `media_path` and `error` **in one update** — `('{id}/', null)`, `('{id}/', 'media_copy_partial')` or `(null, 'media_copy_failed')` |
| `received` | `analyzing` | worker claim | `status='analyzing', current_stage=0, claimed_at=now()` — see claim query below (`error` is left as-is so a receiver `media_copy_*` code stays visible until the result is written) |
| `analyzing` | `received` | worker recover | rows with `claimed_at < now() - interval '30 minutes'`: `status='received', current_stage=null, claimed_at=null` |
| `analyzing` | `done` / `needs_review` | worker | result columns + `current_stage=coalesce(decided_at_stage, 0), error=null`; then media cleanup ([storage.md §4](storage.md#4-lifecycle)) |
| `analyzing` | `failed` | worker | `status='failed', error=<code from §3.1>`; `current_stage` left as-is (shows where it failed); media kept |
| `needs_review` / `done` | `done` | API `PATCH /api/posts/{id}` | `category_id=<chosen>, status='done'`; in `evidence`: set `needs_review=false`, `review_reason=null`, and **set** (overwrite, not append) `manual_override` (interfaces.md §6) — exact statement below |
| `done` / `needs_review` / `failed` | `received` | API `POST /api/posts/{id}/retry` | `status='received', current_stage=null, claimed_at=null, error=null` (result columns kept until overwritten) |
| any | (row deleted) | API `DELETE /api/posts/{id}` | delete Storage objects, then `delete from posts where id=$1` |

**Write conditions.** Every write above is conditional, and "zero rows updated" has a defined meaning:

| Write | `where` condition | Zero rows updated means |
|---|---|---|
| receiver media write (M2) | `update posts set media_path=$2, error=$3 where id=$1 and status='received'` | the row was deleted (or, if the timing rule below were ever broken, already claimed) → the receiver leaves the stored objects (orphans, storage.md §4) and does not retry |
| claim | the claim query below | nothing to claim |
| recover | `status='analyzing' and claimed_at < now() - interval '30 minutes'` | nothing stuck |
| result (`done` / `needs_review`) and `failed` | `id=$1 and status='analyzing' and claimed_at=$claimed_at` | the row was recovered, retried or deleted meanwhile → the worker drops its result (logs `id` only), counts it in `RunSummary.dropped`, sends no DM |
| media cleanup — right after the result write **and** the end-of-run sweep (storage.md §4) | `id=$1 and status in ('done','needs_review') and media_path is not null`; sets only `media_path=null`, and only after the objects were deleted | the row was retried, deleted or already cleaned → nothing to do. Objects already deleted are harmless: an empty prefix means "no media" (storage.md §4) |
| API PATCH | `id=$1 and status in ('done','needs_review')` | `404` if the row is gone, else `409 invalid_state` |
| API retry | `id=$1 and status in ('done','needs_review','failed')` | `404` if the row is gone, else `409 invalid_state` |
| API delete | `id=$1` | `404` |

This makes overlapping runs (CLI + "Process now") and API actions during a run safe. M4 adds the "Saved" DM:
it is sent only after a result write updated exactly 1 row (its text for `needs_review` is fixed in the M4
contract update).

**Why the receiver media write can't race the worker.** The claim takes a row whose `media_path` is still
`null` only once `created_at < now() - MEDIA_WAIT_MINUTES`. The receiver's background work runs inside the
Edge Function's wall-clock window, which starts before the insert (so before `created_at`) and ends at most
150 s later on the Free plan (400 s on paid plans — [research](../research/supabase-edge-functions.md)).
With `MEDIA_WAIT_MINUTES = 5` (300 s), the media write always lands before the worker may claim a media-less
row. A row with `media_path` set can be claimed at once, but `media_path` is set only by this single, final
write; the receiver writes nothing to the row after it. Rule: **`MEDIA_WAIT_MINUTES × 60` must exceed the
wall-clock limit of the plan in use.** `config.py` rejects `MEDIA_WAIT_MINUTES < 3` (Free plan); moving to a
paid plan raises the minimum to 7 (contract update). The `status='received'` condition is the second line of
defence: if the timing assumption ever breaks, the write updates zero rows instead of putting an `error` on a
`done` row or overwriting a `failed` code.

**PATCH statement** (`PATCH /api/posts/{id}`). It is one statement, so `previous_category` and
`previous_review_reason` describe exactly the row version that was updated (never read-then-write). `$1` is
the post id, `$2` the chosen slug (already validated by the API, `422` otherwise):

```sql
update posts p
   set category_id = c.id,
       status      = 'done',
       evidence    = p.evidence || jsonb_build_object(
         'needs_review',    false,
         'review_reason',   null,
         'manual_override', jsonb_build_object(
           'category',               c.slug,
           'previous_category',      (select pc.slug from categories pc where pc.id = p.category_id),
           'previous_review_reason', p.evidence -> 'review_reason',
           'at', to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')))
  from categories c
 where p.id = $1 and c.slug = $2 and p.status in ('done', 'needs_review')
returning p.*;
```

`set` expressions see the row as it was before the update. A second PATCH on a `done` row records
`previous_review_reason = null`. That the post was originally `no_evidence` stays visible because
`evidence.stages` is empty (see the invariants below).

**Per-status invariants** (true for every row, whoever wrote it). "—" = unspecified: `null` on a fresh row,
the previous run's values after a retry (kept until overwritten). Readers must not treat "—" values as the
current result — the one deliberate use is the worker reading the previous `evidence` on a retry to reuse
stored vision (interfaces.md §6).

| `status` | `category_id` | `decided_at_stage`, `confidence`, `relevant`, `informativeness` | `evidence` | `evidence.review_reason` | `current_stage` | `claimed_at` | `error` |
|---|---|---|---|---|---|---|---|
| `received` | — | — | — | — | `null` | `null` | `null` or `media_copy_*` |
| `analyzing` | — | — | — | — | 0–3 | not null | `null` or `media_copy_*` |
| `done` | **not null** | all four not null, **or** all four `null` — allowed only if `evidence.stages` is empty **and** `evidence.manual_override` is not null (a former `no_evidence` row the owner categorized) | not null, `needs_review=false` | `null` | 0–3 | last claim | `null` |
| `needs_review` | not null — `null` iff `review_reason='no_evidence'` | all four not null, or all four `null` iff `review_reason='no_evidence'` iff `evidence.stages` is empty | not null, `needs_review=true` | **not null** | 0–3 | last claim | `null` |
| `failed` | — | — | — | — | stage where it failed (0–3) | last claim | **not null**, a §3.1 code |

`no_evidence` = no stage could run (no usable caption and no media, nor stored vision), so `evidence.stages`
is empty. Every invariant can be checked from the row alone. Also:
- No transition skips `analyzing` except the API transitions listed above.
- Nothing ever writes `status='analyzing'` except the claim.

These invariants are enforced in code (repo layer), not by DB constraints, in v0.

### 3.1 `posts.error` codes

`error` holds exactly one of these. Raw exception text, tracebacks, URLs, tokens and post content never go in
`error` (they go to local logs only, and logs never contain secrets). New codes are an additive contract change.

| Code | Written by | When |
|---|---|---|
| `media_copy_partial` | receiver | some attachments could not be stored (storage.md §4) |
| `media_copy_failed` | receiver | no attachment could be stored |
| `unsupported_payload: <reason>` | worker | `parse()` raised `UnsupportedPayload`; `<reason>` is its machine code (`no_attachment`, `unsupported_type`, … — final list in `payloads.md`, M1; `insert_rejected` = the receiver stored a placeholder, receiver.md §6) |
| `media_download_failed` | worker | a listed object could not be downloaded (storage.md §5) |
| `DeciderError: <message>` / `VisionError: <message>` | worker | an adapter raised a `ModelError` subclass; `<message>` is the adapter's own message, which never contains keys, signed URLs, model output or post content (interfaces.md §2) |
| `internal_error: <ExceptionType>` | worker | any other per-post exception — only the class name, e.g. `internal_error: KeyError` |

**Claim query** (`backend/app/db/repo.py`, M3):

```sql
update posts
   set status = 'analyzing', current_stage = 0, claimed_at = now()
 where id in (
   select id from posts
    where status = 'received'
      and (media_path is not null or created_at < now() - interval '5 minutes')
    order by created_at
    for update skip locked
    limit 5)
returning *;
```

The `media_path is not null or created_at < now() - 5 min` condition gives the receiver's background media
copy time to finish before a fast "Process now" claims the row. After 5 minutes a row with no media is
processed caption-only (download failed, or nothing to download). The 5 minutes and batch size 5 are
`config.py` settings (`MEDIA_WAIT_MINUTES`, `CLAIM_BATCH_SIZE`), the 30 minutes is `STUCK_AFTER_MINUTES`.
`MEDIA_WAIT_MINUTES` must exceed the Edge Function wall-clock limit (see "Why the receiver media write can't
race the worker" above). Keep `CLAIM_BATCH_SIZE × worst-case time per post` (a Stage 3 reel: a few minutes) well under
`STUCK_AFTER_MINUTES`; otherwise a second run recovers rows the first run has claimed but not reached yet.
The conditional writes keep that correct, but it pays for the model calls twice.

## 4. Indexes

| Name | Definition | Serves |
|---|---|---|
| (implicit) `posts_pkey` | `btree (id)` | lookups by id |
| (implicit) `posts_message_mid_key` | `btree (message_mid)` unique | receiver dedupe |
| `posts_search_idx` | `gin (search_tsv)` | full-text search (`GET /api/posts?q=`) |
| `posts_title_trgm` | `gin (title extensions.gin_trgm_ops)` | typo-tolerant title search |
| `posts_category_idx` | `btree (category_id, created_at desc)` | category list, newest first |
| `posts_status_idx` | `btree (status, created_at)` | claim, queue counts, needs-review list |
| (implicit) `categories_slug_key` | `btree (slug)` unique | slug lookup |

No other indexes in v0. M5 (search) may add more through a new migration and an update here.

## 5. Row-level security and grants

**Every table has RLS enabled. No table has a policy in v0.** Only the service role (which bypasses RLS) and
direct DB connections as the `postgres` owner (the laptop's `DATABASE_URL`) can read or write. Nothing in this
system talks to Postgres as `anon` or `authenticated` — the browser only talks to the local FastAPI.

| Table | RLS | Policies | `anon` | `authenticated` | `service_role` / owner |
|---|---|---|---|---|---|
| `categories` | enabled | **none** | no access | no access | full |
| `posts` | enabled | **none** | no access | no access | full |
| `app_secrets` | enabled | **none** | no access | no access | full |

Defense in depth — Supabase's default privileges grant table, sequence and function rights to
`anon`/`authenticated` on every new object in `public`, and Postgres grants `EXECUTE` on new functions to
`PUBLIC`. These revokes cover only objects **owned by `postgres`**, so every migration first checks that it
runs as `postgres` (§6, migration role guard). The initial migration then runs:

```sql
-- existing objects
revoke all on table categories, posts, app_secrets from anon, authenticated;
revoke all on sequence categories_id_seq from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

-- future objects created by the migration role (postgres)
alter default privileges for role postgres in schema public revoke all on tables    from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated;
alter default privileges for role postgres revoke execute on functions from public;  -- global: a per-schema
                                                                                      -- entry can't remove it
```

Every `alter default privileges` in any migration names `for role postgres` explicitly, never relying on the
current role. Defaults are per creating role: these do not cover objects that Supabase's own `supabase_admin`
creates (mainly extensions installed in `public`), which is one more reason no extension lives there
([research](../research/supabase-migration-role.md)).

The last statement is **global**. It removes the `PUBLIC` `EXECUTE` default from every function `postgres`
creates later, in any schema, not only `public`. A later migration whose function must be callable by some
role (e.g. M2's pg_cron / pg_net helpers) grants `EXECUTE` explicitly to exactly that role, and never to
`anon`, `authenticated` or `PUBLIC` in `public`.

Rules for every later migration (also in §6):
- A new table gets `enable row level security` and `revoke all … from anon, authenticated` **in the same
  migration** that creates it; a new sequence or function gets the matching revoke (`revoke execute … from
  public, anon, authenticated` for functions).
- A view is created `with (security_invoker = true)` (otherwise it bypasses RLS) and revoked like a table.
  Materialized views and `security definer` functions in `public` need an ADR.
- Optional hardening (devops-engineer, `supabase/config.toml`): `[auth] enable_signup = false`, so nobody can
  mint an `authenticated` JWT.

**What `tests/db/` (M0.5) must assert.** Assertions are **catalog-wide** — they enumerate `public` at test time
instead of a fixed list, so an object added later without RLS or revokes fails the existing tests. Roles =
`anon` and `authenticated`.
- For every relation in `public` with `relkind in ('r','p','v','m','f')` (tables, partitioned tables, views,
  materialized views, foreign tables): `has_table_privilege(role, oid, p)` is false for each `p` in `SELECT,
  INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER`.
- For every table in `public` (`relkind in ('r','p')`): `pg_class.relrowsecurity = true`.
- For every view in `public`: `reloptions` contains `security_invoker=true`.
- For every sequence in `public`: `has_sequence_privilege(role, oid, 'USAGE,SELECT,UPDATE')` is false; and
  `select nextval('categories_id_seq')` as each role raises SQLSTATE `42501`.
- For every function in `public`, with no exclusions: `has_function_privilege(role, oid, 'EXECUTE')` is
  false.
- No extension in `public`: `select count(*) from pg_extension where extnamespace = 'public'::regnamespace`
  = 0. This replaces any "skip extension members" exclusion: an extension created without
  `with schema extensions` fails here instead of being skipped. If a Supabase-installed extension ever shows
  up in `public`, report it; never exclude it silently.
- Every relation and function in `public` is owned by `postgres` (`pg_class.relowner` / `pg_proc.proowner`
  = `'postgres'::regrole`), so the default-privilege revokes above apply to it.
- Every file in `supabase/migrations/` starts with the migration role guard (§6), checked by a file scan:
  skipping only SQL comments and blank lines, the first statement is a `do` block containing the token
  `current_user <> 'postgres'` (match the token, not the message).
- `supabase/seed.sql` creates no objects (§6), checked by a file scan. First remove `--` line comments,
  `/* … */` block comments and single-quoted string literals (with `''` escapes). Then: (a) the text has no
  dollar quote (`$$` or `$tag$`); (b) every statement (split on `;`) starts with `insert into`; (c) none of
  the keywords `create`, `alter`, `drop`, `grant`, `revoke`, `truncate`, `execute`, `copy`, `set role`,
  `reset role` appears (a `do` block is already excluded by (a) and (b)). Keywords match
  **case-insensitively on word boundaries** (`\bcreate\b`), so `created_at` or a literal `'created by seed'`
  never trip it, while `on conflict do nothing` is allowed. Scan tests: `CREATE TABLE x()` → flagged; `-- never create objects here` → passes;
  `insert … values ('drop me')` → passes; `do $$ begin execute 'create table t()'; end $$;` → flagged.
- **Future objects:** inside a rolled-back transaction, as `postgres`, create a throwaway table, sequence,
  function and view in `public`; each role has no privilege on any of them (proves the default privileges).
  And no `pg_default_acl` entry of `defaclrole = 'postgres'` (global or for `public`) grants anything to
  either role via `aclexplode(defaclacl)`, nor `EXECUTE` to `PUBLIC` (grantee `0`). (Entries owned by
  Supabase's own roles are out of scope; the throwaway-object check covers what our migrations create.)
- For each of `categories`, `posts`, `app_secrets` and each role (`set local role …` in a transaction):
  `select`, `insert`, `update`, `delete` each fail with SQLSTATE `42501` (`insufficient_privilege`).
- No policies in `public`: `select count(*) from pg_policies where schemaname = 'public'` = 0.
- The two `categories` reference rows exist after migration; `categories_slug_format` rejects a bad slug
  (e.g. `'Food'`).
- As the owner/service role: an insert into `posts` with only `message_mid`, `sender_id`, `raw_payload` succeeds
  with `status='received'`, a duplicate `message_mid` with `on conflict do nothing` inserts nothing, and each
  named `check` constraint in §2.2 rejects one out-of-range value.

**Remote check after every deploy.** Locally these tests run against `supabase db reset`. Against a remote
database a separate, smaller check runs after every CI `db push` to **staging** (required; any finding fails
the deploy) and, optionally, to **production** after its deploy (tech-lead decides whether M0.6 includes it).
Rules for that check:
- It is **read-only SQL in devops-owned code** (e.g. `scripts/check-remote-privileges.sql`, run by the deploy
  workflow), owned and reviewed by devops-engineer. It is **never** `tests/db` or a pytest marker on it, so
  editing data-engineer's local suite can never change the deploy gate.
- It contains only `select`s over the catalog that mirror these assertions from the list above: table /
  view privileges, `relrowsecurity`, view `security_invoker`, sequence privileges, function `EXECUTE`, no
  extension in `public`, owners, `pg_default_acl` entries of `postgres`, no policies. **No DDL or DML probe**
  against a remote database: not the throwaway-object check, not the per-role CRUD tests, not
  `nextval`. The query result is a list of findings; empty = pass.
- It connects with a **read-only login**, held in an environment-scoped GitHub secret, not the `postgres`
  password. That role is `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 2`, with `alter role … set default_transaction_read_only = on`, **no role memberships**
  (never `pg_read_all_data`, `pg_monitor` or any Supabase role) and no table, sequence or function rights.
  Its only grant is `CONNECT` on the database: the queries join `pg_class` / `pg_namespace` / `pg_proc` by
  OID (no `'public.x'::regclass` name lookups), so no schema `USAGE` is needed. `has_*_privilege()`,
  `pg_class`, `pg_proc`, `pg_extension`, `pg_policies` and `pg_default_acl` are readable by any role.
  Creating that role is a human step in the dashboard (devops documents it); until it exists, devops may use
  the deploy credential, flagged as an open issue.
- The check always runs inside `begin transaction read only`, whatever the credential. With the read-only
  login its first query also asserts the login itself: `current_setting('default_transaction_read_only') =
  'on'` and no `pg_auth_members` row with it as `member`; otherwise the check fails. With the interim deploy
  credential that assertion is skipped and the run output says so.

It closes the gap where the remote migration role differs, gets Supabase's default grants, and the local
tests still pass. It is also the backstop for CLI role drift inside a migration file (§6).

Adding a policy to any table later is a contract change (ADR + update to this table + a test for exactly
that policy). Storage RLS is specified in [storage.md §3](storage.md#3-access).

## 6. Migration rules (expand → migrate → contract)

The deployed receiver (Edge Function) and the laptop worker can run different versions for a while, and
staging/production are migrated by CI only ([AGENTS_PLAN §15.6](../AGENTS_PLAN.md#156-environments)). So
**every migration must be backward-compatible with the code currently deployed**:

1. **Expand** — add things the old code ignores: new nullable columns (or with a default), new tables, new
   indexes, widened `check` constraints (drop the named constraint and re-add the wider one in the same
   migration). Ship this migration first, alone or with code that tolerates both shapes.
2. **Migrate** — deploy code that writes/reads the new shape; backfill data in a separate migration if needed.
3. **Contract** — only in a later release, once no deployed code reads the old shape: drop old columns,
   narrow constraints. Drops and other destructive SQL need an ADR and human approval.

**Migration role guard.** This is the first statement of **every** migration file (only comments and blank
lines may come before it). Canonical text:

```sql
do $$
begin
  if current_user <> 'postgres' then
    raise exception 'migration must run as postgres, got current_user=% (session_user=%)',
      current_user, session_user;
  end if;
end $$;
```

The file scan in `tests/db` (§5) matches the token `current_user <> 'postgres'` inside the first statement,
**not** the exception message, so a later wording change in this contract never breaks applied migrations
(which can't be edited).

Why `current_user` and not `session_user`: new objects are owned by the current role, and default privileges
are keyed on it. Behaviour per [research: migration role](../research/supabase-migration-role.md) (Supabase
CLI v2.122.0 source):
- Local `supabase start` / `db reset` connects as `postgres` (medium confidence).
- Remote `supabase db push` with `SUPABASE_DB_PASSWORD` (the CI deploy path, M0.6) or `--db-url` as
  `postgres` connects as `postgres`; both users are `postgres` (high).
- Remote `db push --linked` without a password logs in as the temporary role `cli_login_postgres` and runs
  `set session role postgres`, so `current_user = 'postgres'` while `session_user = 'cli_login_postgres'`
  (high). The guard passes; `session_user` in the message only helps diagnosis.
- The GitHub integration / branching role is undocumented (low). Staging and production are migrated by CI
  `db push` only; if that ever changes, test the guard on a throwaway branch first.

Do not weaken the guard to `pg_has_role(current_user, 'postgres', 'member')` (it passes for a
`cli_login_postgres` that was never stepped down, which would then own the objects), and never add
`set role postgres` inside a migration to "fix" it (that hides a misconfigured CLI). If the guard fires, the
`db push` fails before the file creates anything (each file runs as one transaction), which is the intended
outcome. Report it. The fix is a contract change; removing the guard is never the fix.

**CLI and connection rules** (devops-engineer, `ci/migrations` and both deploy workflows):
- Pin the **CLI** to exactly **v2.122.0** (the version the research read) through the `version: 2.122.0`
  input of `supabase/setup-cli`, never `latest` and never a range such as "≥ v2.90.0". The action itself is
  pinned by full commit SHA like every action; the two pins are separate. v2.122.0 contains the two fixes
  the step-down depends on: `b08e6e1f` (re-run the step-down on every new connection) and `0c721790`
  (restore `postgres` after `RESET ROLE` / at the end of each file). Raising the pin is a contract change that re-checks both.
- Deploy with `SUPABASE_DB_PASSWORD` (direct host or the CLI's own pooler config, which uses session mode on
  port 5432). Never a hand-built `--db-url` on pooler port **6543** (transaction mode does not keep
  session-level `set session role`).
- Migrations never contain `reset role`, `set role` or `discard all`.

**`seed.sql` creates no objects.** It only inserts synthetic rows into tables the migrations created (e.g.
the `app_secrets` dev value, §2.3). Anything that creates or alters an object goes in a migration, behind the
guard.

Also:
- No extension in `public` (§1). Every new table, view, sequence and function follows the §5 rules (RLS +
  revokes, `security_invoker`) in the migration that creates it.
- Migrations are append-only. An applied migration is never edited; fix forward with a new one.
- No renames in place (add new → migrate → drop old). No `not null` on an existing column without a default
  and a backfill first.
- Each migration changes one concern. Schema changes go **architect-first**: a contract PR updates this file
  (with an ADR when needed) and merges before data-engineer's migration PR starts.
- Changing the `search_tsv` expression = drop + re-add the generated column → treat as expand/contract with
  an ADR.

## 7. Example row (synthetic)

```json
{
  "id": "6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00",
  "message_mid": "synthetic-mid-0001",
  "sender_id": "1000000000000001",
  "ig_media_id": "3000000000000000001",
  "kind": "reel",
  "permalink": "https://www.instagram.com/reel/SyntheticCode1/",
  "caption": "Crispy smashed potatoes 🥔 boil, smash, roast at 220°C #recipe",
  "media_path": null,
  "title": "Crispy smashed potatoes",
  "search_text": "Crispy smashed potatoes boil, smash, roast at 220°C …",
  "category_id": 1,
  "confidence": 0.93,
  "relevant": true,
  "informativeness": 3,
  "decided_at_stage": 1,
  "evidence": { "version": 1, "...": "see interfaces.md §6" },
  "status": "done",
  "current_stage": 1,
  "claimed_at": "2026-11-01T10:00:05Z",
  "error": null,
  "raw_payload": { "...": "see payloads.md (M1)" },
  "created_at": "2026-11-01T09:58:41Z"
}
```

## 8. Open questions

- **Poison posts:** a post that hard-crashes the worker (process killed, not an exception) is recovered to
  `received` every 30 min forever. v0 accepts this (exceptions → `failed`). If it shows up, add an
  `attempts smallint not null default 0` column (expand-only) via ADR.
- **`kind` values** may change after the M1 payload spike (e.g. unsupported share types). Widening the check
  is an expand migration.
- **Hebrew + `pg_trgm`:** trigram extraction depends on the DB locale treating Hebrew letters as
  alphanumeric; verify in M5 with a synthetic Hebrew title.
