# ⛏️ IssueMiner AI

An automated, self-updating portal that reads **open issues in well-known
open-source repos** and uses an LLM (Google Gemini) to generate structured
**"how to solve it" blueprints** — problem summary, likely root cause, suggested
approach, likely files, and step-by-step implementation. Runs entirely on
GitHub Actions (daily) and can publish to GitHub Pages at $0.

## The flow, end to end

Big repos have thousands of open issues — we never read them all. The pipeline
narrows thousands down to a handful of **live, wanted, doable** issues per repo,
then writes an AI plan for each. Here is exactly what happens on every run.

### 1. Which repos

The target repos live in `config.yml` under `repos:` — currently:

| Repo | Domain | Forge |
|---|---|---|
| `ollama/ollama` | Local LLM runner | GitHub |
| `langfuse/langfuse` | LLM observability & evals | GitHub |
| `duckdb/duckdb` | Analytical in-process DB | GitHub |
| `ClickHouse/ClickHouse` | High-performance DB | GitHub |
| `FreeCAD/FreeCAD` | Parametric 3D CAD | GitHub |
| `blender/blender` | 3D creation suite | Gitea (self-hosted) |

Add/remove repos there — no code change. Each repo can override any setting.

Label tiers are **plain label names**, matched against the repo's own casing and
prefixes (`Type/Bug`, `Meta/Good First Issue`, `Good first issue`) — not search
syntax. The older `label:"..."` form is still accepted and unwrapped.

### 2. Fetch candidates — the forge does the coarse filtering (`src/fetchers.py`)

For each repo we pull a candidate pool that *always* requires an issue to be
open, unassigned, not already fixed by a linked PR, and **active within
`max_inactive_days` (default 180)** — based on *last activity*, not when it was
opened, so an old-but-active issue still counts as live. A **label tier** list is
tried in order until the pool is full (`candidate_pool_size`, 40).

Two forge backends implement that contract:

**`forge: github`** (default) — one **Search API** query per tier
(`is:issue is:open no:assignee -linked:pr updated:>=<date> label:"..."`), sorted
by total reactions, so the pool arrives demand-ordered with reaction counts
already populated.

**`forge: gitea`** — for self-hosted trackers like Blender's
`projects.blender.org`, set via `host:`. The API is public and needs no token
(`GITEA_TOKEN` is optional, only to lift anonymous rate limits). It is markedly
weaker than GitHub's, so the backend compensates:

| Gitea limitation | How we handle it |
|---|---|
| No reaction counts in the issue list | Back-fill one cheap `/reactions` call per candidate — otherwise every Gitea issue scores 0 on the NEED axis and sinks below GitHub ones |
| No demand-based sort (`sort=mostcomment` is silently ignored) | Rely on narrow curated label tiers instead of a sorted firehose |
| No unassigned filter | Drop assigned issues client-side |

This is why tier order matters much more on Gitea: `Meta/Good First Issue` (74
open) and `Meta/Papercut` (105) are curated and small enough to sample
meaningfully, while `Type/Bug` (~4k) is a last resort.

### 3. Rank by "need" — cheap heuristics, no LLM (`src/scoring.py`)

Each candidate gets a **need score**. The score is driven by community demand,
then adjusted so structurally un-solvable issues sink. The top
`triage_pool_size` (15) by score advance. Roughly:

**Demand (raises the score):**
- 👍 reactions — `+2.0` each (capped at 25)
- total reactions — `+0.8` each (capped at 40)
- discussion in a **1–15 comment sweet spot** — `+5` (engaged, not a flame war)

**Feasibility hints (nudge, so the triage stage isn't crowded):**
- needs specific hardware/OS/GPU (`M5`, `CUDA`, `Metal`, …) — `−8`
- tracking issue / RFC / roadmap / epic — `−8`
- open-ended feature request in the title — `−4`
- thin body (< 80 chars) — `−4`; huge thread (> 30 comments) — `−4`
- contains a reproduction / stack trace — `+3`; a code block — `+2`
- `good first issue` / `help wanted` — `+6`; `bug` — `+2`
- brand-new (< 2 days, unvetted) — `−2`

So **"need" = mostly community demand, tilted toward issues that are also
concrete and self-contained.** Excluded labels (`wontfix`, `duplicate`,
`question`, …) drop an issue entirely.

### 4. Gemini, in two tiers (`src/ai_engine.py`)

Only the ranked shortlist reaches an LLM, and in two stages so the expensive
work is spent only on issues worth it:

- **Tier 1 — Triage** (`gemini-2.5-flash-lite`, cheap): for the top ~15 by need,
  a small structured call judges **feasibility** — `feasibility` (high/med/low),
  `self_contained`, `needs_special_environment`, `blockers`, `estimated_effort`,
  `worth_solving`. Issues that aren't feasible + self-contained + free of special
  -environment needs are **gated out here**. (This is where e.g. an "only
  reproduces on an Apple M5" bug gets dropped despite high demand.)

- **Tier 2 — Blueprint** (`gemini-2.5-flash`, better): the up-to-`blueprint_top_n`
  (8) **highest-need survivors** get a full plan — `problem_summary`,
  `root_cause_hypothesis`, `suggested_approach`, `likely_areas`, `prerequisites`,
  ordered `implementation_steps`, `confidence`.

Global caps (`max_triage_calls_per_run`, `max_blueprint_calls_per_run`) and
graceful stop-on-quota mean a run can never blow the Gemini free tier.

### 5. Where it appears

- **Accumulated data** → `data/<owner>__<repo>.json`. Every run **upserts** and
  **skips unchanged issues** (re-run only if the issue changed or is older than
  `reprocess_after_days`), so the library grows without redoing work. In CI this
  is **committed back to `main`** by the workflow.
- **The website** → `src/generator.py` renders all stored blueprints into
  `public/index.html`, **sorted by need (highest first)**, with feasibility /
  effort / self-contained badges, blockers, and a "How to solve it" section per
  card. Filter by repo; "Copy prompt" per card.
  - **Private repo (now):** open `public/index.html` locally
    (`python main.py --site-only` rebuilds it from `data/`).
  - **Public + Pages enabled:** it goes live at
    `https://<user>.github.io/<repo>/`, refreshed daily (see *Going live* below).

**One line:** live issues (≤180d) → ranked by community need → feasibility-gated
by cheap AI → the best get a full AI fix-plan → committed to `data/` and rendered
to a website.

## Prompt-injection safety

Issue text is untrusted user input. Defenses:

- **The LLM has no tools / no agency** — it's a pure text→JSON transform, so
  injected text cannot make it *do* anything.
- **Spotlighting** — issue text is fenced and the system prompt declares it
  data, not instructions.
- **Structured output** (Pydantic schema) constrains what the model can emit.
- **We construct the source URL ourselves** — the model never supplies links.
- **Escape-on-render + CSP** (`src/generator.py`) — every value (issue text
  *and* AI output) is HTML-escaped and the page has a strict Content-Security
  -Policy, so even a fully-injected blueprint renders as inert text. This is the
  key control: we assume the AI output itself is untrusted.
- Issues containing injection phrasing are **flagged**, forced to `feasibility=low`
  (so triage gates them out), and marked "⚠ review" if they ever render.

## Configure

Edit `config.yml` — target repos, per-repo label tiers, caps, and excluded
labels. No code changes needed.

## Run locally

```bash
pip install -r requirements.txt

# Fetch + score only — prints the shortlist, no API key needed:
python main.py --no-ai

# Full run (needs a Gemini key; GitHub token optional but avoids rate limits):
export GEMINI_API_KEY=...          # from https://aistudio.google.com
export GITHUB_TOKEN=...            # optional: a personal access token
python main.py

# Preview the generated site:
open public/index.html            # regenerate from existing data with: python main.py --site-only
```

## Deploy on GitHub

This repo is designed to start **private** (host later).

1. Push to a private GitHub repo.
2. Add your Gemini key as a secret: **Settings → Secrets and variables →
   Actions → New repository secret** → `GEMINI_API_KEY`. (`GITHUB_TOKEN` is
   automatic.)
3. Run the workflow manually (**Actions → Mine issues & deploy → Run workflow**)
   or wait for the daily cron. It mines issues and commits `data/`.

### Going live (GitHub Pages)

GitHub Pages needs either a **public** repo (free) or **GitHub Pro** (private).
When ready:

1. **Settings → Pages → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions → Variables** → add
   `ENABLE_PAGES = true`.

The next run publishes to `https://<user>.github.io/<repo>/`. Until then the
build stays green and you preview `public/index.html` locally.

## Structure

```
config.yml               # target repos + strategy (edit this)
main.py                  # pipeline entry point
src/fetchers.py          # Layer 1: GitHub search
src/scoring.py           # Layer 2: tractability heuristics
src/ai_engine.py         # Layer 3: Gemini structured synthesis + injection defenses
src/store.py             # accumulating per-repo JSON storage
src/generator.py         # static site (escape-on-render + CSP)
.github/workflows/deploy.yml
data/                    # accumulated blueprints (committed)
public/                  # generated site (gitignored, regenerated each run)
```
