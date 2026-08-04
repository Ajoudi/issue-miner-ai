"""IssueMiner AI — pipeline entry point.

  fetch candidates (Layer 1)  ->  score & rank (Layer 2)  ->  Gemini synth (Layer 3)
  ->  accumulate to data/*.json  ->  generate public/index.html

Run locally:
  python main.py                 # full run (needs GEMINI_API_KEY; GITHUB_TOKEN optional but recommended)
  python main.py --no-ai         # fetch + score only, prints the shortlist (no API key needed)
  python main.py --site-only     # just regenerate the site from existing data/
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from src import ai_engine, fetchers, generator, scoring, store

CONFIG_PATH = Path(__file__).resolve().parent / "config.yml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def run(no_ai: bool = False) -> None:
    cfg = load_config()
    s = cfg["settings"]
    exclude = cfg.get("exclude_labels", [])

    for repo_cfg in cfg["repos"]:
        repo = repo_cfg["name"]
        print(f"\n=== {repo} ===")
        candidates = fetchers.fetch_candidates(
            repo, repo_cfg["label_tiers"], s["candidate_pool_size"]
        )
        shortlist = scoring.rank(candidates, exclude, s["max_issues_per_repo"])
        print(f"  shortlisted {len(shortlist)}/{len(candidates)} candidates")

        if no_ai:
            for i in shortlist:
                print(f"    [{i['_score']:>5}] #{i['number']} {i['title'][:70]}")
            continue

        st = store.load(repo)
        processed = skipped = 0
        for issue in shortlist:
            if not store.needs_processing(st, issue, s["reprocess_after_days"]):
                skipped += 1
                continue
            comments = fetchers.fetch_comments(repo, issue["number"], s["max_comments_per_issue"])
            bp = ai_engine.synthesize(
                issue, repo, comments, s["model"], s["issue_body_char_limit"]
            )
            if bp:
                store.upsert(st, bp)
                processed += 1
                print(f"    ✓ #{issue['number']} ({bp['difficulty']})")
        store.save(st)
        print(f"  processed {processed}, skipped {skipped} (unchanged)")

    if not no_ai:
        out = generator.generate(store.load_all())
        print(f"\nSite written to {out}")


def site_only() -> None:
    out = generator.generate(store.load_all())
    print(f"Site written to {out}")


if __name__ == "__main__":
    if "--site-only" in sys.argv:
        site_only()
    else:
        run(no_ai="--no-ai" in sys.argv)
