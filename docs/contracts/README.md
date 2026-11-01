# Contracts

Owned by `architect`. The interfaces every other agent builds against — agents coordinate through these
files, not through conversation.

| File | Contents | Status |
|---|---|---|
| `schema.md` | Tables, columns, statuses, indexes (mirrors `supabase/migrations/`) | M0.1 |
| `interfaces.md` | `Decider`, `VisionModel`, `Evidence`, `StageDecision`, `CascadeResult` | M0.1 |
| `api.md` | Local REST API: endpoints, JSON shapes, errors | M0.1 (skeleton) |
| `storage.md` | Storage bucket layout and lifecycle | M0.1 |
| `payloads.md` | Real (scrubbed) Instagram webhook payload shapes | M1 (after the spike) |

Rules:
- Minimal and testable: types, field names, error cases, one example each.
- Changing a contract after builders start requires an ADR in `docs/decisions/` and a note to `tech-lead`
  listing affected agents.
- Contract PRs merge into `dev` **before** the feature branches that depend on them start.
