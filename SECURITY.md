# Security policy

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** ("Report a vulnerability" under the Security tab).
Don't open a public issue for security problems.

## Scope

- The Supabase Edge Function receiver (webhook signature verification, sender filtering, media fetching).
- Secret handling (Instagram tokens, Supabase keys, model API keys).
- The local web UI's authentication.

## Design commitments

- Webhook requests are rejected unless the `X-Hub-Signature-256` HMAC matches.
- Media is fetched only from an allowlist of Meta CDN hosts.
- No secrets are stored in this repository; leaked secrets are rotated, not just removed.
- Captions and transcripts are treated as untrusted input to AI models.
