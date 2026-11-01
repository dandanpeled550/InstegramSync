# 0001 — Supabase receiver + laptop worker, with the database as the queue

- Status: accepted
- Date: 2026-11-01
- Deciders: product owner (PLAN.md v3), architect

## Context
- Meta delivers Instagram DM webhooks at any time and expects a fast `200`; delivery isn't guaranteed and the
  Conversations API can't serve as a full backup (only the 20 most recent messages per conversation;
  shares return a media URL only) — PLAN §10. So the receiving endpoint must be up 24/7.
- Attachment URLs in webhooks are signed CDN URLs that may expire, so media must be copied soon after delivery.
- Analysis (Jev, Gemini) costs money and is happy to run hours later; the owner runs it on a laptop that is
  often off. Budget is $0 for hosting.
- Supabase's free tier gives Postgres, Storage, Edge Functions and pg_cron in one project. Free projects
  pause after ~7 days idle.

## Decision
1. **Receiver = Supabase Edge Function `ig-webhook`** (Deno), deployed with `--no-verify-jwt` and verifying
   `X-Hub-Signature-256` instead. It is deliberately dumb: verify, filter (echo, sender allowlist), insert the
   raw payload, copy media to Storage in `EdgeRuntime.waitUntil`, send "Got it". No parsing beyond what the
   insert and media copy need — all payload knowledge lives in Python `ingest/parser.py`.
2. **Worker = Python on the laptop** (`python -m app.process`), triggered by CLI, the UI's "Process now", or
   optionally `launchd`. It reaches Supabase with `DATABASE_URL` + the service-role key.
3. **The `posts` table is the queue.** `status` (`received → analyzing → done | needs_review | failed`) drives
   the work; claims use `FOR UPDATE SKIP LOCKED`; rows stuck in `analyzing` > 30 min are recovered; every
   worker write is conditional on `(status='analyzing', claimed_at)` so overlapping runs are safe
   ([schema.md §3](../contracts/schema.md#3-postsstatus-state-machine)).
4. **Status and kind are `text` + named `check` constraints**, not Postgres enums, so adding a value is an
   expand-only migration.
5. **Access is service-role only.** RLS on every table with no policies, plus `revoke all` from `anon` and
   `authenticated`; the private `media` bucket has no `storage.objects` policies. The browser never talks to
   Supabase — only to the local FastAPI.
6. **Media is transient.** Copied on receipt, deleted once a post is `done`/`needs_review`, kept on `failed`
   for retry ([storage.md §4](../contracts/storage.md#4-lifecycle)).
7. **`refresh-token`** Edge Function, run daily by pg_cron, rotates the Instagram token in `app_secrets`;
   this also keeps the free project from pausing.

## Alternatives considered
| Option | Why not |
|---|---|
| Always-on Python server (Render free tier) receiving webhooks | Free tier sleeps; cold starts risk Meta timeouts/retries and lost events. Paid tier costs money |
| Laptop receives webhooks via a tunnel (ngrok, Cloudflare Tunnel) | Laptop off ⇒ webhooks lost; Meta can't be relied on to redeliver |
| Poll the Conversations API instead of webhooks | 20-message window and media-URL-only shares make it lossy |
| Parse payloads in the Edge Function | Two languages holding payload knowledge; payload shapes are still changing (`share` → `ig_post`); harder to re-run |
| A separate queue (SQS, Supabase Queues/pgmq) | Another moving part; a status column + `SKIP LOCKED` suffices at this volume and keeps the state visible in one table |
| Postgres enums for `status` / `kind` | Values can't be removed and changes are awkward in expand/contract migrations |
| RLS policies for an authenticated browser client | No browser client talks to Supabase; policies would only add attack surface |

## Consequences
- Easier: nothing lost while the laptop is off; the worker can later move to a cloud cron job unchanged (the
  DB is the queue); raw payloads + evidence allow re-running the cascade with better models.
- Harder: processing is delayed until the laptop runs; Edge Function time/memory and the 50 MiB upload cap
  may not fit long reels (verify in M2); a hard-crashing post is recovered every 30 min (no attempt counter in
  v0); the claim waits up to 5 min for media (`MEDIA_WAIT_MINUTES`) so a fast "Process now" doesn't race the
  media copy.
- Contracts: `schema.md`, `storage.md`, `interfaces.md` (`Post`, `run_worker`).
- Agents: receiver-engineer (function, media copy), data-engineer (migration, RLS, repo), pipeline-engineer
  (claim/recover/cleanup), web-engineer (retry/delete semantics), security-reviewer (signature, RLS, SSRF).
