# ⛏️ IssueMiner AI

An automated, self-updating portal that reads **open issues in well-known
open-source repos** and uses an LLM (Google Gemini) to generate structured
**"how to solve it" blueprints** — problem summary, likely root cause, suggested
approach, likely files, and step-by-step implementation. Runs entirely on
GitHub Actions (daily) and can publish to GitHub Pages at $0.

## How it picks issues (the funnel)

Big repos have thousands of open issues — we never read them all. Three layers
narrow ~1,000s down to ~10 tractable issues per repo:

1. **Server-side query** (`src/fetchers.py`) — GitHub Search API filters to
   `open`, **unassigned**, **no linked PR**, label-tiered, sorted by reactions.
   Most repos here barely use `good first issue`, so we fall back to `bug`.
2. **Local heuristic score** (`src/scoring.py`) — ranks by community demand,
   a "sweet spot" of discussion, filled-in bug templates, and recency; drops
   excluded labels. No LLM cost.
3. **LLM difficulty judgement** (`src/ai_engine.py`) — only the top N per repo
   go to Gemini, which outputs a `difficulty` rating. The site sorts easy-first.

Results **accumulate** in `data/*.json`; unchanged issues are skipped on later
runs, so the library grows without re-doing work.

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
- Issues containing injection phrasing are **flagged** and forced to low confidence.

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
