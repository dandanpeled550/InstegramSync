# Security policy

## Reporting a vulnerability

This repository does not use GitHub's private vulnerability reporting, and no personal contact details are
published here. To report a problem privately:

1. Open a **public** GitHub issue titled exactly **"Security contact request"**.
2. Put **nothing else of substance in it.** Do **not** include a description, proof of concept, affected
   file or function, logs, screenshots, tokens or any other detail of the problem. The issue is public and
   permanent; anything written there is disclosed to everyone.
3. The maintainer's public reply never contains an address. Instead the maintainer opens a **draft GitHub
   security advisory** on this repository and adds you to it as a collaborator (this works without private
   vulnerability reporting enabled). Share the details only there. The issue is then closed.

Replies are best effort, with no SLA. If there is no answer after 7 days, comment again on the same issue,
still without details.

Issues that contain vulnerability details may be edited or deleted by the maintainer, and those details
should be treated as already public.

### If a secret may be exposed

If you think a credential is exposed (for example a token in a commit), keep the title "Security contact
request" and write only **"possible exposed credential"** in the issue body. Do not paste the value, the
commit, the file path or where you found it. The maintainer rotates any credential that could be affected
first and collects details afterwards. Deleting the commit is not
enough: a secret that reached git is treated as compromised and is rotated.

## Scope

- The Supabase Edge Function receiver (webhook signature verification, sender filtering, media fetching).
- Secret handling (Instagram tokens, Supabase keys, model API keys).
- The local web UI's authentication.

## Design commitments

- Webhook event (POST) requests are rejected unless the `X-Hub-Signature-256` HMAC matches.
- Media is fetched only from an allowlist of Meta CDN hosts (`docs/contracts/storage.md` §3; exact SSRF rules
  are added there before M2).
- No secrets are stored in this repository; leaked secrets are rotated, not just removed.
- Captions and transcripts are treated as untrusted input to AI models.
