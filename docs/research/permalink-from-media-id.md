# Can a shared post's permalink / shortcode be derived from the media id in the webhook payload?
- Answer: **Not confirmed by any official source.** Meta documents `permalink` and `shortcode` fields on the
  IG Media node and a `GET /<IG_MEDIA_ID>` lookup, but the docs describe it for media the app user can access;
  nothing says the `ig_post_media_id` of *someone else's* post can be queried by our bot's token. Expect the
  lookup to fail or be restricted for other users' media, so the M1 spike must test it. Fallbacks: (a) decode a
  shortcode from the id if it is a classic numeric pk (community technique, unreliable for the 1800… ids),
  (b) keep the CDN URL + caption and let the UI say "no link", (c) ask the user to paste the link.
- Confidence: high that the fields exist and that the docs are silent on third-party media; low on actual
  behaviour (untested).
- Checked: 2026-11-01
- Sources:
  - Meta — [IG Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media)
  - Meta — [Post shares: new attachment type](https://developers.facebook.com/documentation/instagram-platform/webhooks/new)
  - Meta — [Messaging API (Instagram Login)](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api)
  - Meta — [Instagram Login get started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started)

## Details

### What the webhook gives us
`ig_post` attachment: `ig_post_media_id` (e.g. `18xxxxxxxxxxxxxxx`, 17–18 digit), `title` (caption), `url`
(signed CDN link). No permalink, no shortcode, no owner username. See `meta-webhooks.md`.

### Official lookup
```
GET https://graph.instagram.com/v26.0/<IG_MEDIA_ID>?fields=id,permalink,shortcode,media_type,username,caption
Authorization: Bearer <instagram user access token>
```
- The IG Media node lists `permalink`, `shortcode`, `media_type`, `media_product_type`, `username`, `owner`,
  `caption`, `timestamp`, `media_url`, `thumbnail_url`.
- Docs say the API returns data only for **professional accounts**, not personal ones. Fields documented as
  restricted for "media owned by others" are described for Business Discovery / hashtag / mentions / tags
  endpoints (e.g. `media_url` omitted for copyrighted audio or download-disabled reels; `username` returned
  instead of `owner`). That implies cross-account reads happen through those special endpoints, not through
  a plain `/<media_id>` read.
- `permalink` is not usable for carousel **child** photos (only the parent album).
- The Messaging API page says media/posts used in messages must be owned by the app user (that is about
  *sending* shares, not reading them).
- Instagram Login permission for reading media: `instagram_business_basic`.

### Ways it could still work (all untested)
1. `GET /<ig_post_media_id>?fields=permalink` with the bot token — works only if Meta lets the messaging
   context grant read access to shared media. Meta added the id specifically to enable such lookups
   (changelog: "media ID, URL, and title"), which is encouraging but not a documented guarantee.
2. Business Discovery (`/<bot_ig_id>?fields=business_discovery.username(<name>){media{permalink}}`) — needs the
   *username* of the post owner (not in the payload) and the owner must be a professional account. Not viable
   without the username.
3. Shortcode ↔ id relation (**community knowledge, unverified here**): a classic Instagram media pk is the
   shortcode read as base-64 (alphabet `A–Za–z0–9-_`). Messaging ids that start `17`/`18` and are ~17 digits
   are Graph "IG media ids" and have been reported to *not* equal the pk, so decoding would give a wrong
   link. Do not ship a decode without proving it on real payloads.

### Recommendation for M1
Spike: for a photo, a reel and a carousel shared from a *public professional* account and from a *personal*
account, try `GET /<id>?fields=permalink,shortcode,username,media_type` and record the HTTP status/error
code. Store the result in this file. Until proven, the data model keeps `permalink` nullable (it already is,
PLAN.md §6) and the UI hides "Open on Instagram" when null.

## Unverified / needs the M1 payload spike
1. Does `GET /<ig_post_media_id>?fields=permalink` succeed for another user's post? For personal accounts?
2. Does the `ig_reel` payload contain an id, and does the same lookup work for it?
3. Is the id for carousels the parent's or the first child's? (Child ids cannot return `permalink`.)
4. Relationship between messaging media ids and shortcodes.
5. Error codes returned on failure (to make the worker's fallback deterministic).
