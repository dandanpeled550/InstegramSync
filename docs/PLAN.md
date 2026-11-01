# Insta Saver — Build Plan (v3)

Share an Instagram post to a bot account by DM → the app categorizes it (food / travel), gives it a title,
and makes it searchable on a password-protected web page.

**Stack:** Supabase (Postgres, Storage, Edge Functions, pg_cron) · Python 3.12 + FastAPI worker & UI on the
laptop · Jev (TypeSafe AI) for decisions · Gemini Flash for vision (default — see §4) · Vite + React

**Changes in v3:** no always-on Python server. A tiny **Supabase Edge Function** receives webhooks 24/7 (free)
and stores the raw payload + media. The **laptop** runs the analysis pipeline and the UI on demand.
The database is the queue, so the same worker can move to the cloud later without code changes.

**v2 (kept):** staged analysis cascade — caption → peek → full video — that stops once the evidence is
relevant and informative enough for its category.

---

## 0. Architecture

```
IG app: Share → @your_bot (DM)
        │  webhook
        ▼
┌──────────── Supabase (free, always on) ─────────────┐
│ 1. RECEIVER — Edge Function `ig-webhook`            │
│    verify signature · filter · dedupe               │
│    INSERT posts (status=received, raw_payload)      │
│    copy media → Storage bucket `media`              │
│    DM "Got it 👍"                                    │
│                                                     │
│    Edge Function `refresh-token` (pg_cron, daily)   │
│                                                     │
│ 6. STORE — Postgres (posts, categories, app_secrets)│
│            Storage (media, deleted after processing)│
└───────────────────────▲─────────────────────────────┘
                        │ SQL + Storage API
┌───────────────────────┴──────── Laptop ──────────────────────────────┐
│ `python -m app.process`  (CLI · "Process now" button · launchd)      │
│   claim rows status=received                                         │
│   2. ANALYZE cascade ──► 3. DECIDE (Jev) ──► 4. ENRICH (title)       │
│   UPDATE posts (done | needs_review) · delete media · DM "Saved ✅"   │
│                                                                      │
│ `python -m app.serve`  → http://localhost:8000                       │
│   7. UI — FastAPI /api/* + Vite/React SPA                            │
└──────────────────────────────────────────────────────────────────────┘
```

```
insta-saver/
  supabase/
    functions/
      ig-webhook/index.ts      # receiver (Deno/TypeScript, ~60–80 lines)
      refresh-token/index.ts   # daily Instagram token refresh
    migrations/                # SQL schema (single source of truth)
  backend/app/
    config.py                  # thresholds, model names, env vars
    process.py                 # `python -m app.process` entry point
    serve.py                   # `python -m app.serve` entry point
    ingest/parser.py           # raw_payload → typed fields (all payload knowledge lives here)
    analyze/                   # cascade.py, precheck.py, media.py, vision.py
    decide/                    # base.py (Decider protocol), jev.py, rubric.py
    enrich/                    # title.py, search_text.py
    meta/client.py             # send DM (reads token from app_secrets)
    db/                        # repo.py, storage.py
    api/                       # posts.py, categories.py, process.py, auth.py
  frontend/                    # Vite + React
```

---

## 1. Receiver — Supabase Edge Function `ig-webhook`

Kept deliberately small and dumb: **store first, think later.** All parsing logic lives in Python.

| Concern | Implementation |
|---|---|
| Deploy | `supabase functions deploy ig-webhook --no-verify-jwt` — Meta doesn't send a Supabase JWT, so JWT checks must be off; the Meta signature check replaces it |
| `GET` | Meta handshake: check `hub.verify_token`, echo `hub.challenge` |
| `POST` | Verify `X-Hub-Signature-256` (HMAC-SHA256 with App Secret, Web Crypto API); reject on mismatch |
| Filters | Drop `is_echo` (bot's own replies); only accept senders in `ALLOWED_SENDER_IDS` |
| Store | `INSERT INTO posts (message_mid, raw_payload, status) … ON CONFLICT (message_mid) DO NOTHING` — dedupes Meta's double deliveries |
| Media | After responding `200`, download the attachment URL (signed, may expire) to Storage `media/{post_id}/…` via `EdgeRuntime.waitUntil(...)`; set `media_path` |
| Ack DM | "Got it 👍" via Send API, token read from `app_secrets` |
| Secrets | `supabase secrets set META_APP_SECRET=… META_VERIFY_TOKEN=… ALLOWED_SENDER_IDS=…` |

### `refresh-token` (scheduled)
Instagram-Login tokens last 60 days. A pg_cron job calls this function daily: if the token in `app_secrets`
expires within 10 days → `GET graph.instagram.com/refresh_access_token` → store the new token + expiry.
Runs even if the laptop is off for months.

---

## 2. Analyze — staged cascade (laptop worker)

`python -m app.process`:
1. **Claim work:** `UPDATE posts SET status='analyzing', current_stage=0 WHERE id IN (SELECT id FROM posts WHERE status='received' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 20) RETURNING *` — safe even if two runs overlap.
2. **Recover:** rows stuck in `analyzing` for > 30 min go back to `received`.
3. For each post: `parser.py` extracts fields from `raw_payload` → run cascade → enrich → update row →
   delete media from Storage → DM "Saved ✅ Food: *title*".

### Stages

| Stage | Input added | Cost | Applies to |
|---|---|---|---|
| **0. Pre-check** | Strip hashtags, emojis, @mentions. < ~15 chars left → skip to Stage 2 | free | all |
| **1. Caption** | caption text → Jev | ~free | all |
| **2. Peek** | Reels: first ~10s at low fps (Gemini clip offsets + fps — no ffmpeg). Photos/carousels: cover image | ~$0.001 | all |
| **3. Full** | Reels: whole video + audio (description + transcript + on-screen text). Carousels: all images (if payload has them — verify in M1). Single photo: skip → `needs_review` | ~$0.004 | reels, carousels |

Media is read from Supabase Storage (`media_path`), not from Instagram's CDN.

### Rules
- **Evidence accumulates** — each stage sends Jev everything so far, never only the newest piece.
- **Vision outputs are category-neutral and fact-rich:** `description`, `on_screen_text`, `transcript`
  (stage 3), `dish_or_place`, `location_hint`, `language`, `suggested_category`.
- **Cross-check (stages 2–3):** vision's `suggested_category` ≠ Jev's → don't stop; at Stage 3 → `needs_review`.
- **Log per post:** `decided_at_stage`, confidence, informativeness, each stage's output in `evidence`.

### Orchestrator sketch (`analyze/cascade.py`)

```python
async def run_cascade(post: Post) -> CascadeResult:
    evidence = Evidence(caption=post.caption)

    for stage in stages_for(post):            # [caption, peek, full] filtered by kind + precheck
        evidence = await stage.collect(post, evidence)    # adds vision output, returns accumulated
        decision = await decider.decide(evidence.as_text())
        if should_stop(decision, evidence):
            return CascadeResult(decision, evidence, decided_at_stage=stage.number)

    return CascadeResult(decision, evidence, decided_at_stage=stage.number, needs_review=True)


def should_stop(d: Decision, ev: Evidence) -> bool:
    return (
        d.confidence >= settings.CATEGORY_CONFIDENCE_MIN       # 0.8
        and d.relevant
        and d.informativeness >= settings.REQUIRED_INFO[d.category]   # food: 3, travel: 2
        and (ev.suggested_category in (None, d.category))      # vision cross-check
    )
```

---

## 3. Decide — Jev

One Jev call per stage, three questions answered in parallel:

```python
class StageDecision(BaseModel):
    category: Literal["food", "travel"]      # choice (+ confidence); options loaded from `categories`
    relevant: bool                           # is the text about this post (not promo/CTA/giveaway)?
    informativeness: int                     # score 0–3, rubric below
```

### Informativeness rubric (`decide/rubric.py`)

| Score | Food | Travel |
|---|---|---|
| 0 | Nothing — emojis, hashtags, "wait for it 😱" | Nothing — "take me back 😍" |
| 1 | Vague — "easy dinner idea" | Vague — "paradise exists" |
| 2 | Dish named — "Crispy smashed potatoes" | Place named — "Balos Lagoon, Crete" |
| 3 | Dish + ingredients or steps | Place + practical detail (how to get there, tips, prices) |

### Thresholds (`config.py`)

```python
CATEGORY_CONFIDENCE_MIN = 0.8
REQUIRED_INFO = {"food": 3, "travel": 2}   # food wants the recipe; travel wants the place
PEEK_SECONDS = 10
```

- Behind a `Decider` protocol → `JevDecider`; swappable for a structured-output LLM if Jev access is a problem.
- Jev question types (bool / choice / score-with-criteria) come from third-party package descriptions —
  **confirm against TypeSafe's docs once we have a key.**

---

## 4. Vision model options (Stages 2–3 and Enrich)

| Option | Photos | Reels (video + audio) | ~Cost/post | Notes |
|---|---|---|---|---|
| **A. Gemini Flash** (2.5 Flash → try Flash-Lite) ⭐ default | ✅ | ✅ native, one call; clip offsets + fps | $0.001–0.005 | Hears voiceover; no ffmpeg/Whisper; enables cheap Stage 2 peek |
| B. Claude Haiku 5.5 | ✅ strong OCR | ⚠️ frames only (ffmpeg) + separate transcription | ~$0.0005 + STT | Cheapest per token; more moving parts |
| C. Hybrid (Haiku photos, Gemini reels) | ✅ | ✅ | lowest | Two code paths / vendors |
| D. Open-source (Qwen3-VL…) | ✅ | ✅ | GPU hosting | Possible locally on a strong Mac, but slow; not worth it at this volume |

Wrapped behind a `VisionModel` protocol — swappable in one file.

---

## 5. Enrich — title + search text

- **Title (≤60 chars):** short text-only call to the vision model using accumulated evidence.
  Fallback: caption's first sentence with emojis/hashtags stripped.
- **Search text:** caption + every stage's description + transcript + on-screen text.

---

## 6. Store — Supabase

```sql
create extension if not exists pg_trgm;

create table categories (
  id    serial primary key,
  slug  text unique not null,          -- 'food', 'travel'
  label text not null
);

create table posts (
  id                 uuid primary key default gen_random_uuid(),
  message_mid        text unique not null,
  sender_id          text not null,
  ig_media_id        text,
  kind               text,                          -- post | carousel | reel (set by worker)
  permalink          text,
  caption            text,
  media_path         text,                          -- Storage path; null after processing
  title              text,
  search_text        text,
  category_id        int references categories(id),
  confidence         real,
  relevant           boolean,
  informativeness    smallint,
  decided_at_stage   smallint,                      -- 1 | 2 | 3
  evidence           jsonb,
  status             text not null default 'received', -- received|analyzing|done|needs_review|failed
  current_stage      smallint,
  claimed_at         timestamptz,
  error              text,
  raw_payload        jsonb not null,
  created_at         timestamptz not null default now(),
  search_tsv         tsvector generated always as (
                       to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(search_text,''))
                     ) stored
);

create index posts_search_idx   on posts using gin (search_tsv);
create index posts_title_trgm   on posts using gin (title gin_trgm_ops);
create index posts_category_idx on posts (category_id, created_at desc);
create index posts_status_idx   on posts (status, created_at);

-- Instagram token, readable only with the service role (RLS on, no policies)
create table app_secrets (
  key        text primary key,               -- 'ig_access_token'
  value      text not null,
  expires_at timestamptz
);
alter table app_secrets enable row level security;
alter table posts       enable row level security;   -- only service role / direct DB access
```

- Storage bucket `media` (private). Media deleted after processing → stays well inside the 1 GB free tier.
- `'simple'` text-search config → works for Hebrew and mixed-language captions.
- Laptop connects with `DATABASE_URL` (session pooler) + service-role key for Storage. If using the
  transaction pooler (port 6543), set asyncpg `statement_cache_size=0`.
- `raw_payload` + `evidence` allow re-running the cascade later (new categories, better models).

---

## 7. UI — local web page

`python -m app.serve` → `http://localhost:8000`

**Page**
- Login: single password (env var) → signed HTTP-only cookie. `AUTH_ENABLED=false` allowed for localhost.
- Sidebar: All · Food · Travel · Needs review — with counts. Badge: "N waiting to process".
- **"Process now" button** → runs the worker in the background, shows progress.
- Search box (debounced) → full-text + typo-tolerant search.
- Card: title · category chip · "Open on Instagram ↗" · date. Actions: change category, retry, delete.

**API**
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/login` | set session cookie |
| GET | `/api/categories` | categories + counts |
| GET | `/api/posts?category=&q=&cursor=` | list / search, paginated |
| GET | `/api/queue` | count of `received` posts |
| POST | `/api/process` | trigger the worker |
| PATCH | `/api/posts/{id}` | change category (clears `needs_review`) |
| POST | `/api/posts/{id}/retry` | re-run the cascade |
| DELETE | `/api/posts/{id}` | delete |

Vite + React, built to static files served by FastAPI.

### Triggers for processing
- CLI: `python -m app.process`
- "Process now" button in the UI
- Optional: macOS `launchd` job every hour while the laptop is awake

---

## 8. Deployment & cost

| Piece | Where | Cost |
|---|---|---|
| Receiver + token refresh | Supabase Edge Functions + pg_cron | $0 |
| Database + media | Supabase Postgres + Storage | $0 |
| Worker + UI | Laptop | $0 |
| Jev + vision | APIs | < $1 for hundreds of posts |

**Laptop `.env.<env>`** (`.env.local`, `.env.dev`, `.env.prod`, picked by `APP_ENV`): `DATABASE_URL`,
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `JEV_API_KEY`, `GEMINI_API_KEY`, `APP_PASSWORD`, `SESSION_SECRET`.
**Supabase secrets (per project):** `META_APP_SECRET`, `META_VERIFY_TOKEN`, `ALLOWED_SENDER_IDS`.

### Git & environments (details: AGENTS_PLAN.md §15)

| Env | Branch | Supabase project | Deployed by |
|---|---|---|---|
| local | feature branches | `supabase start` (Docker) | — |
| staging | `dev` — where things are tested | `insta-saver-dev` | CI on every merge to `dev` |
| production | `main` — always live and working | `insta-saver-prod` (the real bot's webhook) | CI on merge of a release PR, tagged `vX.Y.Z` |

- All work happens on branches from `dev` → PR → checks + reviews → squash-merge into `dev`.
- `dev → main` only through a release PR that **you** merge after testing on staging. Hotfixes branch from
  `main` and are back-merged into `dev`.
- Staging gets Instagram input from signed fixture replay (`make replay`); optionally a second Meta app +
  bot account for live tests.
- `make process-prod` only runs from a clean, tagged `main` checkout.

### Path to the cloud later (no code changes — the DB is the queue)
- **UI from your phone:** deploy `app.serve` to Render. The free tier's sleep/cold start is fine now —
  a human waits a few seconds; Meta's webhook no longer depends on it.
- **Automatic processing:** run `python -m app.process` as a Render Cron Job (or Cloud Run job) every few minutes.

---

## 9. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Setup: bot IG account (Creator), Meta app (Instagram Login), Supabase `-dev` + `-prod` projects, repo with `main` + `dev` (default), branch protection, pre-commit, PR template, CI, schema migration | First PR merged into `dev` deploys to staging via CI; release `v0.1.0` merged to `main` |
| **M1** | **Receiver v0 + payload spike:** handshake + insert raw payload; share a photo, a carousel, a reel | Confirmed: permalink derivation from media id, what the reel URL points to, whether carousels include all images |
| M2 | Receiver complete: signature, filters, dedupe, media → Storage, "Got it" DM, `refresh-token` + pg_cron | Share → row + stored media + DM, within seconds, laptop off |
| M3 | Worker: claim/recover, parser, **Stage 0–1 + Jev**, fallback title | `python -m app.process` categorizes posts with good captions |
| M4 | Stages 2–3 (vision) + cross-check + LLM titles + media cleanup + "Saved" DM | Weak-caption posts categorized; `decided_at_stage` logged |
| M5 | Local UI: login, categories, search, links, needs-review, "Process now" | Find a post by typing "gnocchi" |
| M6 | Hardening: tests for `parser.py` + `should_stop`, failure DMs, optional launchd | A week of real use without touching code |
| Later | Host UI on Render, cloud cron worker, thumbnails, semantic search (pgvector), more categories, travel map | — |

---

## 10. Risks

- **Meta payload changes** (`share` → `ig_post` in 2025–26) — receiver stores raw payloads; all parsing in `parser.py`.
- **Webhook delivery isn't guaranteed by Meta** — the always-on receiver minimizes loss; the Conversations
  API can't be a full backup (details only for the 20 most recent messages per conversation; shares return
  media URL only).
- **Jev is early-access** — behind `Decider`; question types to be confirmed.
- **Permalink** — webhook gives a CDN URL, not the post link; derivation from media id verified in M1.
- **Edge Function limits** — large reels must finish downloading within the function's time/memory limits;
  verify in M2 with a long reel.
- **Processing is delayed while the laptop is off** — posts wait in the queue, nothing is lost.
- **Supabase free tier pauses after ~7 days idle** — the daily `refresh-token` cron keeps the project active
  (the staging project may still pause between test sessions; resuming it is a click).
- **Public repo** (chosen so branch protection is free) — no secrets, personal data or real eval data in
  git; fixtures are synthetic/scrubbed; fork PRs never get secrets. Rules in AGENTS_PLAN.md §15.10.
- **Ambiguous posts** ("best carbonara in Rome") — one primary category + `needs_review` on disagreement.

---

## 11. Open questions

1. Vision model — Gemini Flash (default) or Claude Haiku 5.5?
2. Do you have a Jev API key yet (early access)?
3. Hourly automatic processing via `launchd`, or manual only?
4. Thumbnails on cards (keep a small image per post instead of deleting all media)?
5. Post languages — Hebrew, English, both?
6. React + Vite OK for the frontend?
7. Food-in-a-place posts: single primary category, or allow both?
