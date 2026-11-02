# Security policy

## Reporting a vulnerability

This repository does not use GitHub's private vulnerability reporting, and no personal contact details are
published here. To report a problem privately:

1. Open a **public** GitHub issue titled exactly **"Security contact request"**.
2. Put **nothing else of substance in it.** Do **not** include a description, proof of concept, affected
   file or function, logs, screenshots, tokens or any other detail of the problem. The issue is public and
   permanent; anything written there is disclosed to everyone.
3. The maintainer replies in that issue with a private channel. The report moves there, and the issue is
   then closed.

Issues that contain vulnerability details may be edited or deleted by the maintainer, and those details
should be treated as already public.

### If a secret may be exposed

If you think a credential is exposed (for example a token in a commit), write only **"possible exposed
credential"** in the issue. Do not paste the value, the commit, the file path or where you found it. The
maintainer rotates the credential first and collects details afterwards. Deleting the commit is not
enough: a secret that reached git is treated as compromised and is rotated.

## Scope

- The Supabase Edge Function receiver (webhook signature verification, sender filtering, media fetching).
- Secret handling (Instagram tokens, Supabase keys, model API keys).
- The local web UI's authentication.

## Design commitments

- Webhook requests are rejected unless the `X-Hub-Signature-256` HMAC matches.
- Media is intended to be fetched only from an allowlist of Meta CDN hosts (planned for the receiver in M2;
  the exact rules will be recorded in `docs/contracts/` and are not yet specified).
- No secrets are stored in this repository; leaked secrets are rotated, not just removed.
- Captions and transcripts are treated as untrusted input to AI models.
