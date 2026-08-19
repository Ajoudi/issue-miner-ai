"""Issue fetching — Layer 1 of the funnel (server-side filtering).

Two forges are supported, selected per-repo by `forge:` in config.yml:

  github  — api.github.com Search API. Filters open/unassigned/no-linked-PR/
            label/recency server-side and sorts by reactions, so the pool comes
            back demand-ordered and reaction counts are already populated.
  gitea   — a self-hosted Gitea instance (`host:` in config), e.g. Blender's
            projects.blender.org. Its API is public and needs no auth, but it is
            much weaker than GitHub's: no reaction counts in the issue list, no
            demand-based sort (`sort=mostcomment` is silently ignored), and no
            unassigned filter. So we fetch a recency-ordered pool, drop assigned
            issues client-side, and back-fill reaction counts with one cheap
            request per candidate — otherwise every Gitea issue would score 0 on
            the NEED axis and sink below GitHub ones in the global ranking.

We never download all of a repo's issues; only a small candidate pool per repo.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Callable

import requests

SEARCH_URL = "https://api.github.com/search/issues"
API_ROOT = "https://api.github.com"
USER_AGENT = "IssueMiner-AI/1.0 (+https://github.com/)"

# Legacy config tiers were raw GitHub search fragments (label:bug, label:"help
# wanted"). Tiers are now plain label names so they work on any forge; this
# unwraps the old syntax so existing configs keep working.
_LEGACY_TIER = re.compile(r'^label:\s*"?(.*?)"?$', re.I)


def normalize_tier(tier: str) -> str:
    """A config label tier as a plain label name ('' means 'no label filter')."""
    tier = (tier or "").strip()
    m = _LEGACY_TIER.match(tier)
    return (m.group(1) if m else tier).strip()


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def _gh_session() -> requests.Session:
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


def _gh_normalize(item: dict[str, Any]) -> dict[str, Any]:
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


def _gh_fetch(repo: str, tiers: list[str], pool_size: int, updated_after: str | None) -> list[dict[str, Any]]:
    session = _gh_session()
    seen: dict[int, dict[str, Any]] = {}
    recency = f"updated:>={updated_after}" if updated_after else ""

    for tier in tiers:
        if len(seen) >= pool_size:
            break
        label_q = f'label:"{tier}"' if tier else ""
        q = f"repo:{repo} is:issue is:open no:assignee -linked:pr {recency} {label_q}".strip()
        params = {"q": q, "sort": "reactions", "order": "desc", "per_page": min(pool_size, 100)}
        resp = _get(session, SEARCH_URL, params)
        if resp.status_code != 200:
            print(f"  [warn] {repo} tier {tier or '(no label)'!r} -> HTTP {resp.status_code}: {resp.text[:120]}")
            continue
        items = resp.json().get("items", [])
        for it in items:
            if it["number"] not in seen:
                seen[it["number"]] = _gh_normalize(it)
        print(f"  tier {tier or '(no label)'!r}: +{len(items)} (pool={len(seen)})")
        time.sleep(2)  # be gentle with the search rate limit

    return list(seen.values())


# --------------------------------------------------------------------------- #
# Gitea (projects.blender.org and friends)
# --------------------------------------------------------------------------- #
def _gitea_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
    # Optional — the public instances we target need no auth, but a token lifts
    # anonymous rate limits if the instance enforces them.
    token = os.environ.get("GITEA_TOKEN")
    if token:
        s.headers["Authorization"] = f"token {token}"
    return s


def _gitea_api(host: str, repo: str) -> str:
    return f"{host.rstrip('/')}/api/v1/repos/{repo}"


def _gitea_normalize(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item["number"],
        "title": item.get("title", ""),
        "body": item.get("body") or "",
        "html_url": item["html_url"],
        "labels": [l["name"] for l in (item.get("labels") or [])],
        "comments": item.get("comments", 0),
        "reactions": 0,   # back-filled below — not present in Gitea's list payload
        "thumbs_up": 0,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "state": item.get("state"),
    }


def _gitea_is_unassigned(item: dict[str, Any]) -> bool:
    """Gitea has no server-side unassigned filter, so we drop them here."""
    return not item.get("assignee") and not (item.get("assignees") or [])


def _gitea_reactions(session: requests.Session, api: str, number: int) -> tuple[int, int]:
    """(total, thumbs_up) for one issue. Gitea returns one object per reacting
    user (or null), so the counts are just list lengths."""
    resp = session.get(f"{api}/issues/{number}/reactions", timeout=30)
    if resp.status_code != 200:
        return 0, 0
    data = resp.json() or []
    if not isinstance(data, list):
        return 0, 0
    return len(data), sum(1 for r in data if r.get("content") in ("+1", "thumbs_up", "heart", "hooray"))


def _gitea_fetch(
    repo: str, host: str, tiers: list[str], pool_size: int, updated_after: str | None
) -> list[dict[str, Any]]:
    session = _gitea_session()
    api = _gitea_api(host, repo)
    seen: dict[int, dict[str, Any]] = {}
    # Gitea wants RFC3339; our cutoff arrives as YYYY-MM-DD.
    since = f"{updated_after}T00:00:00Z" if updated_after else None

    for tier in tiers:
        if len(seen) >= pool_size:
            break
        params: dict[str, Any] = {
            "state": "open",
            "type": "issues",            # excludes pull requests
            "limit": min(pool_size, 50),  # Gitea caps page size
        }
        if tier:
            params["labels"] = tier
        if since:
            params["since"] = since
        resp = session.get(f"{api}/issues", params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  [warn] {repo} tier {tier or '(no label)'!r} -> HTTP {resp.status_code}: {resp.text[:120]}")
            continue
        items = resp.json() or []
        added = 0
        for it in items:
            if it["number"] in seen or not _gitea_is_unassigned(it):
                continue
            seen[it["number"]] = _gitea_normalize(it)
            added += 1
        print(f"  tier {tier or '(no label)'!r}: +{added} (pool={len(seen)})")
        time.sleep(1)

    # Back-fill demand signal — one small request per candidate.
    for issue in seen.values():
        total, up = _gitea_reactions(session, api, issue["number"])
        issue["reactions"], issue["thumbs_up"] = total, up
        time.sleep(0.15)

    return list(seen.values())


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def fetch_candidates(repo_cfg: dict[str, Any], pool_size: int, updated_after: str | None = None) -> list[dict[str, Any]]:
    """Fetch a candidate pool for one configured repo, trying each label tier
    until the pool is full. Always returns open, unassigned issues whose last
    activity is on/after `updated_after` (YYYY-MM-DD), in the normalized shape
    the ranking and blueprint stages expect."""
    repo = repo_cfg["name"]
    tiers = [normalize_tier(t) for t in repo_cfg.get("label_tiers", [""])]
    forge = repo_cfg.get("forge", "github")

    if forge == "gitea":
        host = repo_cfg.get("host")
        if not host:
            print(f"  [warn] {repo}: forge 'gitea' needs a `host:` — skipping")
            return []
        return _gitea_fetch(repo, host, tiers, pool_size, updated_after)
    return _gh_fetch(repo, tiers, pool_size, updated_after)


def state_checker(repo_cfg: dict[str, Any]) -> Callable[[str, int], str | None]:
    """Return a `(repo, number) -> 'open'|'closed'|None` probe bound to this
    repo's forge, for store.prune_resolved. None means 'leave the record as-is'.
    A 404 (deleted/transferred) counts as closed. No LLM cost either way."""
    forge = repo_cfg.get("forge", "github")
    host = repo_cfg.get("host", "")
    # One session for the whole prune sweep — this runs once per stored issue.
    session = _gitea_session() if forge == "gitea" else _gh_session()

    def check(repo: str, number: int) -> str | None:
        if forge == "gitea":
            resp = session.get(f"{_gitea_api(host, repo)}/issues/{number}", timeout=30)
        else:
            resp = _get(session, f"{API_ROOT}/repos/{repo}/issues/{number}")
        if resp.status_code == 200:
            return resp.json().get("state")
        if resp.status_code == 404:
            return "closed"
        return None

    return check


def fetch_comments(repo_cfg: dict[str, Any], number: int, limit: int) -> list[str]:
    """Up to `limit` comment bodies for one issue — called only for the small
    set of issues we actually send to the LLM."""
    if limit <= 0:
        return []
    repo = repo_cfg["name"]
    if repo_cfg.get("forge") == "gitea":
        api = _gitea_api(repo_cfg.get("host", ""), repo)
        resp = _gitea_session().get(f"{api}/issues/{number}/comments", params={"limit": limit}, timeout=30)
    else:
        resp = _get(_gh_session(), f"{API_ROOT}/repos/{repo}/issues/{number}/comments", {"per_page": limit})
    if resp.status_code != 200:
        return []
    return [c.get("body") or "" for c in (resp.json() or [])][:limit]
