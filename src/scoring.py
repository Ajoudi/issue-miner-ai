"""Tractability scoring — Layer 2 of the funnel (free, no LLM).

Given the candidate pool, rank issues by how likely they are to be an *easy,
well-defined, wanted* piece of work — using only signals already present in the
search payload. The top N per repo go to the LLM; the rest are dropped.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

REPRO_HINTS = re.compile(r"(reproduc|steps to|expected|actual|traceback|stack trace)", re.I)
CODE_BLOCK = re.compile(r"```")


def _age_days(iso: str | None) -> float:
    if not iso:
        return 9999.0
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def score_issue(issue: dict[str, Any], exclude_labels: list[str]) -> float | None:
    """Return a tractability score, or None if the issue should be excluded.

    Higher = more tractable/wanted. Heuristics:
      + community demand (reactions / thumbs up)
      + a "sweet spot" of discussion (1-15 comments); penalize 0 and >30
      + a filled-in bug template (code block / reproduction language)
      + curated easy labels
      - stale (very old) or unvetted (brand new) issues
      - excluded labels remove the issue entirely
    """
    labels_lower = {l.lower() for l in issue.get("labels", [])}
    if labels_lower & {x.lower() for x in exclude_labels}:
        return None

    score = 0.0

    # Community demand.
    score += min(issue.get("thumbs_up", 0), 20) * 1.5
    score += min(issue.get("reactions", 0), 30) * 0.5

    # Discussion sweet spot.
    c = issue.get("comments", 0)
    if c == 0:
        score -= 3          # nobody has engaged / unvetted
    elif 1 <= c <= 15:
        score += 6          # discussed enough to be understood, not a war
    elif c <= 30:
        score += 1
    else:
        score -= 4          # likely contentious / hard

    # Body quality — a real, reproducible report.
    body = issue.get("body", "") or ""
    if len(body) < 80:
        score -= 4          # too thin to act on
    if CODE_BLOCK.search(body):
        score += 3
    if REPRO_HINTS.search(body):
        score += 3

    # Curated labels (bonus when present).
    if labels_lower & {"good first issue", "help wanted", "good-first-issue"}:
        score += 8
    if "bug" in labels_lower:
        score += 3

    # Recency: penalize stale and brand-new.
    age = _age_days(issue.get("updated_at"))
    if age > 365:
        score -= 5
    elif age > 180:
        score -= 2
    if _age_days(issue.get("created_at")) < 2:
        score -= 2          # too new to be vetted

    return score


def rank(issues: list[dict[str, Any]], exclude_labels: list[str], top_n: int) -> list[dict[str, Any]]:
    """Score, filter, and return the top N issues (each annotated with `_score`)."""
    scored: list[dict[str, Any]] = []
    for issue in issues:
        s = score_issue(issue, exclude_labels)
        if s is None:
            continue
        issue = {**issue, "_score": round(s, 2)}
        scored.append(issue)
    scored.sort(key=lambda i: i["_score"], reverse=True)
    return scored[:top_n]
