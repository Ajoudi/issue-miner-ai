"""Accumulating storage — one JSON file per repo under data/.

The site grows over time. On each run we skip issues we've already processed
unless the issue changed (new updated_at) or is older than reprocess_after_days.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _path(repo: str) -> Path:
    return DATA_DIR / (repo.replace("/", "__") + ".json")


def load(repo: str) -> dict[str, Any]:
    p = _path(repo)
    if p.exists():
        return json.loads(p.read_text())
    return {"repo": repo, "generated_at": None, "issues": {}}


def needs_processing(store: dict[str, Any], issue: dict[str, Any], reprocess_after_days: int) -> bool:
    existing = store["issues"].get(str(issue["number"]))
    if not existing:
        return True
    # Issue changed since last time?
    if existing.get("updated_at") != issue.get("updated_at"):
        return True
    # Periodic refresh of stale blueprints.
    processed = existing.get("processed_at")
    if not processed:
        return True
    dt = datetime.fromisoformat(processed.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days >= reprocess_after_days


def upsert(store: dict[str, Any], blueprint: dict[str, Any]) -> None:
    blueprint = {**blueprint, "processed_at": datetime.now(timezone.utc).isoformat()}
    store["issues"][str(blueprint["number"])] = blueprint


def prune_resolved(store: dict[str, Any], repo: str, check_state) -> int:
    """Mark stored issues that are no longer open as resolved (hidden from the
    site, never re-analyzed). `check_state(repo, number) -> 'open'|'closed'|None`.
    Returns the count newly marked resolved."""
    newly = 0
    for num, rec in store["issues"].items():
        if rec.get("resolved"):
            continue
        if check_state(repo, int(num)) == "closed":
            rec["resolved"] = True
            rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
            newly += 1
    return newly


def save(store: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    store["generated_at"] = datetime.now(timezone.utc).isoformat()
    _path(store["repo"]).write_text(json.dumps(store, indent=2, ensure_ascii=False))


def load_all() -> list[dict[str, Any]]:
    """All stored blueprints across every repo, for the site generator."""
    out: list[dict[str, Any]] = []
    for f in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        out.extend(data.get("issues", {}).values())
    return out
