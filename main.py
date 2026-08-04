"""IssueMiner AI — pipeline entry point.

  fetch (L1) -> rank by need (L2) -> triage/feasibility gate (L3a) -> blueprint (L3b)
  -> accumulate to data/*.json -> generate public/index.html

Run locally:
  python main.py                 # full run (needs GEMINI_API_KEY)
  python main.py --no-ai         # fetch + rank only, prints the shortlist (no key needed)
  python main.py --site-only     # just regenerate the site from existing data/
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src import ai_engine, fetchers, generator, scoring, store
from src.ai_engine import QuotaExceeded

CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def _updated_after(repo_cfg: dict, s: dict) -> str | None:
    """YYYY-MM-DD cutoff for last activity (per-repo override, else global)."""
    days = repo_cfg.get("max_inactive_days", s.get("max_inactive_days"))
    if not days:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime("%Y-%m-%d")


class Budget:
    """Global per-run call caps — quota can't be blown even if config is wrong."""

    def __init__(self, max_triage: int, max_blueprint: int):
        self.triage_left = max_triage
        self.blueprint_left = max_blueprint


def _process_repo(repo_cfg: dict, s: dict, exclude: list[str], budget: Budget) -> None:
    repo = repo_cfg["name"]
    print(f"\n=== {repo} ===")

    candidates = fetchers.fetch_candidates(
        repo, repo_cfg["label_tiers"], s["candidate_pool_size"], _updated_after(repo_cfg, s)
    )
    shortlist = scoring.rank(candidates, exclude, s["triage_pool_size"])
    print(f"  ranked {len(shortlist)}/{len(candidates)} candidates by need")

    st = store.load(repo)
    feasible: list[tuple[dict, dict]] = []  # (issue, triage) awaiting blueprint
    skipped = 0

    # Tier 1: triage top-by-need candidates until we have enough feasible ones.
    for issue in shortlist:
        if len(feasible) >= s["blueprint_top_n"]:
            break
        if not store.needs_processing(st, issue, s["reprocess_after_days"]):
            skipped += 1
            continue
        if budget.triage_left <= 0:
            print("  [budget] triage cap reached")
            break
        budget.triage_left -= 1
        tri = ai_engine.triage(issue, repo, s["triage_model"], s["triage_body_char_limit"])
        if not tri:
            continue
        verdict = "✓feasible" if ai_engine.is_feasible(tri) else "✗gated"
        print(f"    triage #{issue['number']}: {tri['feasibility']} {verdict} — {tri['feasibility_reason'][:60]}")
        if ai_engine.is_feasible(tri):
            feasible.append((issue, tri))

    # Tier 2: full blueprint for feasible survivors (already highest-need first).
    processed = 0
    for issue, tri in feasible:
        if budget.blueprint_left <= 0:
            print("  [budget] blueprint cap reached")
            break
        budget.blueprint_left -= 1
        comments = fetchers.fetch_comments(repo, issue["number"], s["max_comments_per_issue"])
        bp = ai_engine.blueprint(issue, repo, comments, s["blueprint_model"], s["issue_body_char_limit"])
        if not bp:
            continue
        store.upsert(st, ai_engine.build_record(issue, repo, tri, bp))
        processed += 1
        print(f"    ✓ blueprint #{issue['number']} ({tri['estimated_effort']})")

    store.save(st)
    print(f"  feasible {len(feasible)}, blueprinted {processed}, skipped {skipped} (unchanged)")


def run(no_ai: bool = False) -> None:
    cfg = load_config()
    s = cfg["settings"]
    exclude = cfg.get("exclude_labels", [])

    if no_ai:
        for repo_cfg in cfg["repos"]:
            repo = repo_cfg["name"]
            print(f"\n=== {repo} ===")
            candidates = fetchers.fetch_candidates(
                repo, repo_cfg["label_tiers"], s["candidate_pool_size"], _updated_after(repo_cfg, s)
            )
            for i in scoring.rank(candidates, exclude, s["triage_pool_size"]):
                print(f"    [{i['_score']:>5}] #{i['number']} {i['title'][:70]}")
        return

    budget = Budget(s["max_triage_calls_per_run"], s["max_blueprint_calls_per_run"])
    for repo_cfg in cfg["repos"]:
        try:
            _process_repo(repo_cfg, s, exclude, budget)
        except QuotaExceeded as e:
            print(f"\n[quota] Gemini quota reached — stopping cleanly, resuming next run.\n  {str(e)[:160]}")
            break

    out = generator.generate(store.load_all())
    print(f"\nSite written to {out}")


if __name__ == "__main__":
    if "--site-only" in sys.argv:
        print(f"Site written to {generator.generate(store.load_all())}")
    else:
        run(no_ai="--no-ai" in sys.argv)
