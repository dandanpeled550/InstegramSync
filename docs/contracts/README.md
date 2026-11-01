# Contracts

Owned by `architect`. The interfaces every other agent builds against — agents coordinate through these
files, not through conversation.

| File | Contents | Status |
|---|---|---|
| [`schema.md`](schema.md) | Tables, columns, statuses + transitions, indexes, RLS, migration rules (mirrors `supabase/migrations/`) | v0 (M0.1) |
| [`interfaces.md`](interfaces.md) | `Post`, `Decider`, `VisionModel`, `Evidence`, `StageDecision`, `CascadeResult`, `Titler`, policy, `run_worker` | v0 (M0.1); repo/storage signatures before M3 |
| [`api.md`](api.md) | Local REST API: endpoints, JSON shapes, errors | v0 (M0.1) |
| [`storage.md`](storage.md) | Storage bucket, path layout, access, lifecycle | v0 (M0.1) |
| `payloads.md` | Real (scrubbed) Instagram webhook payload shapes, plus the receiver's security rules (fail closed on empty secrets/allowlist, HMAC over the raw body, per-event filter order, echo rule, handshake, no logging of bodies or tokens) | M1 (after the spike) — before receiver-engineer starts |

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
