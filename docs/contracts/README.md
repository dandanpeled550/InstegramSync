# Contracts

Owned by `architect`. The interfaces every other agent builds against — agents coordinate through these
files, not through conversation.

| File | Contents | Status |
|---|---|---|
| [`schema.md`](schema.md) | Tables, columns, statuses + transitions, indexes, RLS, migration rules (mirrors `supabase/migrations/`) | v0 (M0.1) |
| [`interfaces.md`](interfaces.md) | `Post`, `Decider`, `VisionModel`, `Evidence`, `StageDecision`, `CascadeResult`, `Titler`, policy, `run_worker` | v0 (M0.1); repo/storage signatures before M3 |
| [`api.md`](api.md) | Local REST API: endpoints, JSON shapes, errors | v0 (M0.1) |
| [`storage.md`](storage.md) | Storage bucket, path layout, access, lifecycle | v0 (M0.1) |
| `payloads.md` | Real (scrubbed) Instagram webhook payload shapes | M1 (after the spike) |

Rules:
- Minimal and testable: types, field names, error cases, one example each.
- Changing a contract after builders start requires an ADR in `docs/decisions/` and a note to `tech-lead`
  listing affected agents.
- Contract PRs merge into `dev` **before** the feature branches that depend on them start.
