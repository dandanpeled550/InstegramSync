# 0002 — Staged analysis cascade with Jev decisions behind protocols

- Status: accepted
- Date: 2026-11-01
- Deciders: product owner (PLAN.md v2/v3) for the cascade, rubric and thresholds (1–5, 8); architect
  (proposed in PR #4) for categories-as-`str` (6) and the `policy.py` placement (7)

## Context
- Many shared posts are categorizable from the caption alone; others ("wait for it 😱") need the media.
  Video analysis costs ~4× a short peek and much more than a caption call (PLAN §2).
- "Categorized" isn't enough: food posts are only useful with the recipe, travel posts with the place
  (informativeness rubric, PLAN §3).
- Jev (TypeSafe AI) is early-access; its question types (bool / choice / score-with-criteria) come from a
  third-party description and are **unverified**. Vision vendor choice (Gemini Flash vs. Claude Haiku) is open
  (PLAN §11 Q1).
- Captions, transcripts and on-screen text are attacker-controllable input that flows into prompts, stored
  titles and the UI.

## Decision
1. **Cascade:** Stage 0 pre-check (strip hashtags/emojis/@mentions; < ~15 chars ⇒ skip Stage 1) →
   Stage 1 caption → Stage 2 peek (cover image, or first `PEEK_SECONDS` of a reel) → Stage 3 full (whole reel
   with audio, or all carousel images; single photos skip it). Stop at the first stage where `should_stop` is
   true; otherwise `needs_review`.
2. **Evidence accumulates** and the decider always sees all of it. Evidence is an immutable value persisted as
   versioned JSON in `posts.evidence`, so runs can be replayed and evaluated.
3. **Per-stage decision = three answers** (`category` + confidence, `relevant`, `informativeness` 0–3) in
   `StageDecision`; `should_stop` requires confidence ≥ 0.8, relevant, informativeness ≥ the category's
   requirement (food 3, travel 2), and agreement with vision's `suggested_category` when present.
4. **Vision is caption-blind and category-neutral**, so its `suggested_category` is an independent signal for
   the cross-check. Disagreement never stops early; at the last stage it yields `needs_review`
   (`cross_check_mismatch`).
5. **Swappable vendors:** all model calls go through `Decider` (`JevDecider`), `VisionModel` (Gemini Flash by
   default) and `Titler`, owned by ai-engineer. Adapters own retries and raise `DeciderError` / `VisionError`;
   the worker marks the post `failed`. Title failures fall back to `fallback_title` and never fail a post.
6. **Categories are data** (`categories` table), typed as `str` slugs in code, validated at run time.
7. **Thresholds, rubric and `should_stop` live in `backend/app/decide/policy.py` (ai-engineer)**: they are
   AI behavior and change only with an eval report. `config.py` (pipeline-engineer) keeps runtime settings
   (batch size, timeouts, env vars). The sources disagree: PLAN §3 puts thresholds in `config.py` and the
   rubric in `decide/rubric.py`; AGENTS_PLAN §4.7 puts rubric + thresholds in `decide/policy.py`; AGENTS_PLAN
   §4.6 lists `should_stop` among pipeline-engineer's pure functions. This follows AGENTS_PLAN §4.7 for
   thresholds and rubric, and departs from §4.6 for `should_stop` (it stays pure; the cascade calls it).
   There is no `decide/rubric.py`.
8. **Retry after media deletion** reuses stored vision outputs (`reused: true`) and recomputes decisions.

## Alternatives considered
| Option | Why not |
|---|---|
| Always analyze full media | ~4× cost and latency on posts the caption already settles |
| One multimodal LLM call per post (category + title + everything) | No early exit; no per-stage evidence for evals; harder to tune per category |
| Structured-output LLM instead of Jev | Kept as the fallback behind `Decider` if Jev access or question types don't work out — not first choice because the plan targets Jev |
| Give vision the caption | Higher-quality descriptions, but the cross-check would no longer be independent |
| `Literal["food","travel"]` category type | Adding a category would need code changes everywhere; categories are already a table |
| Thresholds in `config.py` | Mixes eval-gated AI behavior with runtime settings and splits ownership |

## Consequences
- Easier: cheap posts stay cheap; `decided_at_stage`, confidence, informativeness and per-call `Usage` are
  logged for evals; vendors swap in one file; deterministic `should_stop` / `precheck` / `parse` are unit-testable.
- Harder: up to three decider calls per post; the evidence JSON is a versioned format that needs care; Jev's
  real API may force a `JevDecider` redesign (contained behind `Decider`).
- Unverified, routed to `researcher` via tech-lead: Jev question types and whether "choice" returns a
  confidence; Gemini clip offsets / fps / pricing; whether carousel payloads include all images (M1).
- Contracts: `interfaces.md` (all of it), `schema.md` (`evidence`, decision columns).
- Agents: ai-engineer (adapters, policy, titles, evals), pipeline-engineer (cascade, precheck, evidence),
  web-engineer (`review_reason`, `manual_override`).
