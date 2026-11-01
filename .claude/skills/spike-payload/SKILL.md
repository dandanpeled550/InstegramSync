---
name: spike-payload
description: M1 helper — turn real Instagram webhook payloads captured by the receiver into scrubbed fixtures and a payloads contract. Use after the human has shared test posts to the bot.
---

# /spike-payload

Public repo: **no real data reaches git.** Raw payloads only ever live in gitignored `fixtures/raw/`.

1. **Human step:** ask the human to share one photo post, one carousel and one reel to the bot, then to
   export the latest `raw_payload` rows (Supabase dashboard → SQL editor) into `fixtures/raw/*.json`.
   Agents don't query the remote database.
2. Delegate to `test-engineer`: run `scripts/scrub-payload.py fixtures/raw/<file>.json` for each file →
   `fixtures/payloads/<kind>.json` with fake IDs, rewritten captions, fake media URLs, and the original
   structure preserved.
3. Delegate to `architect`: write `docs/contracts/payloads.md` from the scrubbed fixtures — field paths for
   `ig_post` / `ig_reel`, which fields are present per kind, and the answers to the M1 questions
   (permalink derivation, what the reel URL points to, whether carousels include all images).
4. `security-reviewer` reviews the fixtures PR before merge.
