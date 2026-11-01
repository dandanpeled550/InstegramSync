# Schema contract — v0

- Version: v0 (M0.1) · 2026-11-01 · owner: `architect`
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
| `error` | `text` | yes | — | receiver, worker | a fixed error code from §3.1 — never raw exception text, secrets, tokens, URLs or post content; ≤ 500 chars |
| `raw_payload` | `jsonb` | no | — | receiver | the webhook `messaging` event exactly as received (shape: `payloads.md`, M1) |
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
| — | `received` | receiver | `insert (message_mid, sender_id, raw_payload) … on conflict (message_mid) do nothing returning id` |
| `received` | `analyzing` | worker claim | `status='analyzing', current_stage=0, claimed_at=now()` — see claim query below (`error` is left as-is so a receiver `media_copy_*` code stays visible until the result is written) |
| `analyzing` | `received` | worker recover | rows with `claimed_at < now() - interval '30 minutes'`: `status='received', current_stage=null, claimed_at=null` |
| `analyzing` | `done` / `needs_review` | worker | result columns + `current_stage=coalesce(decided_at_stage, 0), error=null`; then media cleanup ([storage.md §4](storage.md#4-lifecycle)) |
| `analyzing` | `failed` | worker | `status='failed', error=<code from §3.1>`; `current_stage` left as-is (shows where it failed); media kept |
| `needs_review` / `done` | `done` | API `PATCH /api/posts/{id}` | `category_id=<chosen>, status='done'`; in `evidence`: set `needs_review=false`, `review_reason=null`, and **set** (overwrite, not append) `manual_override` (interfaces.md §6) |
| `done` / `needs_review` / `failed` | `received` | API `POST /api/posts/{id}/retry` | `status='received', current_stage=null, claimed_at=null, error=null` (result columns kept until overwritten) |
| any | (row deleted) | API `DELETE /api/posts/{id}` | delete Storage objects, then `delete from posts where id=$1` |

**Write conditions.** Every write above is conditional, and "zero rows updated" has a defined meaning:

| Write | `where` condition | Zero rows updated means |
|---|---|---|
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

**Per-status invariants** (true for every row, whoever wrote it). "—" = unspecified: `null` on a fresh row,
the previous run's values after a retry (kept until overwritten). Readers must not treat "—" values as the
current result — the one deliberate use is the worker reading the previous `evidence` on a retry to reuse
stored vision (interfaces.md §6).

| `status` | `category_id` | `decided_at_stage`, `confidence`, `relevant`, `informativeness` | `evidence` | `evidence.review_reason` | `current_stage` | `claimed_at` | `error` |
|---|---|---|---|---|---|---|---|
| `received` | — | — | — | — | `null` | `null` | `null` or `media_copy_*` |
| `analyzing` | — | — | — | — | 0–3 | not null | `null` or `media_copy_*` |
| `done` | **not null** | not null — except all four `null` when `evidence.manual_override` is set and the overridden result was `no_evidence` | not null, `needs_review=false` | `null` | 0–3 | last claim | `null` |
| `needs_review` | not null — `null` iff `review_reason='no_evidence'` | not null — all four `null` iff `review_reason='no_evidence'` | not null, `needs_review=true` | **not null** | 0–3 | last claim | `null` |
| `failed` | — | — | — | — | stage where it failed (0–3) | last claim | **not null**, a §3.1 code |

`no_evidence` = no stage could run (no usable caption and no media, nor stored vision). Also:
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
| `unsupported_payload: <reason>` | worker | `parse()` raised `UnsupportedPayload`; `<reason>` is its machine code (`no_attachment`, `unsupported_type`, … — final list in `payloads.md`, M1) |
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
Keep `CLAIM_BATCH_SIZE × worst-case time per post` (a Stage 3 reel: a few minutes) well under
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
`PUBLIC`. The initial migration therefore runs:

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
- For every function in `public` that is not an extension member (`pg_depend.deptype <> 'e'`):
  `has_function_privilege(role, oid, 'EXECUTE')` is false.
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

Also:
- Every new table, view, sequence and function follows the §5 rules (RLS + revokes, `security_invoker`) in
  the migration that creates it.
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
