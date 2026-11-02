# Receiver security contract — v0

- Version: v0 (M0.1b) · 2026-11-02 · owner: `architect` — round 2: per-event insert with transient /
  permanent classification and a placeholder row, verify-token digest compare and length floor, malformed
  `Content-Length`, `HEAD`/`OPTIONS`, extended test table · round 3: trimmed secrets used for HMAC and
  digest, class `54` and `PGRST102` permanent, lone-surrogate tests, alerting on repeated codes, placeholder
  `sqlstate` regex · round 4: a failed placeholder insert is transient unless class `23`/`54`, alert on any
  `placeholder_rejected`, "trim" is `String.prototype.trim()`
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
| `META_VERIFY_TOKEN` | **at least 32 characters** after trimming; generated, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"` (43 characters) | GET handshake |
| `ALLOWED_SENDER_IDS` | comma-separated list; items trimmed, empty items ignored; **at least one item, and every item matches `^[0-9]+$`** | sender allowlist |

**Trimming** always means JavaScript `String.prototype.trim()`: it removes leading and trailing whitespace
and line terminators as ECMAScript defines them (ASCII space, tab, CR, LF, VT, FF, and Unicode spaces such
as U+00A0 and U+FEFF), and nothing else. The same function is used for all three variables and for each
`ALLOWED_SENDER_IDS` item. "Characters" in a length rule means the trimmed string's `.length`.

**The trimmed value is the value.** After validation the function uses the trimmed string of
`META_APP_SECRET` and `META_VERIFY_TOKEN` everywhere: the HMAC key (§4) and the verify-token digest (§4) are
computed from exactly the string the validity rule checked, never from the raw env value. The incoming
`hub.verify_token` is not trimmed (it is compared as received). So a secret pasted with a trailing newline
works, and the length floor can't be met by whitespace.

The function reads them **on every request** (no caching across a config change). If any one is unset,
empty or invalid, **every** request (GET and POST) gets `500` with an empty body. Nothing else happens: no
signature check, no DB access, no outbound fetch, no DM. The log line names the variable, never its value
(`config_invalid: ALLOWED_SENDER_IDS`). Why `500` rather than `200`: Meta retries a failed delivery for up
to 36 h, so events sent while the function is misconfigured are redelivered once it is fixed.

Why these rules: an HMAC with an empty key can be forged by anyone, and an empty allowlist must mean
"nobody", never "everybody". Requiring digits-only items rules out wildcards such as `*`. A short verify
token makes the handshake's `200`/`403` answer a guessing oracle.

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected by the platform. They are checked in the same
step and also read on every request: a missing or empty one is a `500` with an empty body and no I/O
(`config_invalid: SUPABASE_URL`). The DB client may be built per request, or cached keyed on these two
values; never built once at module load.

## 2. Request handling, in this order

| Step | Check | On failure |
|---|---|---|
| 1 | Configuration valid (§1) | `500` |
| 2 | Method is `GET` (handshake, §3) or `POST` (events, steps 3–7). Everything else, **including `HEAD` and `OPTIONS`**, is rejected. There is no CORS handler: do not copy the stock Supabase function template's `OPTIONS` / `Access-Control-Allow-Origin: *` block | `405` |
| 3a | `Content-Length`, when present, is a single value matching `^[0-9]+$`. Non-numeric, negative, empty or comma-joined values are malformed and are never read as `0` | `400`, body not read |
| 3b | Body size: `Content-Length`, when present, ≤ `MAX_BODY_BYTES`; then read the body as a stream and stop as soon as more than `MAX_BODY_BYTES` bytes have arrived (a missing or false `Content-Length` doesn't help an attacker) | `413`, body not hashed or parsed |
| 4 | Signature (§4) over the **exact raw bytes** read in step 3b | `403` |
| 5 | Decode UTF-8 (fatal on invalid bytes), `JSON.parse`, require `object === "instagram"` and an `entry` array | `200`, nothing stored (logged as `ignored: unparsable` / `ignored: not_instagram`) — a signed body that never parses would only be retried uselessly |
| 6 | Filter **each** `entry[].messaging[]` event on its own (§5) | dropped events are counted, not errors |
| 7 | Insert **each** event that passed, independently (§6), all awaited before responding | `500` if at least one insert failed **transiently**; permanent rejections count as handled |
| — | Respond | `200`, empty body |

Rules that tie the steps together:
- **Nothing before verification.** No DB read or write, no outbound fetch (CDN, Graph API) and no DM happens
  before step 4 passed **and** the event passed step 6. A request rejected in steps 1–4 causes no I/O beyond
  reading its own body.
- **Always `200` after a valid signature**, including when every event was filtered out, the body was ignored
  in step 5, every event was a duplicate, or an insert was rejected permanently (§6). The only non-`200`
  after a valid signature is `500` for a transient insert failure. Respond as soon as the inserts are done:
  media copy and the ack DM (M2) never delay the response — they run in `EdgeRuntime.waitUntil(...)` after
  it.
- **Error responses have an empty body** (`400`, `403`, `405`, `413`, `500`): no reason, no echo of input.
- **No `Access-Control-*` header on any response.**

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
- `hub.verify_token` must equal `META_VERIFY_TOKEN`, compared as **SHA-256 digests** (§4, verify-token
  compare). A missing `hub.verify_token` is a mismatch.
- `hub.challenge` must match `^[0-9]{1,128}$` (the research says Meta sends an integer; if the M1 spike shows
  otherwise, widening this is a contract change).
- All three hold → `200`, body = the `hub.challenge` value exactly, `Content-Type: text/plain; charset=utf-8`,
  `X-Content-Type-Options: nosniff`. Never HTML or JSON.
- Anything else → `403`, empty body. The handshake never touches the DB.

## 4. Signature (`POST`) and constant-time compares

- Header `X-Hub-Signature-256` must be present and of the form `sha256=` followed by exactly 64 hex digits.
  Missing, another prefix, wrong length or non-hex → `403`.
- Expected value = HMAC-SHA256(key = the **trimmed** `META_APP_SECRET` (§1) as UTF-8, message = the raw request bytes from step 3b).
  Never hash a re-serialized or re-encoded body: Meta escapes non-ASCII as `\uXXXX` in what it signs, so
  `JSON.stringify(JSON.parse(body))` does not reproduce the signed bytes.
- Compare in **constant time**: `crypto.subtle.verify("HMAC", key, receivedBytes, rawBody)` with the 32 bytes
  decoded from the 64 hex digits, or a constant-time compare of two 32-byte arrays (e.g. `timingSafeEqual`
  from `@std/crypto`). Never `===` / `==` on strings, hex or base64.
- Mismatch → `403`. Parsing (step 5) starts only after a match.

**Verify-token compare** (§3): compute `SHA-256(UTF-8(hub.verify_token))` (as received) and `SHA-256(UTF-8(trimmed META_VERIFY_TOKEN))` (§1)
— always 32 bytes each — and compare the digests with `timingSafeEqual`. There is **no** length check before
it and no early return on a length difference: `timingSafeEqual` on raw values of different lengths throws or
returns early, which leaks the token length.

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
- **Every accepted event is attempted independently**, in batch order. A failed insert never stops the
  others. Background work (media copy, ack DM — M2) is scheduled for every row that was actually inserted
  (not a duplicate, not a placeholder), whatever happened to the other events and even if the response is
  `500`; a redelivery then dedupes those rows.

**Insert errors.** The SQLSTATE is the `code` of the PostgREST error body when it matches `^[0-9A-Z]{5}$`
(`PGRST…` codes are not SQLSTATEs); its class is the first two characters. Each failed insert is classified:

| Class | Errors | Outcome for that event |
|---|---|---|
| **Permanent** | SQLSTATE class `22` (data exception, e.g. `22P05`: jsonb rejects a `\u0000` escape in third-party caption text; `22P02`: invalid json input), class `23` (integrity; `23505` on `message_mid` never surfaces, `on conflict` absorbs it), class `54` (program limit exceeded, e.g. `54000`: an index row too large for an oversized `mid`), or PostgREST code **`PGRST102`** (HTTP `400`, invalid request body) | log `insert_rejected: <SQLSTATE or PGRST102>`, store the **placeholder row** below, counts as handled |
| **Transient** | everything else: network error, timeout, no response, PostgREST HTTP `5xx`, SQLSTATE classes `08`, `40`, `53`, `57` (and any other class, e.g. `42` after a bad migration), every other `PGRST…` code (including the rest of `PGRST1xx`, which a client or config bug produces for every request) / HTTP `401`/`403` from a wrong key | log `insert_failed: <SQLSTATE \| PGRST code \| HTTP status \| exception class>`; the response is `500` so Meta redelivers |

Unknown errors default to **transient**: a redelivery after the cause is fixed stores the event, and dedupe
makes the retry safe. Only the entries in the permanent row are known to fail the same way forever for the
same input.

**Lone surrogates.** A caption can carry a `\ud800` escape with no low surrogate. Step 5 accepts it (the
bytes are valid ASCII and `JSON.parse` allows it), the receiver passes the event to the DB client unchanged,
and the client's `JSON.stringify` sends it as `\ud800`. The expected outcome is SQLSTATE `22P02` from
Postgres's jsonb input (class 22, permanent), unless PostgREST's own JSON parser rejects the body first
(`PGRST102`, permanent too). Both are covered by the table; which one the pinned Supabase stack produces is
fixed by the integration test in §10, so a platform upgrade that changes it fails that test instead of
silently turning a permanent rejection into a 36 h retry loop.

**Alerting** (devops-engineer, M0.6): the same `insert_failed: <code>` or `placeholder_failed: <code>` in 3 or
more requests within 1 hour alerts the owner (a transient error that keeps repeating is probably permanent
and is looping on Meta's retries), and so does the same `insert_rejected: <code>` in 3 or more log lines
within 1 hour (one input being rejected is bad input; every share being rejected is a bug, e.g. a bad
migration). **Any single `placeholder_rejected: <code>` alerts** (threshold 1, not tunable): it is the only
case where a share leaves no row. The other thresholds are defaults that devops may tune in `ops/`; the log
codes above are the contract.

**Placeholder row** (permanent rejection only). So the owner sees that a share failed instead of it vanishing,
the receiver inserts, with the same `on conflict (message_mid) do nothing`:

```text
message_mid = message.mid, sender_id = sender.id,
raw_payload = {"insta_saver_placeholder": "insert_rejected", "sqlstate": "<SQLSTATE or unknown>"}
```

`sqlstate` is the SQLSTATE only if it matches `^[0-9A-Z]{5}$` (checked again right before the write);
otherwise, including for `PGRST102`, it is the fixed string `"unknown"`. `raw_payload` holds only this fixed
marker, never any part of the event. The worker's `parse()` raises
`UnsupportedPayload("insert_rejected")` for it (interfaces.md §1), so the row ends `failed` with
`unsupported_payload: insert_rejected` and shows up in the UI. A placeholder gets no background work (no media
copy, no ack DM).

**If the placeholder insert itself fails**, the table above does **not** apply as is. The placeholder body is
built by the receiver and known-good; only `message_mid` and `sender_id` come from the event. So a failure
whose cause can't be those two values is not about this input, and is never treated as permanent:

| Placeholder insert result | Outcome |
|---|---|
| A row is returned | handled (the original `insert_rejected: <code>` log line stays) |
| No row returned (`on conflict` on `message_mid`: an earlier delivery already stored this `mid`) | duplicate, absorbed: handled, nothing else logged |
| SQLSTATE class `23` (integrity, e.g. `23502` on `sender_id`) or class `54` (e.g. `54000`: the `mid` is too large to index) | **permanent**: log `placeholder_rejected: <SQLSTATE>`, count as handled. The event is lost and this log line is its only trace, so **every single** `placeholder_rejected` alerts (below) |
| Anything else: transient errors from the table above, **and** `PGRST102`, class `22` and any other code the table calls permanent | **transient**: log `placeholder_failed: <SQLSTATE \| PGRST code \| HTTP status \| exception class>`, the response is `500` so Meta redelivers. Why: a `PGRST102` or class `22` on a body the receiver built means the client or platform is broken for every request (e.g. an empty or truncated body), not that this input is bad; treating it as permanent would silently lose every share until someone notices |

The other events in the batch are unaffected either way (§6 "attempted independently"). Trade-off: if a
`mid` itself ever caused a class `22` error (not expected, Meta generates it), the event loops on Meta's
retries for up to 36 h and the `placeholder_failed` alert fires. That is accepted over a silent loss.

- **Post-upload write (M2 media copy):** after all attachments of a post were attempted, **one** update sets
  `media_path` and `error` together, conditional on `status = 'received'` — exact statement, zero-rows meaning
  and why it can't race the worker in [schema.md §3](schema.md#3-postsstatus-state-machine) (write
  conditions). Never one update per attachment: the worker may claim as soon as `media_path` is set.

## 7. Outbound calls (M2)

- The ack DM is sent only for a newly inserted, non-placeholder row, inside `waitUntil`, after the response.
- The Graph API token (`app_secrets.ig_access_token`) goes in an `Authorization: Bearer` header, never in a URL
  query string (`?access_token=` ends up in error messages and logs). Graph API support for the header with
  Instagram Login is checked in M2; if only the query form works, the request URL is never logged or
  included in an error.
- Media downloads follow the SSRF rules in storage.md §3 (M2 entry condition).

## 8. Logging

Allowed in logs: the HTTP status and outcome code, `pathname` (never the full URL — the handshake query
contains `hub.verify_token`), body byte length, counts per drop reason, number of rows inserted, inserted
`posts.id` values, exception class names, SQLSTATE codes, PostgREST `PGRST…` codes and the HTTP status of a
failed DB call.

Never logged: the raw or parsed body or any part of it (captions, CDN URLs, `mid`s, sender ids), request
headers (`X-Hub-Signature-256`, `Authorization`, `apikey`), the query string, any env value or token, and
database error messages, details or hints (they can echo row values — log the SQLSTATE only).

## 9. Deployment

- `verify_jwt = false` for **`ig-webhook` only**: `[functions.ig-webhook] verify_jwt = false` in
  `supabase/config.toml` (devops-engineer) and the matching per-function deploy flag in CI. Never a
  project-wide setting; every other function (e.g. `refresh-token`, M2) keeps its own auth, specified in its
  M2 contract.
- The service-role key is used only inside the function and never appears in a response or log.

## 10. Tests `receiver-engineer` must write (Deno, no network)

Inject env, a fake DB client and a fake `fetch`; every test also checks what the fakes recorded. Every
error-status test also asserts an **empty body**, and the whole suite asserts that no response carries an
`Access-Control-*` header.

| Rule | Test |
|---|---|
| Fail closed | each of the three variables unset / `""` / `"  "` → `GET` and `POST` both `500`, zero DB calls, zero fetches. `ALLOWED_SENDER_IDS` = `","`, `"abc"`, `"123,*"` → `500`. `META_VERIFY_TOKEN` of 31 characters → `500`; 32 → accepted; 31 characters plus a trailing space or newline → `500` |
| Trimmed secrets | `META_APP_SECRET="<secret>\n"`: a signature computed with key `<secret>` → `200`, one computed with `"<secret>\n"` → `403`. `META_VERIFY_TOKEN="  <token>\n"`: handshake with `<token>` → `200`; with `"  <token>\n"` (URL-encoded) → `403`. Trim is `String.prototype.trim()`: `META_VERIFY_TOKEN="<token>\u00a0\ufeff"` → handshake with `<token>` → `200`; `ALLOWED_SENDER_IDS="\u00a01000000000000001\t"` → that sender is allowed; a 31-character token plus `\u00a0` → `500` |
| Platform env | `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` unset / `""` → `GET` and `POST` `500`, empty body, zero DB calls, zero fetches |
| Config per request | one handler instance: request 1 with valid env → `200`; set `ALLOWED_SENDER_IDS=""` → request 2 → `500`; restore → request 3 → `200`. Same with a changed `ALLOWED_SENDER_IDS` value: request 2 uses the new list |
| Method | `PUT`, `HEAD`, `OPTIONS` (with `Origin` and `Access-Control-Request-Method`) → `405`, empty body, no `Access-Control-Allow-Origin` |
| Handshake | correct → `200`, body = challenge, `Content-Type: text/plain; charset=utf-8`, `X-Content-Type-Options: nosniff`; wrong token, token differing only in the last character, token differing only in length (the real token plus one character, and its first 31 characters), missing token, `hub.mode=unsubscribe`, missing challenge, 129-digit challenge, non-digit challenge → `403`; no DB call in any case |
| Content-Length | `Content-Length: abc`, `-1`, `""`, `10, 10` → `400`, body not read |
| Size | `Content-Length: 1048577` → `413` without reading the body; a chunked body of 1 MiB + 1 byte with no `Content-Length` → `413`; a body of exactly 1 MiB with a valid signature → processed |
| Signature | valid → `200`; header missing, prefix `sha1=`, 63 hex digits, non-hex, wrong digest → `403`, zero DB calls; a body containing `é` signed over its raw bytes → accepted, while the same signature checked against `JSON.stringify(JSON.parse(body))` would fail (proves raw bytes are hashed) |
| Order | invalid signature with an allowlisted sender in the body → zero DB calls, zero fetches |
| Echo | allowlisted sender with `is_echo: true` → not inserted; event with `sender.id === entry.id` and no `is_echo` → not inserted; both → `200` |
| Allowlist | unknown sender → not inserted, `200`; one batch with 2 entries and 3 events (allowed, echo, stranger) → exactly 1 insert; an entry whose `id` is allowlisted → nothing from it inserted, and the log contains `config_error: bot_id_allowlisted` |
| Shape | event without `message.mid` (e.g. a reaction) → not inserted, `200` |
| Body ignored | valid signature + invalid JSON, invalid UTF-8, or `object: "page"` → `200`, zero inserts |
| Dedupe | insert returns no row → no background work scheduled, `200` |
| Permanent rejection | batch of 3 accepted events, the 2nd insert fails with SQLSTATE `22P05` → `200`; events 1 and 3 inserted and get background work; a placeholder row for event 2 with `raw_payload` = exactly the marker; log has `insert_rejected: 22P05` and no DB error message. Same with a class `23` code (`23502`), a class `54` code (`54000`) and `22P02`. HTTP `400` with code `PGRST102` → `200`, placeholder with `"sqlstate": "unknown"`, log `insert_rejected: PGRST102`. Placeholder insert also failing (event 2 rejected with `22P05` first): with `23502` or `54000` → `200`, no row for event 2, log `placeholder_rejected: <code>`; with `PGRST102`, `22P05`, `08006` or a thrown network error → `500`, log `placeholder_failed: <code>`; in every case events 1 and 3 are still inserted and get background work, and no log line holds a DB error message. Placeholder insert returning no row (duplicate) → `200`, no `placeholder_*` log line |
| Lone surrogate (unit) | a signed body whose caption text contains the escape `\ud800` (raw bytes) → passes step 5; the event handed to the fake DB client is unchanged (the caption string still holds U+D800). Fake returns `22P02` → placeholder, log `insert_rejected: 22P02`; fake returns HTTP `400` `PGRST102` → placeholder; fake returns HTTP `400` `PGRST100` → transient, `500`, no placeholder |
| Lone surrogate (integration, test-engineer, `tests/integration/`, local `supabase start`, M1) | insert an event whose caption holds `\ud800` through the receiver's DB client against the pinned local stack; assert the **exact** observed outcome (expected `22P02`; or `PGRST102` if PostgREST rejects first) and that the receiver classifies it permanent and stores the placeholder. Record the observed code in the PR. If the stack stores the row instead (e.g. with U+FFFD), the test asserts that and no classification is needed. Same test with `\u0000` → expected `22P05` |
| Transient failure | batch of 3, the 2nd insert fails with each of: thrown network error, HTTP `503`, SQLSTATE `08006`, `40001`, `53300`, `57014`, `42P01`, `PGRST301`, `PGRST100` → `500`; events 1 **and 3** still inserted and get background work; no placeholder |
| Logging | capture all log output across the suite: it never contains the body, the signature value, `META_APP_SECRET`, `META_VERIFY_TOKEN`, a sender id, a `mid`, a query string or a DB error message |
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
- **Sustained failures (researcher, M1 spike checklist):** does Meta alert, throttle, flag or disable a
  webhook subscription after sustained non-`200` responses (e.g. hours of config `500`s after a typo in
  `ALLOWED_SENDER_IDS`), and how is it re-enabled? The research covers retries for up to 36 h only. Until
  answered, a config `500` is treated as an incident to fix within hours.
- **`hub.challenge` format:** digits-only per the research; confirm in the M1 spike.
