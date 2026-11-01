# How do we set up a Meta app with Instagram Login so a Creator bot account receives DM webhooks (dev mode), and how long do tokens last?
- Answer: Create a **Business**-type Meta app, add the "Instagram API with Instagram Login" product, request
  `instagram_business_basic` + `instagram_business_manage_messages`, generate a token for the bot account in
  the dashboard (long-lived, 60 days), subscribe the account with
  `POST graph.instagram.com/v26.0/me/subscribed_apps?subscribed_fields=messages`, and register the callback URL
  + verify token in the dashboard. The bot must be an Instagram professional account (Creator or Business — no
  Facebook Page needed). Tokens last 60 days and are refreshed with `GET /refresh_access_token` once at least
  24 h old and not expired; unrefreshed tokens die at 60 days. Whether webhooks flow in *development mode* to
  accounts with an app role is not stated by Meta's pages I could read — community reports say yes for role
  holders only.
- Confidence: high for scopes, token lifetime/refresh and subscription call (official); medium for dev-mode
  webhook behaviour (official text says app must be "Live", community says roles work in dev mode); the exact
  dashboard click-path is unverified (UI changes often).
- Checked: 2026-11-01
- Sources:
  - Meta — [Instagram Login get started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started)
  - Meta — [Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)
  - Meta — [Set up Instagram webhooks](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup)
  - Meta — [Messaging API (Instagram Login)](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api)
  - Meta — [Instagram Platform overview](https://developers.facebook.com/documentation/instagram-platform/overview)
  - Meta — [Webhook fields and permissions](https://developers.facebook.com/documentation/instagram-platform/webhooks/fields)
  - Community (third-party): [n8n forum thread "Instagram DMs webhooks work only in test mode"](https://community.n8n.io/t/instagram-dms-webhooks-work-only-in-test-mode/176851),
    [Chatwoot self-hosted Instagram guide](https://developers.chatwoot.com/self-hosted/configuration/features/integrations/instagram-via-instagram-business-login.md),
    [JFBConnect Instagram setup](https://www.sourcecoast.com/jfbconnect/docs/social-network-applications/instagram-application-setup)

## Details

### Setup steps (official, condensed)
1. Bot Instagram account → switch to a **professional** account (Creator works; `account_type` returns
   `Business` or `Media_Creator`). No linked Facebook Page is required with Instagram Login.
2. developers.facebook.com → create app, type **Business** (other types cannot use the product).
3. App Dashboard → Instagram → **API setup with Instagram business login**.
4. Add the bot account (it needs a role on the app — Instagram Tester — and must accept the invite in
   Instagram: Settings → Apps and websites → Tester invites; this acceptance step is community-sourced).
5. Configure webhooks in the same dashboard section: callback URL
   (`https://<project>.supabase.co/functions/v1/ig-webhook`), verify token (= `META_VERIFY_TOKEN`); Meta sends
   the GET handshake (see `meta-webhooks.md`). Subscribe the `messages` field.
6. Click **Generate token** next to the account → log in as the bot → copy the token (long-lived, 60 days;
   the Business Login OAuth flow instead yields a 1-hour token to exchange). Store it in `app_secrets`.
7. Enable notifications per account (required, separate from the dashboard toggle):
```
POST https://graph.instagram.com/v26.0/me/subscribed_apps
     ?subscribed_fields=messages
Authorization: Bearer <IG user token>
→ {"success": true}
```
8. Verify: `GET https://graph.instagram.com/v26.0/me?fields=user_id,username` returns the bot's id.

### Scopes
| Scope | Why |
|---|---|
| `instagram_business_basic` | Profile/media reads; required by the webhooks setup and by token refresh |
| `instagram_business_manage_messages` | Receive `messages` webhooks and send DMs |
Old `business_*` scope names were deprecated 2025-01-27. Others (`..._content_publish`, `..._manage_comments`) are not needed.

### Access level and development mode
- Standard Access is the default and is intended for accounts you own/manage or that have roles on the app;
  Advanced Access (App Review + Business Verification) is needed for accounts you don't own. Our bot
  account is ours, so Standard should suffice — **for the single human sender too only if that sender has an
  app role** (community reports say non-role users' messages are not delivered in dev mode).
- Meta's webhooks page says the app "must be published or Live to receive notifications for app users". Community
  threads say that in dev mode, events triggered by users **with a role** (admin/developer/tester) do arrive.
  Our plan relies on the latter: give the personal sender account a role (Instagram Tester) and keep the
  app in development mode. If events do not arrive, the fallback is switching to Live for the own accounts
  (Live without App Review still limits to role users in practice; Meta states users without a role only get
  App-Review-passed features). Messaging permissions need review for general use — not for us.
- Unverified: whether the **sending** account must be an Instagram Tester or only a Facebook/app role.

### Token lifetime and refresh
| Token | Lifetime | How |
|---|---|---|
| Authorization code | 1 hour, single use | `instagram.com/oauth/authorize` |
| Short-lived | ~1 hour (stated for Business Login) | `POST api.instagram.com/oauth/access_token` |
| Long-lived | 60 days | `GET graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=…&access_token=…` (server-side only) |
| Dashboard "Generate token" | long-lived, 60 days | UI |
| Refresh | resets to 60 days | `GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=…` |

Refresh conditions: token at least 24 h old, not expired, `instagram_business_basic` granted. A token not
refreshed within 60 days expires and **cannot** be refreshed (re-generate in the dashboard). PLAN.md's rule
(refresh when < 10 days left, daily cron) fits. Expected response (from Meta's pattern; fields unverified in
this pass): `{"access_token": "…", "token_type": "bearer", "expires_in": 5184000}` → store `now()+expires_in`.

### Sending the ack DM
`POST https://graph.instagram.com/v26.0/me/messages` with Bearer token and body
`{"recipient":{"id":"<IGSID>"},"message":{"text":"Got it"}}`. Allowed only within 24 h of the user's last
message (standard window), which suits our immediate ack, but the later "Saved" DM after hours/days of
laptop-off delay **may fall outside the 24 h window** and fail. Flag for the worker design (M3/M4).

## Unverified / needs the M1 payload spike
1. Do webhooks arrive in development mode for a role-holding personal sender? (First thing to test.)
2. Exact dashboard labels and whether "Instagram Tester" is the correct role for the bot vs. the sender.
3. Whether the "Saved" DM after >24 h fails (and with which error), and whether a human-agent tag could help.
4. Exact refresh response shape and whether the dashboard-generated token refreshes identically.
5. Whether a Creator account behaves identically to Business for messaging webhooks.
