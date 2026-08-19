"""Heuristic ranking — Layer 2 of the funnel (free, no LLM).

Goal: rank candidates by NEED (community demand), while pushing obviously
infeasible issues down so they don't crowd out the triage pool. The LLM triage
stage (Layer 3a) does the real feasibility gate; this is just a cheap pre-sort.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

REPRO_HINTS = re.compile(r"(reproduc|steps to|expected|actual|traceback|stack trace|error:)", re.I)
CODE_BLOCK = re.compile(r"```")
# Structural infeasibility signals (down-rank; triage confirms/denies).
SPECIAL_ENV = re.compile(
    r"\b(m1|m2|m3|m4|m5|cuda|rocm|metal|vulkan|windows arm|aarch64|risc-?v|raspberry|specific (gpu|driver|hardware))\b",
    re.I,
)
META_ISSUE = re.compile(r"\b(tracking issue|meta[- ]issue|umbrella|rfc|proposal|roadmap|epic)\b", re.I)
BROAD_FEATURE = re.compile(r"^\s*(feature request|feat|\[feature\]|support for|add support|please add)\b", re.I)
# Label signals, matched as substrings so they survive per-forge naming schemes.
CONTRIB_LABEL = re.compile(r"good[- ]?first[- ]?issue|help wanted|easy|beginner", re.I)
PAPERCUT_LABEL = re.compile(r"papercut|small|quick win", re.I)
BUG_LABEL = re.compile(r"(^|[/\s:-])bug(s|fix)?($|[/\s:,-])", re.I)


def _age_days(iso: str | None) -> float:
    if not iso:
        return 9999.0
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def score_issue(issue: dict[str, Any], exclude_labels: list[str]) -> float | None:
    """Return a NEED-weighted score (with light feasibility penalties), or None
    if the issue should be dropped entirely."""
    labels_lower = {l.lower() for l in issue.get("labels", [])}
    if labels_lower & {x.lower() for x in exclude_labels}:
        return None

    title = issue.get("title", "") or ""
    body = issue.get("body", "") or ""
    blob = f"{title}\n{body}"

    # --- NEED (community demand) — the primary axis -----------------------
    need = 0.0
    need += min(issue.get("thumbs_up", 0), 25) * 2.0
    need += min(issue.get("reactions", 0), 40) * 0.8
    c = issue.get("comments", 0)
    if 1 <= c <= 15:
        need += 5          # engaged, not a war
    elif c > 30:
        need -= 4          # contentious / stuck

    score = need

    # --- Light feasibility de-prioritization (triage makes the real call) -
    if SPECIAL_ENV.search(blob):
        score -= 8         # needs specific hardware/OS most solvers lack
    if META_ISSUE.search(blob):
        score -= 8         # tracking/RFC — not a discrete fix
    if BROAD_FEATURE.search(title):
        score -= 4         # open-ended feature, usually not self-contained

    # Feasibility boosts — a concrete, reproducible report.
    if len(body) < 80:
        score -= 4
    if CODE_BLOCK.search(body):
        score += 2
    if REPRO_HINTS.search(blob):
        score += 3
    # Label bonuses are matched as substrings, not exact names: forges prefix
    # and capitalize differently ("Type/Bug", "Meta/Good First Issue",
    # "Good first issue") and an exact-match set silently scores them all as 0.
    label_blob = " ".join(labels_lower)
    if CONTRIB_LABEL.search(label_blob):
        score += 6     # explicitly flagged as newcomer-friendly by maintainers
    if PAPERCUT_LABEL.search(label_blob):
        score += 5     # small, well-defined annoyance — our ideal shape
    if BUG_LABEL.search(label_blob):
        score += 2     # a defect is more tractable than an open-ended feature

    # Recency: penalize stale and brand-new.
    if _age_days(issue.get("updated_at")) > 365:
        score -= 5
    if _age_days(issue.get("created_at")) < 2:
        score -= 2

    return score


def rank(issues: list[dict[str, Any]], exclude_labels: list[str], top_n: int) -> list[dict[str, Any]]:
    """Score, filter, and return the top N issues (each annotated with `_score`)."""
    scored: list[dict[str, Any]] = []
    for issue in issues:
        s = score_issue(issue, exclude_labels)
        if s is None:
            continue
        scored.append({**issue, "_score": round(s, 2)})
    scored.sort(key=lambda i: i["_score"], reverse=True)
    return scored[:top_n]
