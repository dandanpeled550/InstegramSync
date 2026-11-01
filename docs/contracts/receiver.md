# Receiver security contract — v0

- Version: v0 (M0.1b) · 2026-11-01 · owner: `architect`
- Implemented by `receiver-engineer` in `supabase/functions/ig-webhook/` (Deno / TypeScript).
- **Binding from the M1 receiver v0** (the spike build), not only from M2. Every rule here holds for any
  deployed `ig-webhook`, whatever else it does yet. A receiver PR that skips one fails security review.
- Sources: [PLAN.md §1](../PLAN.md#1-receiver--supabase-edge-function-ig-webhook),
  [research: Meta webhooks](../research/meta-webhooks.md),
  [research: Edge Functions](../research/supabase-edge-functions.md),
  [ADR 0001](../decisions/0001-supabase-receiver-laptop-worker.md).
- **Not in this file:** payload *shapes* (attachment types, reel/carousel keys, the final
  `unsupported_payload` reasons). They go to `payloads.md` after the M1 spike. The rules below use only the
  envelope fields the research confirms (`object`, `entry[].id`, `entry[].messaging[]`, `sender.id`,
  `message.mid`, `message.is_echo`). The SSRF rules for the media copy go to [storage.md §3](storage.md#3-access)
  before M2.

## 1. Configuration — fail closed

Supabase secrets, per project (`supabase secrets set …`, never in git; `.env.example` lists names only):

| Variable | Valid when | Used for |
|---|---|---|
| `META_APP_SECRET` | non-empty after trimming | HMAC key for `X-Hub-Signature-256` |
| `META_VERIFY_TOKEN` | non-empty after trimming | GET handshake |
| `ALLOWED_SENDER_IDS` | comma-separated list; items trimmed, empty items ignored; **at least one item, and every item matches `^[0-9]+$`** | sender allowlist |

The function reads them **on every request** (no caching across a config change). If any one is unset,
empty or invalid, **every** request (GET and POST) gets `500` with an empty body. Nothing else happens: no
signature check, no DB access, no outbound fetch, no DM. The log line names the variable, never its value
(`config_invalid: ALLOWED_SENDER_IDS`). Why `500` rather than `200`: Meta retries a failed delivery for up
to 36 h, so events sent while the function is misconfigured are redelivered once it is fixed.

Why these rules: an HMAC with an empty key can be forged by anyone, and an empty allowlist must mean
"nobody", never "everybody". Requiring digits-only items rules out wildcards such as `*`.

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected by the platform; a missing one is also a
`500` with no further processing.

## 2. Request handling, in this order

| Step | Check | On failure |
|---|---|---|
| 1 | Configuration valid (§1) | `500` |
| 2 | Method is `GET` (handshake, §3) or `POST` (events, steps 3–7) | `405` |
| 3 | Body size: `Content-Length`, when present, ≤ `MAX_BODY_BYTES`; then read the body as a stream and stop as soon as more than `MAX_BODY_BYTES` bytes have arrived (a missing or false `Content-Length` doesn't help an attacker) | `413`, body not hashed or parsed |
| 4 | Signature (§4) over the **exact raw bytes** read in step 3 | `403` |
| 5 | Decode UTF-8 (fatal on invalid bytes), `JSON.parse`, require `object === "instagram"` and an `entry` array | `200`, nothing stored (logged as `ignored: unparsable` / `ignored: not_instagram`) — a signed body that never parses would only be retried uselessly |
| 6 | Filter **each** `entry[].messaging[]` event on its own (§5) | dropped events are counted, not errors |
| 7 | Insert each event that passed (§6), awaited before responding | `500` if any insert failed (Meta redelivers; dedupe makes it safe) |
| — | Respond | `200`, empty body |

Rules that tie the steps together:
- **Nothing before verification.** No DB read or write, no outbound fetch (CDN, Graph API) and no DM happens
  before step 4 passed **and** the event passed step 6. A request rejected in steps 1–4 causes no I/O beyond
  reading its own body.
- **Always `200` after a valid signature**, including when every event was filtered out, the body was ignored
  in step 5, or every event was a duplicate. The only non-`200` after a valid signature is `500` for a failed
  insert. Respond as soon as the inserts are done: media copy and the ack DM (M2) never delay the response —
  they run in `EdgeRuntime.waitUntil(...)` after it.
- Error responses have an empty body: no reason, no echo of input.

**`MAX_BODY_BYTES` = 1 MiB (1,048,576 bytes).** Justification, against
[research: Edge Functions](../research/supabase-edge-functions.md): the platform's own request-body limit is
undocumented, so we set one. Hashing and parsing 1 MiB costs a few milliseconds, far inside the 2 s CPU and
256 MB memory limits. A share event is ~1–3 KB; even a 2,200-character Hebrew caption, which Meta sends
`\uXXXX`-escaped (about 6 bytes per character), stays under ~15 KB, so 1 MiB holds dozens of worst-case
events — more than a one-owner bot ever batches. The cost of being wrong is visible: a `413` is logged with
the byte length, and the size seen in the M1 spike is recorded in `payloads.md`. Changing the value is a
contract change.

## 3. GET handshake

Read the query with `new URL(req.url).searchParams` (the dots in `hub.*` are literal).

- `hub.mode` must equal `"subscribe"`.
- `hub.verify_token` must equal `META_VERIFY_TOKEN`, compared in **constant time** over the UTF-8 bytes (§4).
- `hub.challenge` must be present, non-empty and ≤ 128 characters.
- All three hold → `200`, body = the `hub.challenge` value exactly, `Content-Type: text/plain; charset=utf-8`,
  `X-Content-Type-Options: nosniff`. Never HTML or JSON.
- Anything else → `403`, empty body. The handshake never touches the DB.

## 4. Signature (`POST`)

- Header `X-Hub-Signature-256` must be present and of the form `sha256=` followed by exactly 64 hex digits.
  Missing, another prefix, wrong length or non-hex → `403`.
- Expected value = HMAC-SHA256(key = `META_APP_SECRET` as UTF-8, message = the raw request bytes from step 3).
  Never hash a re-serialized or re-encoded body: Meta escapes non-ASCII as `\uXXXX` in what it signs, so
  `JSON.stringify(JSON.parse(body))` does not reproduce the signed bytes.
- Compare in **constant time**: `crypto.subtle.verify("HMAC", key, receivedBytes, rawBody)`, or a
  constant-time compare of two equal-length byte arrays (e.g. `timingSafeEqual` from `@std/crypto`). Never
  `===` / `==` on strings, hex or base64. The same helper is used for the verify token in §3.
- Mismatch → `403`. Parsing (step 5) starts only after a match.

## 5. Per-event filter

Each `entry[].messaging[]` event is checked on its own, in this order; the first failing check drops that
event only (the others in the batch continue):

1. **Shape:** the event is an object with `sender.id` a non-empty string and `message.mid` a non-empty
   string. Otherwise drop (`not_a_message` — reactions, reads, postbacks and the like; `payloads.md` may
   refine this after the spike).
2. **Echo:** drop if `message.is_echo === true` **or** `sender.id === entry.id` (the bot's own messages,
   including our ack DM, come back as events). Both conditions, as the research recommends: the echo shape
   under Instagram Login is only confirmed in the M1 spike, and either check alone may miss one.
3. **Allowlist:** keep only if `sender.id` equals one of the `ALLOWED_SENDER_IDS` items (exact string
   compare). Otherwise drop (`sender_not_allowed`).

The bot's own id is **never** in `ALLOWED_SENDER_IDS` (it would let echoes through if the echo check were
ever wrong). The receiver enforces this: an `entry` whose `id` is in the allowlist is dropped as a whole and
logged as `config_error: bot_id_allowlisted` (still `200`).

Accepted events are not otherwise interpreted here: a plain-text DM from an allowlisted sender is stored and
the worker marks it `failed` with `unsupported_payload: <reason>` (schema.md §3.1).

## 6. Insert and dedupe

- One insert per accepted event: `insert into posts (message_mid, sender_id, raw_payload) values (…) on conflict
  (message_mid) do nothing returning id` (schema.md §3), with `message_mid = message.mid`,
  `sender_id = sender.id`, `raw_payload` = the event object exactly as parsed. Any client that produces the
  same statement is fine (e.g. supabase-js `upsert(…, { onConflict: "message_mid", ignoreDuplicates: true })`).
- **Dedupe on `message.mid`.** Meta retries failed deliveries for up to 36 h, so duplicates are normal. No row
  returned = duplicate → nothing else happens for that event (no media copy, no DM), and it still counts as
  success.
- Only rows that were actually inserted get background work (media copy, ack DM — M2), even if a later
  insert in the same request failed.
- **Post-upload write (M2 media copy):** after all attachments of a post were attempted, **one** update sets
  `media_path` and `error` together, conditional on `status = 'received'` — exact statement, zero-rows meaning
  and why it can't race the worker in [schema.md §3](schema.md#3-postsstatus-state-machine) (write
  conditions). Never one update per attachment: the worker may claim as soon as `media_path` is set.

## 7. Outbound calls (M2)

- The ack DM is sent only for a newly inserted row, inside `waitUntil`, after the response.
- The Graph API token (`app_secrets.ig_access_token`) goes in an `Authorization: Bearer` header, never in a URL
  query string (`?access_token=` ends up in error messages and logs). Graph API support for the header with
  Instagram Login is checked in M2; if only the query form works, the request URL is never logged or
  included in an error.
- Media downloads follow the SSRF rules in storage.md §3 (M2 entry condition).

## 8. Logging

Allowed in logs: the HTTP status and outcome code, `pathname` (never the full URL — the handshake query
contains `hub.verify_token`), body byte length, counts per drop reason, number of rows inserted, inserted
`posts.id` values, exception class names and SQLSTATE codes.

Never logged: the raw or parsed body or any part of it (captions, CDN URLs, `mid`s, sender ids), request
headers (`X-Hub-Signature-256`, `Authorization`, `apikey`), the query string, any env value or token, and
database error messages or details (they can echo row values — log the SQLSTATE only).

## 9. Deployment

- `verify_jwt = false` for **`ig-webhook` only**: `[functions.ig-webhook] verify_jwt = false` in
  `supabase/config.toml` (devops-engineer) and the matching per-function deploy flag in CI. Never a
  project-wide setting; every other function (e.g. `refresh-token`, M2) keeps its own auth, specified in its
  M2 contract.
- The service-role key is used only inside the function and never appears in a response or log.

## 10. Tests `receiver-engineer` must write (Deno, no network)

Inject env, a fake DB client and a fake `fetch`; every test also checks what the fakes recorded.

| Rule | Test |
|---|---|
| Fail closed | each of the three variables unset / `""` / `"  "` → `GET` and `POST` both `500`, zero DB calls, zero fetches. `ALLOWED_SENDER_IDS` = `","`, `"abc"`, `"123,*"` → `500` |
| Method | `PUT` → `405` |
| Handshake | correct → `200`, body = challenge, `text/plain`; wrong token, token differing only in the last character, missing token, `hub.mode=unsubscribe`, missing challenge, 129-char challenge → `403`; no DB call in any case |
| Size | `Content-Length: 1048577` → `413` without reading the body; a chunked body of 1 MiB + 1 byte with no `Content-Length` → `413`; a body of exactly 1 MiB with a valid signature → processed |
| Signature | valid → `200`; header missing, prefix `sha1=`, 63 hex digits, non-hex, wrong digest → `403`, zero DB calls; a body containing `é` signed over its raw bytes → accepted, while the same signature checked against `JSON.stringify(JSON.parse(body))` would fail (proves raw bytes are hashed) |
| Order | invalid signature with an allowlisted sender in the body → zero DB calls, zero fetches |
| Echo | allowlisted sender with `is_echo: true` → not inserted; event with `sender.id === entry.id` and no `is_echo` → not inserted; both → `200` |
| Allowlist | unknown sender → not inserted, `200`; one batch with 2 entries and 3 events (allowed, echo, stranger) → exactly 1 insert; an entry whose `id` is allowlisted → nothing from it inserted |
| Shape | event without `message.mid` (e.g. a reaction) → not inserted, `200` |
| Body ignored | valid signature + invalid JSON, invalid UTF-8, or `object: "page"` → `200`, zero inserts |
| Dedupe | insert returns no row → no background work scheduled, `200` |
| DB failure | insert throws → `500`; background work is scheduled only for rows inserted before the failure |
| Logging | capture all log output across the suite: it never contains the body, the signature value, `META_APP_SECRET`, `META_VERIFY_TOKEN`, a sender id, a `mid` or a query string |
| Deploy config | parse `supabase/config.toml`: `[functions.ig-webhook] verify_jwt = false`, and no other function and no project-level setting has `verify_jwt = false` |
| Post-upload write (M2) | the media write is the single conditional update from schema.md §3; zero rows updated → no throw, no retry |

## 11. Example (synthetic)

```text
POST /functions/v1/ig-webhook
X-Hub-Signature-256: sha256=<64 hex digits: HMAC-SHA256(META_APP_SECRET, raw body)>

{"object":"instagram","entry":[{"id":"17841000000000000","time":1700000000000,"messaging":[
  {"sender":{"id":"1000000000000001"},"recipient":{"id":"17841000000000000"},"timestamp":1700000000000,
   "message":{"mid":"synthetic-mid-0001","attachments":[{"type":"ig_post","payload":{"url":"…"}}]}},
  {"sender":{"id":"17841000000000000"},"recipient":{"id":"1000000000000001"},"timestamp":1700000000500,
   "message":{"mid":"synthetic-mid-0002","is_echo":true,"text":"Got it 👍"}}]}]}
```

With `ALLOWED_SENDER_IDS=1000000000000001`: the first event is inserted (`message_mid =
"synthetic-mid-0001"`), the second is dropped as an echo, and the response is `200` with an empty body.

## 12. Open questions

- **Meta's response deadline:** the research says "respond promptly" but gives no number. The design awaits
  only the inserts, so it should be well under any plausible deadline; confirm in the M1 spike.
- **Handshake query in platform logs:** Supabase's own invocation logs may record the request URL, including
  `hub.verify_token`. Low impact (the token only answers Meta's handshake); rotating `META_VERIFY_TOKEN` after
  setup is an option. Confirm in M1 what the platform logs show.
