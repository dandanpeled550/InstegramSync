# Interfaces contract — v0

- Version: v0.1 (M0.1b) · 2026-11-01 · owner: `architect` — v0.1: `PERMALINK_RE.fullmatch`, no `RUBRIC`
  default, `no_evidence` ⇔ empty `stages`, partial listing = no media; round 2: `parse()` maps the
  receiver's placeholder to `UnsupportedPayload("insert_rejected")`
- Source: [PLAN.md §2–§5](../PLAN.md), [ADR 0002](../decisions/0002-staged-cascade-with-jev.md).
- The Python below is the **contract** (names, fields, types, docstrings, error behavior). Builders implement
  it in the modules named; bodies shown as `...` are theirs to write.

## 0. Conventions

- Python 3.12, fully typed (`mypy --strict`-clean). Value types are `@dataclass(frozen=True, slots=True)` from
  the standard library — the domain layer has no third-party dependency. Adapters may use pydantic (or the
  vendor SDK's schema types) **internally** to validate model output, then return these dataclasses.
- Every model call is `async`.
- All text that originates from Instagram (caption, transcript, on-screen text, and anything a model derived
  from them, including titles) is **untrusted data**. Adapters delimit it as data in prompts and validate
  outputs; the UI renders it as plain text. The detailed prompt-injection limits for adapters (no tools,
  function calling, grounding or URL fetching; unknown `suggested_category` coerced to `None`; length caps on
  `VisionResult` text; control/bidi characters stripped from titles) are added to this contract before the
  M3/M4 adapters are built.
- Categories are **data** (`categories` table), so category values are typed `str` (a `Category.slug`), not
  `Literal["food","travel"]`. Validation happens at run time against the loaded categories.
- `PLAN.md` calls the decision type `Decision` in one sketch; its name is `StageDecision`.

### Module map (no import cycles)

| Module | Owner | Defines |
|---|---|---|
| `backend/app/db/models.py` | data-engineer | `PostStatus`, `PostKind`, `Post` |
| `backend/app/decide/types.py` | ai-engineer | `Category`, `Usage`, `StageDecision`, `MediaItem`, `VisionResult`, `ModelError`, `DeciderError`, `VisionError` |
| `backend/app/analyze/evidence.py` | pipeline-engineer | `StageName`, `StageNumber`, `StageRecord`, `Evidence`, `ReviewReason`, `CascadeResult` |
| `backend/app/decide/base.py` | ai-engineer | `Decider` protocol |
| `backend/app/decide/policy.py` | ai-engineer | thresholds, `RUBRIC`, `should_stop` (PLAN §0's `decide/rubric.py` is folded in here — there is no `rubric.py`) |
| `backend/app/analyze/vision.py` | ai-engineer | `VisionModel` protocol (+ the Gemini adapter) |
| `backend/app/enrich/title.py` | ai-engineer | `Titler` protocol, `fallback_title`, `TITLE_MAX_CHARS` |
| `backend/app/ingest/parser.py` | pipeline-engineer | `PERMALINK_RE`, `ParsedPayload`, `UnsupportedPayload`, `parse` |
| `backend/app/process.py` | pipeline-engineer | `RunSummary`, `run_worker` |

Import direction: `db/models` and `decide/types` import nothing from `app`; `analyze/evidence` imports
`decide/types`; everything else may import those three.

## 1. Posts — `db/models.py`, `ingest/parser.py`

```python
# backend/app/db/models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping
from uuid import UUID

PostStatus = Literal["received", "analyzing", "done", "needs_review", "failed"]
PostKind = Literal["post", "carousel", "reel"]


@dataclass(frozen=True, slots=True)
class Post:
    """A `posts` row as claimed by the worker (see schema.md §2.2).

    The repo builds a Post from the claimed row's columns up to and including `evidence` only. The fields
    after `evidence` are always None straight after the claim (also on a retry, even though the row still
    holds the previous run's values); the worker fills them from `parse(raw_payload)`
    (`dataclasses.replace(post, kind=..., ...)`).
    """

    id: UUID
    message_mid: str
    sender_id: str
    status: PostStatus
    raw_payload: Mapping[str, Any]
    created_at: datetime
    claimed_at: datetime | None
    media_path: str | None  # "{id}/" or None — storage.md §2
    # previous run's evidence JSON (non-None on retry)
    evidence: Mapping[str, Any] | None
    kind: PostKind | None = None
    ig_media_id: str | None = None
    permalink: str | None = None
    caption: str | None = None
```

```python
# backend/app/ingest/parser.py
PERMALINK_RE: re.Pattern[str] = re.compile(
    r"^https://www\.instagram\.com/(p|reel)/[A-Za-z0-9_-]+/?$"
)
# Always applied with PERMALINK_RE.fullmatch(value) — never .match()/.search(), because `$` also matches
# before a trailing "\n". Widening it (e.g. after the M1 spike) is a contract change. The SPA applies the
# same check before rendering a permalink as a link (api.md), with a regex that has no `m` flag.


@dataclass(frozen=True, slots=True)
class ParsedPayload:
    """Typed fields extracted from one webhook `messaging` event. All payload knowledge lives in parser.py."""

    kind: PostKind
    ig_media_id: str | None
    # None unless it fully matches PERMALINK_RE — derivation verified in M1
    permalink: str | None
    caption: str | None  # as found; no cleaning
    attachment_count: int  # >= 1


class UnsupportedPayload(ValueError):
    """The event is not a shared post/carousel/reel (e.g. plain text DM, story reply).

    `reason` is a short machine-readable code, e.g. "no_attachment", "unsupported_type".
    The worker marks the post `failed` with error f"unsupported_payload: {reason}".
    """

    reason: str


def parse(raw_payload: Mapping[str, Any]) -> ParsedPayload:
    """Pure function; no I/O. Raises UnsupportedPayload; never returns partial garbage.
    Exact payload shapes: payloads.md (M1).

    Checked first: if raw_payload has the key "insta_saver_placeholder" (the receiver's
    placeholder for an event Postgres rejected, receiver.md §6), raise
    UnsupportedPayload("insert_rejected"), whatever else the mapping contains."""
    ...
```

## 2. Model I/O types — `decide/types.py`

```python
@dataclass(frozen=True, slots=True)
class Category:
    """A row of `categories`. Loaded once per worker run and passed to adapters' constructors."""

    id: int
    slug: str  # "food"
    label: str  # "Food"


@dataclass(frozen=True, slots=True)
class Usage:
    """Cost/latency record for one model call; stored in evidence for evals."""

    provider: str  # "jev" | "gemini" | ...
    model: str  # e.g. "gemini-2.5-flash"
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class StageDecision:
    """Answer to the three per-stage questions (PLAN §3).

    Invariants (checked in __post_init__, ValueError on violation):
      0.0 <= confidence <= 1.0;  0 <= informativeness <= 3;  category non-empty.
    """

    category: str  # a Category.slug — the decider's best choice
    confidence: float  # confidence in `category`
    relevant: bool  # is the text about this post (not promo / CTA / giveaway)?
    informativeness: int  # rubric score 0–3 for `category` (PLAN §3 table)
    usage: Usage | None = None


@dataclass(frozen=True, slots=True)
class MediaItem:
    """One stored attachment, downloaded by the pipeline to a local temp file before vision runs."""

    index: int  # 0-based attachment order (storage.md §2)
    path: Path  # local file; deleted by the pipeline after the post finishes
    mime_type: str  # "image/jpeg", "video/mp4", ...
    kind: Literal["image", "video"]


@dataclass(frozen=True, slots=True)
class VisionResult:
    """Category-neutral, fact-rich description of media (PLAN §2 Rules).

    Text fields are None when absent (never ""). `transcript` is only produced in mode="full" for video.
    `suggested_category` is a Category.slug or None when the model can't tell.
    """

    description: str
    on_screen_text: str | None = None
    transcript: str | None = None
    dish_or_place: str | None = None
    location_hint: str | None = None
    language: str | None = None  # BCP-47 primary tag, e.g. "he", "en"
    suggested_category: str | None = None
    usage: Usage | None = None


class ModelError(Exception):
    """Base for adapter failures, raised only after the adapter's own retries are exhausted.

    `retryable` = True for transient causes (timeout, 429, 5xx), False otherwise (bad request,
    invalid/unsafe output, unknown category). The message is short adapter-written text (e.g.
    "timeout after 3 attempts") and is stored in `posts.error` (schema.md §3.1): it never contains API
    keys, signed URLs, model output or post content.
    """

    retryable: bool


class DeciderError(ModelError): ...


class VisionError(ModelError): ...
```

## 3. `Decider` — `decide/base.py`

```python
class Decider(Protocol):
    """Answers category / relevant / informativeness for the evidence so far. Implementation: JevDecider.

    Construction (not part of the protocol): `JevDecider(categories: Sequence[Category], ...)`.
    """

    async def decide(self, evidence: Evidence) -> StageDecision:
        """Decide on ALL accumulated evidence (never only the newest stage).

        - Returns a StageDecision whose `category` is one of the constructor's category slugs.
        - Low confidence / not relevant / uninformative are normal answers, not errors.
        - Raises DeciderError on failure (after internal retries). Never returns a default/guess on failure.
        - No side effects besides the API call; safe to call concurrently for different posts.
        """
        ...
```

## 4. `VisionModel` — `analyze/vision.py`

```python
class VisionModel(Protocol):
    """Describes media for Stages 2–3. Default implementation: Gemini Flash (PLAN §4).

    Construction: `GeminiVision(categories: Sequence[Category], ...)`.
    The model sees only the media — not the caption — so its suggested_category is an independent
    signal for the cross-check (ADR 0002).
    """

    async def describe(
        self, media: Sequence[MediaItem], *, mode: Literal["peek", "full"]
    ) -> VisionResult:
        """
        mode="peek" (Stage 2): the caller passes only the cover item (media[0]). For a video, analyze only
                    the first policy.PEEK_SECONDS at low fps (clip offsets — no ffmpeg); no transcript.
        mode="full" (Stage 3): the caller passes all items. Video: whole clip incl. audio → transcript.
                    Images: all of them in one call.
        Raises VisionError (after internal retries); ValueError if `media` is empty.
        """
        ...
```

## 5. Policy — `decide/policy.py`

Thresholds, the rubric and `should_stop` are AI behavior and change only with an eval report, so they live
with `ai-engineer` (ADR 0002). PLAN §3 puts thresholds in `config.py` and the rubric in `decide/rubric.py`;
AGENTS_PLAN §4.6 lists `should_stop` among pipeline-engineer's pure functions; AGENTS_PLAN §4.7 puts rubric
and thresholds in `decide/policy.py`. This contract puts all three in `decide/policy.py`. `should_stop` stays
a pure function, which the cascade (pipeline-engineer) calls.

```python
# category slug → score 0–3 → criterion text (PLAN §3 table); used by JevDecider's informativeness
# question. No default: JevDecider.__init__ raises ValueError if a loaded category has no RUBRIC entry,
# so run_worker fails before claiming anything (a config error, not a per-post failure).
# tests/ai asserts RUBRIC covers the slugs in schema.md §2.1.
RUBRIC: Mapping[str, Mapping[int, str]]
CATEGORY_CONFIDENCE_MIN: float = 0.8
REQUIRED_INFO: Mapping[str, int] = {"food": 3, "travel": 2}
REQUIRED_INFO_DEFAULT: int = 3  # for a category slug missing from REQUIRED_INFO
PEEK_SECONDS: int = 10


def should_stop(decision: StageDecision, evidence: Evidence) -> bool:
    """Pure. True iff the cascade can stop at the current stage:
    decision.confidence >= CATEGORY_CONFIDENCE_MIN
    and decision.relevant
    and decision.informativeness >= REQUIRED_INFO.get(decision.category, REQUIRED_INFO_DEFAULT)
    and evidence.suggested_category in (None, decision.category)     # vision cross-check
    """
```

## 6. Evidence — `analyze/evidence.py`

```python
StageName = Literal["caption", "peek", "full"]
StageNumber = Literal[1, 2, 3]  # Stage 0 (pre-check) is not recorded as a stage
ReviewReason = Literal["below_threshold", "cross_check_mismatch", "no_evidence"]


@dataclass(frozen=True, slots=True)
class StageRecord:
    stage: StageNumber
    name: StageName  # 1="caption", 2="peek", 3="full"
    vision: VisionResult | None  # None for stage 1
    decision: StageDecision | None  # None until decide() returned
    # vision copied from the previous run's evidence (retry, media gone)
    reused: bool = False


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything known about a post so far. Immutable: each step returns a new Evidence.

    caption: raw caption (or None). clean_caption: after Stage 0 pre-check (hashtags/emojis/@mentions
    stripped); None when the pre-check decided the caption is too short (< ~15 chars) → Stage 1 skipped.
    """

    caption: str | None
    clean_caption: str | None
    stages: tuple[StageRecord, ...] = ()

    def with_vision(
        self, stage: StageNumber, vision: VisionResult | None, *, reused: bool = False
    ) -> "Evidence":
        """Append a new StageRecord (name derived from `stage`). Stages must be strictly increasing."""

    def with_decision(self, decision: StageDecision) -> "Evidence":
        """Attach `decision` to the last StageRecord. ValueError if there is none or it already has one."""

    @property
    def suggested_category(self) -> str | None:
        """suggested_category of the most recent stage that has vision; None if no vision yet."""

    @property
    def latest_decision(self) -> StageDecision | None: ...
    def as_text(self) -> str:
        """Deterministic plain-text rendering of all evidence (caption + every stage's vision fields),
        labeled by source. Adapters may use it or their own delimited rendering."""

    def to_json(self) -> dict[str, Any]:
        """The `caption`/`clean_caption`/`stages` part of the evidence JSON below (version 1).
        Generic: built with `dataclasses.asdict` (tuples become lists, None becomes null) — no per-field code."""

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Evidence":
        """Inverse of to_json; ValueError on unknown `version`. Generic: each nested dataclass
        (StageRecord, VisionResult, StageDecision, Usage) is built from the keys named by
        `dataclasses.fields(T)` — extra keys are ignored, missing keys take the field default, a missing
        key without a default raises ValueError."""


@dataclass(frozen=True, slots=True)
class CascadeResult:
    """Outcome of run_cascade(post). Invariants:
      needs_review is False ⇒ decision is not None, decided_at_stage is not None, review_reason is None
      needs_review is True  ⇒ review_reason is not None
      review_reason == "no_evidence" ⇔ decision is None ⇔ evidence.stages == () (no stage could run)
    decision / decided_at_stage are those of the LAST stage that ran.
    """

    decision: StageDecision | None
    evidence: Evidence
    decided_at_stage: StageNumber | None
    needs_review: bool
    review_reason: ReviewReason | None = None
```

Because serialization is generic, ai-engineer can add a field to `VisionResult`, `StageDecision` or `Usage`
without touching `analyze/evidence.py`. Rule: **every field added after v0 has a default**, so evidence
stored earlier still loads.

`review_reason` when no stage stopped: `cross_check_mismatch` if the last stage's vision
`suggested_category` disagrees with its decision, otherwise `below_threshold`. A single photo whose peek
doesn't stop is `below_threshold` (Stage 3 doesn't apply to it).

**Retry with media gone:** if the post has no stored media (`media_path` is `None`, the listing under it
is empty, or any listed object is "not found" — storage.md §4) and `post.evidence` holds vision for stage 2/3, the cascade reuses it
(`with_vision(..., reused=True)`) instead of calling `VisionModel`; decisions are always recomputed. With neither media nor stored vision, stages 2–3 are skipped.

**Errors:** `DeciderError` / `VisionError` propagate out of the cascade; the worker marks the post `failed`
with `error = f"{type(e).__name__}: {e}"` (truncated to 500 chars). Any other per-post exception is stored as
`error = f"internal_error: {type(e).__name__}"` — never its message; details go to local logs only. The
full list of codes is [schema.md §3.1](schema.md#31-postserror-codes). Media is kept for retry.

### Evidence JSON (`posts.evidence`)

Written by the worker with the result. `PATCH /api/posts/{id}` (api.md) changes exactly three keys: it sets
`needs_review` to `false`, `review_reason` to `null`, and **sets** (overwrites) `manual_override`.

```json
{
  "version": 1,
  "caption": "best gnocchi 😍 #food",
  "clean_caption": null,
  "stages": [
    {
      "stage": 2, "name": "peek", "reused": false,
      "vision": {
        "description": "Hands roll potato dough into small dumplings on a floured board.",
        "on_screen_text": "Nonna's gnocchi", "transcript": null,
        "dish_or_place": "potato gnocchi", "location_hint": null, "language": "en",
        "suggested_category": "food",
        "usage": {"provider": "gemini", "model": "gemini-2.5-flash", "input_tokens": 2100,
                  "output_tokens": 180, "cost_usd": 0.0011, "latency_ms": 2400}
      },
      "decision": {
        "category": "food", "confidence": 0.9, "relevant": true, "informativeness": 2,
        "usage": {"provider": "jev", "model": "jev", "input_tokens": null, "output_tokens": null,
                  "cost_usd": null, "latency_ms": 900}
      }
    }
  ],
  "decided_at_stage": 2,
  "needs_review": true,
  "review_reason": "below_threshold",
  "manual_override": null
}
```

`manual_override` when set: `{"category": "food", "previous_category": "travel" | null, "previous_review_reason":
"below_threshold" | null, "at": "2026-11-01T12:00:00Z"}` — only the latest override is kept; `previous_*`
record the row's category and `review_reason` just before this override (useful for evals).
Field rules: unknown keys are ignored by readers; `version` bumps only on breaking shape changes
(with an ADR); `null` (not missing) for absent optional values.

## 7. Titles — `enrich/title.py`

```python
TITLE_MAX_CHARS: int = 60  # also enforced by posts_title_length_check


class Titler(Protocol):
    """Short title from accumulated evidence; text-only call to the vision model's vendor (PLAN §5)."""

    async def title(self, evidence: Evidence, category: Category | None) -> str:
        """Returns a single-line title, 1..TITLE_MAX_CHARS chars (counted with `len()`, i.e. code points, as
        `char_length` does), trimmed, no hashtags/@mentions.
        Raises ModelError on failure — the caller then uses fallback_title(). A title failure never
        fails the post."""


def fallback_title(caption: str | None) -> str | None:
    """Pure. First sentence of the caption with emojis, hashtags and @mentions removed, whitespace
    collapsed, cut at a word boundary so that the result INCLUDING the trailing "…" (added if cut) is
    <= TITLE_MAX_CHARS code points.
    None if nothing remains. Example: "Crispy smashed potatoes 🥔. Boil, smash… #recipe" → "Crispy smashed potatoes"
    """
```

M3 has no LLM titles yet: the worker uses `fallback_title` only. M4 adds the `Titler`.

## 8. Worker entry — `process.py`

Used by the CLI (`python -m app.process`) and by `POST /api/process` (web-engineer calls it; it must not
re-implement the loop).

```python
@dataclass(frozen=True, slots=True)
class RunSummary:
    recovered: int  # rows moved analyzing → received at start
    claimed: int
    done: int
    needs_review: int
    failed: int
    dropped: int  # results discarded because the row changed meanwhile (schema.md §3)
    started_at: datetime
    finished_at: datetime


async def run_worker(*, batch_size: int | None = None) -> RunSummary:
    """Recover stuck rows, then claim and process batches until a claim returns no rows, then run the
    media cleanup sweep (storage.md §4). batch_size defaults to config.CLAIM_BATCH_SIZE (5).
    Per-post failures are recorded on the row and never raised. Raises only for infrastructure failures
    (DB unreachable, missing config) before or between batches. Safe to run concurrently with itself."""
```

## 9. Planned for M3 (not yet contract)

The repository (`db/repo.py`: recover, claim, conditional result/failed writes, category load) and storage
helpers (`db/storage.py`: list/download/delete under a prefix) get exact signatures in a contract update
**before** M3 builders start. Their semantics are already fixed by [schema.md §3](schema.md#3-postsstatus-state-machine)
and [storage.md §4](storage.md#4-lifecycle).

## 10. Open questions

- **Jev API (researcher):** whether Jev's "choice" question returns a confidence, and whether bool / choice /
  score-with-criteria exist as PLAN assumes (third-party description only). If confidence is unavailable,
  `JevDecider` must derive one or we switch to a structured-output LLM behind `Decider` — ADR either way.
- **Gemini clip offsets + fps + pricing (researcher):** assumed for `mode="peek"`; unverified.
- **`Category` home:** it is a `categories` row loaded by `db/repo.py` but defined in `decide/types.py`. That
  works (no cycle); moving it to `db/models.py` is a possible later cleanup, left as is in v0 because the
  type split is under review.
- **Carousel media in payloads (M1):** if payloads don't include all images, `mode="full"` for carousels sees
  only what's stored, and `attachment_count` semantics may change.
