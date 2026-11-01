# What are Supabase Edge Function limits, and how do we run background work, public webhooks and cron?
- Answer: Hosted limits are 2 s CPU time per request, 256 MB memory, 150 s wall clock on Free (400 s paid),
  150 s idle timeout, 20 MB bundle (CLI). Use `EdgeRuntime.waitUntil(promise)` (not awaited) to keep working
  after returning `200`, within the same wall-clock window. Public webhooks need JWT verification off
  (`--no-verify-jwt` at deploy or `verify_jwt = false` in `config.toml`) plus our own signature check.
  Schedule functions with `pg_cron` + `pg_net` (`net.http_post`), keeping the URL and key in Vault. Free plan:
  500,000 invocations, 1 GB storage, 50 MB max upload per file, 500 MB DB, 5 GB egress, projects pause after
  1 week of inactivity.
- Confidence: high for the limits and patterns (official docs); medium for streaming a large reel within 2 s
  CPU / 256 MB (not tested); request-body size limit not documented.
- Checked: 2026-11-01
- Sources:
  - Supabase — [Edge Function limits](https://supabase.com/docs/guides/functions/limits)
  - Supabase — [Background tasks](https://supabase.com/docs/guides/functions/background-tasks)
  - Supabase — [Scheduling Edge Functions](https://supabase.com/docs/guides/functions/schedule-functions)
  - Supabase — [Securing Edge Functions](https://supabase.com/docs/guides/functions/auth)
  - Supabase — [Pricing](https://supabase.com/pricing)

## Details

### Limits (hosted)
| Limit | Value |
|---|---|
| CPU time | 2 s per request (async I/O waiting does not count) |
| Wall clock | 150 s Free / 400 s paid; a worker can serve several requests and run background tasks inside this window |
| Idle timeout | 150 s without a response → caller gets 504 |
| Memory | 256 MB |
| Bundle | 20 MB (CLI bundling) / 5 MB (server-side bundling) |
| Functions per project | 100 Free / 1,000 Pro |
| Request body size | not stated in the limits page (unverified) |

Implication: downloading a reel is mostly network I/O (cheap on CPU), but buffering a large video in memory
risks the 256 MB cap. Stream the response body straight into Storage (`fetch(url).body` → upload) rather than
`await res.arrayBuffer()`. Supabase Storage free tier caps a single file at 50 MB, which fits typical reels
but not long ones.

### `EdgeRuntime.waitUntil`
```ts
Deno.serve((req) => {
  EdgeRuntime.waitUntil(downloadMedia(postId, url)); // do NOT await
  return new Response("ok", { status: 200 });
});
```
- The instance stays alive until the promise settles or a limit (wall clock/CPU/memory) is hit.
- Wrap work in `try/catch`; optionally listen to `beforeunload` (`ev.detail?.reason`) to log why shutdown
  happens and mark the row so the worker can retry the download.
- **Local gotcha:** the CLI kills instances after each request, cutting background tasks. Set
  `[edge_runtime] policy = "per_worker"` in `supabase/config.toml` for local dev (owned by devops).
- Design consequence: insert the row (with `raw_payload`) *before* responding, then download in the
  background; if the download fails the row still exists and the worker can fetch from the (possibly expired)
  URL or mark `needs_review`.

### Public webhook auth
- Meta sends no Supabase JWT, so deploy with `supabase functions deploy ig-webhook --no-verify-jwt` or set
  `[functions.ig-webhook] verify_jwt = false`. Supabase's guidance: for external webhooks keep the platform
  check off and verify the caller yourself (our `X-Hub-Signature-256` check).
- Community note (unverified): with the newer API-key system, functions that call Supabase with the
  secret key must read it from env (`SUPABASE_SERVICE_ROLE_KEY` / newer secret-key vars); check at M2.

### pg_cron + pg_net scheduling
```sql
select cron.schedule(
  'refresh-token-daily',
  '0 3 * * *',
  $$
  select net.http_post(
    url     := (select decrypted_secret from vault.decrypted_secrets where name = 'project_url') || '/functions/v1/refresh-token',
    headers := jsonb_build_object(
                 'Content-Type', 'application/json',
                 'apikey', (select decrypted_secret from vault.decrypted_secrets where name = 'secret_key')),
    body    := '{}'::jsonb
  );
  $$
);
```
- Official example runs every minute, reads URL and key from Vault, passes the key in the `apikey` header; the
  function disables `verify_jwt` and checks the key itself (`auth: 'secret'` with `@supabase/server`).
- Caution from the docs: `pg_net` stores the decrypted key in `net.http_request_queue` until sent, so any
  DB-login role could read it — fine for a single-owner project.
- Alternative for `refresh-token`: since it doesn't need a public caller, give it its own shared secret in
  a header and keep `verify_jwt = false`.
- Timeout for pg_net requests was not stated on the scheduling page (unverified; `timeout_milliseconds`
  defaults are in the pg_net docs, not checked).
- The cron migration belongs to `data-engineer`; secrets in Vault must be set per project (dev/prod).

### Free-tier quotas relevant to us
500k invocations/month, 1 GB storage (media deleted after processing), 50 MB per file, 500 MB DB, 5 GB
egress, max 2 active projects, **paused after 1 week of inactivity** (the daily cron call counts as activity
per PLAN.md's assumption — not confirmed by docs; verify on staging).

## Unverified / needs the M1–M2 spike
1. Request body size limit for incoming webhooks (webhooks are small; low risk).
2. Whether a ~30–60 MB reel streams within 256 MB / 2 s CPU (M2 long-reel test per PLAN.md §10).
3. Whether pg_cron-triggered calls prevent free-project pausing.
4. pg_net default timeout for the daily `refresh-token` call.
5. `waitUntil` behaviour when the function returns before Storage upload finishes under load.
