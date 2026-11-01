# Storage contract — v0

- Version: v0.1 (M0.1b) · 2026-11-01 · owner: `architect` — v0.1: single conditional receiver media write,
  partial listing = no media
- Implemented by: `data-engineer` (bucket in the migration, `backend/app/db/storage.py`), `receiver-engineer`
  (upload), `pipeline-engineer` (download + cleanup), `web-engineer` (delete via API).
- Source: [PLAN.md §1, §2, §6](../PLAN.md), [ADR 0001](../decisions/0001-supabase-receiver-laptop-worker.md).

## 1. Buckets

| Bucket | Public | File size limit | Allowed MIME types | Created by |
|---|---|---|---|---|
| `media` | **no** (private) | 50 MiB (`52428800`) | `image/*`, `video/*` | the initial migration (`insert into storage.buckets … on conflict (id) do nothing`) |

There is exactly one bucket in v0. The 50 MiB limit matches the Supabase Free plan's global upload cap;
whether long reels fit is a known M2 risk (see §6).

## 2. Path layout

```
media/                          ← bucket
  {post_id}/                    ← posts.id (uuid, lowercase, hyphenated); posts.media_path = "{post_id}/"
    00.{ext}                    ← attachment 0 (cover / single photo / the reel video)
    01.{ext}                    ← attachment 1 (carousels only)
    …
```

- Object names are the 0-based attachment index in payload order, zero-padded to 2 digits (`00`–`99`),
  so lexical order = attachment order.
- `{ext}` comes from the response `Content-Type`:

  | Content-Type | ext |
  |---|---|
  | `image/jpeg` | `jpg` |
  | `image/png` | `png` |
  | `image/webp` | `webp` |
  | `image/heic` | `heic` |
  | `video/mp4` | `mp4` |
  | `video/quicktime` | `mov` |

  Any other type is **not stored** (counts as a failed attachment). The object is uploaded with that
  `Content-Type`.
- `posts.media_path` stores the folder prefix **without** the bucket name, with a trailing slash:
  `"6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00/"`. Readers list objects under it; they never guess file names.
- No other paths exist in the bucket. Nothing outside `{uuid}/NN.ext` is ever written.

Example (synthetic carousel with 3 images):

```
media/6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00/00.jpg
media/6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00/01.jpg
media/6f1c2a9e-0b7d-4e3a-9a51-2d4c8e7f1a00/02.jpg
```

## 3. Access

- Only the **service role** reads or writes `media`:
  - `ig-webhook` uses the `SUPABASE_SERVICE_ROLE_KEY` that Supabase injects into Edge Functions.
  - The laptop worker and local API use `SUPABASE_SERVICE_ROLE_KEY` from `.env.<env>`.
- **No `storage.objects` policies** are created for bucket `media` (Supabase keeps RLS enabled on
  `storage.objects`; with no policy, `anon`/`authenticated` can neither list, read, upload nor delete).
- No public URLs and no signed URLs are handed to the browser in v0 — the UI links to Instagram, not to
  stored media.
- `tests/db/` (M0.5) asserts: bucket `media` exists with `public = false`, the size limit and MIME list
  above; there are **zero policies on `storage.objects` in v0** (`select count(*) from pg_policies where
  schemaname = 'storage' and tablename = 'objects'` = 0 — any policy, whatever its `bucket_id` filter, is a
  contract change); and, with one object row present
  for `bucket_id = 'media'` (inserted as owner), `anon` / `authenticated` `select` returns **zero rows** and
  `insert` / `update` / `delete` change nothing or fail with `42501`. (Unlike the `public` tables, the
  migration does not revoke Supabase's own grants on `storage.objects` — RLS is what denies here.)
- The receiver downloads media **only from Meta CDN hosts** (allowlist owned by `receiver-engineer`,
  e.g. `lookaside.fbsbx.com`, `*.cdninstagram.com`, `*.fbcdn.net`) — SSRF guard. The exact normative SSRF
  rules (https and port 443 only, exact host or `.`-suffix match, no IP literals or userinfo, redirects
  re-checked per hop or not followed, streamed 50 MiB cap, timeouts, no auth headers to the CDN) are added
  here before M2 starts.

## 4. Lifecycle

| When | Actor | Action |
|---|---|---|
| Right after a **new** row is inserted (`returning id` gave a row; duplicates copy nothing) | `ig-webhook`, inside `EdgeRuntime.waitUntil(...)` after responding `200` | Download each attachment URL (one retry per attachment), upload to `{post_id}/NN.ext`. When every attachment has been attempted, **one** conditional update sets `media_path` and `error` together ([schema.md §3](schema.md#3-postsstatus-state-machine), receiver media write; [receiver.md §6](receiver.md#6-insert-and-dedupe)): **≥ 1** object stored → `media_path = '{post_id}/'`, plus `error = 'media_copy_partial'` if some failed; all failed → `media_path` stays `null`, `error = 'media_copy_failed'`. Never one update per attachment. `error` never contains the URL |
| Worker processes the post | worker (`analyze/media.py` via `db/storage.py`) | List objects under `media_path` and download them to a local temp dir; delete the temp dir when the post is finished (any outcome). **No media** = `media_path` is `null`, **or** the listing under it is empty, **or** any listed object is "not found" on download. In the last case the whole post counts as having no media (all downloaded files are discarded), because a partial set means a cleanup is deleting it — running vision on part of the media would overwrite the full stored vision. No media is not an error: the cascade reuses stored vision or skips Stages 2–3 (interfaces.md §6) |
| Post reaches `done` or `needs_review` | worker | **After** the result row is committed: delete all objects under `media_path` ("not found" is success), then `update posts set media_path = null where id = $1 and status in ('done','needs_review') and media_path is not null` ([schema.md §3](schema.md#3-postsstatus-state-machine) write conditions) |
| Post reaches `failed` | worker | **Keep** the media, so `retry` can re-run vision |
| Each worker run, after the batch loop | worker | **Cleanup sweep:** for rows with `status in ('done','needs_review') and media_path is not null`, delete objects, then null `media_path` with the same conditional update as above (catches deletes that failed earlier). Idempotent; "not found" is success |
| `DELETE /api/posts/{id}` | local API | Delete all objects under `{id}/` first ("not found" is success), then delete the row. If Storage errors, the row is kept and the API returns `502` |

Consequences:
- Steady-state storage ≈ media of posts still `received`/`analyzing`/`failed` → stays far inside the 1 GB free tier.
- Retrying a `done`/`needs_review` post finds no media; the cascade reuses the vision outputs already in
  `posts.evidence` (see [interfaces.md §6](interfaces.md#evidence-json-postsevidence)) instead of re-calling vision.
- A retry that lands between the result commit and the cleanup leaves `media_path` set on a `received` row
  whose objects are (or are about to be) gone. That is the "no media" case above, not a failure.
- Orphaned folders are not swept in v0; acceptable at this volume. They arise when a row is deleted by hand in
  the dashboard; when `DELETE /api/posts/{id}` runs while the receiver's `waitUntil` upload for that post
  is still in progress (the receiver media write then updates zero rows); or when the Edge Function instance
  hits a platform limit mid-upload, so the final media write never runs (`media_path` stays `null` and the
  worker processes the post caption-only after `MEDIA_WAIT_MINUTES`).

## 5. Errors

| Situation | Behavior |
|---|---|
| Upload exceeds the bucket size limit | counts as a failed attachment (`media_copy_partial` / `media_copy_failed`) |
| CDN URL expired / non-2xx / host not in allowlist | failed attachment; never retried after the one retry |
| Worker can't download an object listed under `media_path` (any error except "not found") | post → `failed`, `error = 'media_download_failed'`; media kept |
| Listing under `media_path` is empty, or any listed object is "not found" | no media for the whole post (§4) — not an error |
| Delete fails during cleanup | leave `media_path` set; the next run's sweep retries |

## 6. Open questions

- **Large reels (M2):** Edge Function wall-clock/memory limits and the 50 MiB upload cap vs. long reels —
  `researcher` to confirm limits, `receiver-engineer` to test with a long reel. If they don't fit, an ADR
  decides (e.g. store a lower-resolution rendition, or let the worker fetch late).
- **What the reel attachment URL points to (M1):** if it isn't a downloadable video file, the receiver
  stores only the cover image and Stage 3 falls back accordingly — decided after the payload spike.
- **Thumbnails (PLAN §11 Q4):** if accepted, a separate `thumbs/{post_id}.webp` path that survives
  processing is a contract change (ADR).
