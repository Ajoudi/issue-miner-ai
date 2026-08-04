"""GitHub issue fetching — Layer 1 of the funnel (server-side filtering).

We never download all of a repo's issues. The GitHub Search API does the heavy
filtering for us: open, unassigned, no linked PR, label-tiered, reaction-sorted.
Only a small candidate pool comes back per repo.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

SEARCH_URL = "https://api.github.com/search/issues"
API_ROOT = "https://api.github.com"
USER_AGENT = "IssueMiner-AI/1.0 (+https://github.com/)"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _get(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> requests.Response:
    """GET with basic retry + rate-limit awareness."""
    for attempt in range(3):
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
            wait = max(1, min(60, reset - int(time.time()))) if reset else 5 * (attempt + 1)
            print(f"  [rate-limit] waiting {wait}s...")
            time.sleep(wait)
            continue
        return resp
    return resp  # type: ignore[return-value]


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw search hit to the fields the rest of the pipeline uses."""
    return {
        "number": item["number"],
        "title": item.get("title", ""),
        "body": item.get("body") or "",
        "html_url": item["html_url"],
        "labels": [l["name"] for l in item.get("labels", [])],
        "comments": item.get("comments", 0),
        "reactions": (item.get("reactions") or {}).get("total_count", 0),
        "thumbs_up": (item.get("reactions") or {}).get("+1", 0),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "state": item.get("state"),
    }


def fetch_candidates(
    repo: str, label_tiers: list[str], pool_size: int, updated_after: str | None = None
) -> list[dict[str, Any]]:
    """Fetch a candidate pool for `repo`, trying each label tier until full.

    Base query always requires: open issue, unassigned, no linked PR, and (if
    `updated_after` is given, as YYYY-MM-DD) last activity on/after that date.
    Sorted by total reactions descending so the most-wanted issues come first.
    """
    session = _session()
    seen: dict[int, dict[str, Any]] = {}
    recency = f"updated:>={updated_after}" if updated_after else ""

    for tier in label_tiers:
        if len(seen) >= pool_size:
            break
        q = f"repo:{repo} is:issue is:open no:assignee -linked:pr {recency} {tier}".strip()
        params = {"q": q, "sort": "reactions", "order": "desc", "per_page": min(pool_size, 100)}
        resp = _get(session, SEARCH_URL, params)
        if resp.status_code != 200:
            print(f"  [warn] {repo} tier {tier!r} -> HTTP {resp.status_code}: {resp.text[:120]}")
            continue
        items = resp.json().get("items", [])
        for it in items:
            if it["number"] not in seen:
                seen[it["number"]] = _normalize(it)
        print(f"  tier {tier or '(no label)'!r}: +{len(items)} (pool={len(seen)})")
        time.sleep(2)  # be gentle with the search rate limit

    return list(seen.values())


def get_issue_state(repo: str, number: int) -> str | None:
    """Return 'open' / 'closed' for a single issue, or None on error (leave as-is).
    A 404 (deleted/transferred) is treated as 'closed'. Uses the core REST API
    (5000 req/hr authenticated) — no Gemini cost."""
    session = _session()
    resp = _get(session, f"{API_ROOT}/repos/{repo}/issues/{number}")
    if resp.status_code == 200:
        return resp.json().get("state")
    if resp.status_code == 404:
        return "closed"
    return None


def fetch_comments(repo: str, number: int, limit: int) -> list[str]:
    """Fetch up to `limit` comment bodies for a single issue (called only for
    the small set of issues we actually send to the LLM)."""
    if limit <= 0:
        return []
    session = _session()
    url = f"{API_ROOT}/repos/{repo}/issues/{number}/comments"
    resp = _get(session, url, {"per_page": limit})
    if resp.status_code != 200:
        return []
    return [c.get("body") or "" for c in resp.json()][:limit]
