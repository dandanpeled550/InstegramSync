# Contracts

Owned by `architect`. The interfaces every other agent builds against — agents coordinate through these
files, not through conversation.

| File | Contents | Status |
|---|---|---|
| [`schema.md`](schema.md) | Tables, columns, statuses + transitions, indexes, RLS, migration rules (mirrors `supabase/migrations/`) | v0.1 (M0.1b) |
| [`interfaces.md`](interfaces.md) | `Post`, `Decider`, `VisionModel`, `Evidence`, `StageDecision`, `CascadeResult`, `Titler`, policy, `run_worker` | v0.1 (M0.1b); repo/storage signatures before M3 |
| [`api.md`](api.md) | Local REST API: endpoints, JSON shapes, errors | v0.1 (M0.1b) |
| [`storage.md`](storage.md) | Storage bucket, path layout, access, lifecycle | v0.1 (M0.1b) |
| [`receiver.md`](receiver.md) | `ig-webhook` security rules: fail closed on empty secrets/allowlist, body size cap, HMAC over the raw body, handshake, per-event filter order, echo rule, dedupe, logging, `verify_jwt`, required tests | v0 (M0.1b) — **binding from the M1 receiver v0** |
| `payloads.md` | Real (scrubbed) Instagram webhook payload shapes (attachment types, reel/carousel keys, `unsupported_payload` reasons, observed body sizes) | M1 (after the spike) |

Rules:
- Minimal and testable: types, field names, error cases, one example each.
- Changing a contract after builders start requires an ADR in `docs/decisions/` and a note to `tech-lead`
  listing affected agents.
- Contract PRs merge into `dev` **before** the feature branches that depend on them start.

Deviations from PLAN.md not covered by an ADR (each one is what PLAN intends, stated precisely):
- The receiver insert includes `sender_id` (PLAN §1 omits it; PLAN §6 declares it `not null`).
- The worker recovers stuck rows **before** claiming (PLAN §2 lists the claim first).
- `Decider.decide(evidence)` takes the `Evidence` value, not `evidence.as_text()`.
- `fallback_title` also strips @mentions.
