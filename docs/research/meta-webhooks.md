# What do Instagram messaging webhooks look like when a user shares a post / reel to the bot?
- Answer: Shares arrive in the `messages` field as `entry[].messaging[].message.attachments[]`. Posts use
  `type: "ig_post"` (legacy `type: "share"` is being removed), reels use `type: "ig_reel"`. `ig_post` carries
  `ig_post_media_id`, `title` (the caption) and `url` (a signed CDN "lookaside" URL, not the post link).
  Echoes carry `message.is_echo: true` and must be dropped. Meta signs every POST with `X-Hub-Signature-256`
  (`sha256=` + HMAC-SHA256 of the raw body with the App Secret). GET handshake: check `hub.verify_token`, reply
  with the `hub.challenge` value. Failed deliveries are retried for up to 36 hours, so dedupe on `message.mid`.
- Confidence: high for the overall structure, signature, handshake, retries and echo filter (official docs);
  medium for `ig_post` / `ig_reel` exact field sets (official `ig_post` sample exists; the official `ig_reel`
  sample shows only `url`); low for carousels (nothing documented).
- Checked: 2026-11-01
- Sources:
  - Meta — [Instagram post shares: new attachment type](https://developers.facebook.com/documentation/instagram-platform/webhooks/new)
  - Meta — [Webhook examples](https://developers.facebook.com/documentation/instagram-platform/webhooks/examples)
  - Meta — [Set up Instagram webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup)
  - Meta — [Webhooks overview](https://developers.facebook.com/documentation/instagram-platform/webhooks)
  - Meta — [Webhook fields and permissions](https://developers.facebook.com/documentation/instagram-platform/webhooks/fields)
  - Meta — [Instagram Messaging changelog](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog/)
  - Meta — [Messaging API (Instagram Login)](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api)

## Details

### Envelope (all events)
`object` is `"instagram"`; `entry[].id` is the bot account's Instagram user id; `entry[].messaging[]` holds
the events. For received messages `recipient.id` is the bot and `sender.id` is the user's Instagram-scoped id
(IGSID). Batches may hold several events and up to 1,000 updates — process every item individually.

### Shared post (current shape, from Meta's docs; values are fake)
```json
{
  "object": "instagram",
  "entry": [{
    "id": "17841000000000000",
    "time": 1700000000000,
    "messaging": [{
      "sender":    { "id": "SENDER_IGSID" },
      "recipient": { "id": "17841000000000000" },
      "timestamp": 1700000000000,
      "message": {
        "mid": "MESSAGE_MID",
        "attachments": [
          { "type": "ig_post",
            "payload": {
              "ig_post_media_id": "18000000000000000",
              "title": "Caption text of the shared post",
              "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18000000000000000&signature=PLACEHOLDER" } }
        ]
      }
    }]
  }]
}
```
- Timeline (official): from 2025-11-03 post shares carried **both** `share` and `ig_post`; `share` was to be
  supported until 2026-02-01, and the changelog (entry dated 2026-04-27; a search snippet cited 2026-05-06 as the rollout date) says `share` is now being removed
  gradually from post-share payloads. Meta says new integrations must support `ig_post`. The parser should
  accept `ig_post` first and fall back to `share` (old shape: `payload.url` only).
- The `url` is a signed `lookaside.fbsbx.com` CDN link; PLAN.md already assumes it may expire — download early.
  Meta's `ig_post` sample shows the media id inside the CDN URL's `asset_id` parameter.

### Shared reel
Meta's example shows `{"type":"ig_reel","payload":{"url":"<URL_FOR_REEL_MEDIA>"}}`. A search summary of the
changelog says `ig_reel` payloads include `title`, `url` and a video id (analogous to `ig_post`), but the
exact key name for the id was not found in official text — **unverified**. Do not hard-code `ig_post_media_id`
for reels; read whichever `*_id` key the real payload has (M1 spike). Also note a `reel` type exists for
reels in other contexts; handle `ig_reel`, `reel`, `video` defensively.

### Other attachment types listed in Meta's examples
`image`, `video`, `audio`, `file`, `media`, `story_mention`, `story`, `ig_story`, `reel`. `message.is_unsupported:
true` marks unsupported media. A message may contain multiple attachments (array). `message.reply_to` appears
on replies (since 2025-12-19).

### Echoes
Messages sent by the bot (including our "Got it" DM) come back as a `messages` event with
`message.is_echo: true`, `sender.id` = bot id, `recipient.id` = the user. Filter: drop if `message.is_echo`
**or** `sender.id === entry.id`. (Meta's field matrix also lists a separate `message_echoes` field for
Instagram Login; we simply don't subscribe to it.)

### Handshake (GET)
Query params `hub.mode` (always `subscribe`), `hub.verify_token` (must equal the token typed in the App
Dashboard) and `hub.challenge` (integer). Validate the token, respond `200` with the challenge value as the
body. In Deno read them via `new URL(req.url).searchParams.get("hub.challenge")` (the dot is literal; the
PHP underscore rewrite does not apply).

### Signature (POST)
Header `X-Hub-Signature-256: sha256=<hex>`; HMAC-SHA256 over the payload with the App Secret. Meta calls
validation optional but recommended; we require it. Compute over the **raw request bytes** (read the body as
text/arrayBuffer once, verify, then `JSON.parse`) and compare in constant time. Community note (third-party,
widely reported, not in the Instagram docs page I could read): Meta escapes non-ASCII characters as `\uXXXX`
in the signed body, so re-serializing parsed JSON breaks the signature — another reason to use raw bytes.

### Retries and delivery
Respond `200` promptly. On failure Meta retries immediately and then at decreasing frequency for up to 36
hours, then drops the event. Duplicates are expected → `ON CONFLICT (message_mid) DO NOTHING`. There is no
historical store of webhook events, so the raw payload must be saved on receipt.

### Permissions / subscription
`messages` field with Instagram Login requires `instagram_business_basic` + `instagram_business_manage_messages`.
Meta states the app must be **Live** to receive notifications for app users; see
`instagram-login-setup.md` for what that means in development mode.

### Limitations that affect us
- "Webhooks include only the URL for a shared media item or post" (Messaging API page) — no permalink, owner or
  full media list is promised.
- Webhook delivery is not guaranteed; the Conversations API cannot fully back it up (PLAN.md §10).

## Unverified / needs the M1 payload spike
1. Exact `ig_reel` payload keys (is there a media/video id? is `title` the caption?).
2. What the reel `url` points to: playable MP4 on a CDN vs. a page/thumbnail. Check Content-Type and whether
   it needs auth and how long it lives.
3. Whether a shared **carousel** arrives as one `ig_post` (likely cover only), several attachments, or a
   different type. No official text covers carousels.
4. Whether `share` and `ig_post` both still appear for our app at the time of the spike (gradual rollout).
5. Whether `title` is truncated for long captions.
6. Whether the CDN URL is fetchable without headers from Supabase's servers and its expiry.
7. Shape of echo events for the bot's own DMs under Instagram Login (confirm `is_echo` appears in `messages`).
8. Whether the signature really needs the raw (unicode-escaped) body in practice.
