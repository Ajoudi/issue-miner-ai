"""Static site generator — writes public/index.html.

SECURITY: every dynamic value (issue text AND AI output) is treated as untrusted
and HTML-escaped via `e()`. Links are validated to https-only. A Content-Security
-Policy meta tag is defense-in-depth. Even a fully-injected blueprint can only
ever render as plain visible text.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

FEAS_BADGE = {
    "high": "background:#dcfce7;color:#166534",
    "medium": "background:#fef9c3;color:#854d0e",
    "low": "background:#fee2e2;color:#991b1b",
}
EFFORT_LABEL = {"under_1h": "under 1h", "half_day": "half day", "multi_day": "multi-day"}


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def safe_url(url: str) -> str:
    url = (url or "").strip()
    return e(url) if url.lower().startswith("https://") else "#"


def _card(bp: dict[str, Any]) -> str:
    feas = bp.get("feasibility", "low")
    effort = EFFORT_LABEL.get(bp.get("estimated_effort", ""), bp.get("estimated_effort", "?"))
    steps = "".join(f"<li>{e(s)}</li>" for s in bp.get("implementation_steps", []))
    areas = "".join(f'<span class="chip">{e(a)}</span>' for a in bp.get("likely_areas", []))
    prereqs = "".join(f"<li>{e(p)}</li>" for p in bp.get("prerequisites", []))
    blockers = bp.get("blockers", [])
    blockers_html = (
        f'<p class="blockers"><strong>Blockers:</strong> {e(", ".join(blockers))}</p>' if blockers else ""
    )
    flag = (
        '<span class="badge" style="background:#fef2f2;color:#991b1b">⚠ review</span>'
        if bp.get("flagged_injection")
        else ""
    )
    copy_text = e(
        f"Repo: {bp.get('repo')} #{bp.get('number')} — {bp.get('title')}\n"
        f"Problem: {bp.get('problem_summary')}\n"
        f"Approach: {bp.get('suggested_approach')}\n"
        f"Source: {bp.get('source_url')}"
    )
    return f"""
    <article class="card" data-repo="{e(bp.get('repo'))}" data-feas="{e(feas)}">
      <div class="row">
        <span class="repo">{e(bp.get('repo'))}</span>
        <span class="badge" style="{FEAS_BADGE.get(feas, '')}">feasible: {e(feas)}</span>
        <span class="badge" style="background:#eef2ff;color:#3730a3">{e(effort)}</span>
        {'<span class="badge" style="background:#f0fdfa;color:#115e59">self-contained</span>' if bp.get('self_contained') else ''}
        {flag}
      </div>
      <h3>{e(bp.get('title'))} <span class="num">#{e(bp.get('number'))}</span></h3>
      <p class="summary">{e(bp.get('problem_summary'))}</p>
      <p><strong>Likely cause:</strong> {e(bp.get('root_cause_hypothesis'))}</p>
      <p><strong>Approach:</strong> {e(bp.get('suggested_approach'))}</p>
      <div class="chips">{areas}</div>
      {blockers_html}
      <details><summary>How to solve it</summary>
        {'<p class="pre"><strong>You&#39;ll need:</strong></p><ul>' + prereqs + '</ul>' if prereqs else ''}
        <ol>{steps}</ol>
      </details>
      <div class="actions">
        <a class="btn" href="{safe_url(bp.get('source_url',''))}" target="_blank" rel="noopener noreferrer">View issue ↗</a>
        <button class="btn ghost" data-copy="{copy_text}">Copy prompt</button>
      </div>
    </article>"""


def _repo_filters(blueprints: list[dict[str, Any]]) -> str:
    repos = sorted({bp.get("repo", "") for bp in blueprints})
    out = '<button class="filter active" data-filter-repo="all">All repos</button>'
    out += "".join(
        f'<button class="filter" data-filter-repo="{e(r)}">{e(r)}</button>' for r in repos
    )
    return out


def generate(blueprints: list[dict[str, Any]]) -> Path:
    # Hide issues that have since been closed/fixed; highest need first.
    blueprints = [b for b in blueprints if not b.get("resolved")]
    blueprints = sorted(blueprints, key=lambda b: -float(b.get("need_score") or 0))
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "".join(_card(b) for b in blueprints)

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; connect-src https://cdn.tailwindcss.com; img-src 'self' data:; base-uri 'none'; form-action 'none'">
<title>IssueMiner AI</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;margin:0;background:#f8fafc;color:#0f172a}}
  header{{padding:2rem 1.5rem;background:linear-gradient(120deg,#4f46e5,#7c3aed);color:#fff}}
  header h1{{margin:0;font-size:1.6rem}} header p{{margin:.35rem 0 0;opacity:.9;font-size:.9rem}}
  .wrap{{max-width:1100px;margin:0 auto;padding:1.5rem}}
  .filters{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem}}
  .filter{{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:.3rem .8rem;font-size:.8rem;cursor:pointer}}
  .filter.active{{background:#4f46e5;color:#fff;border-color:#4f46e5}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem}}
  .card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:1.1rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
  .card h3{{font-size:1rem;margin:.5rem 0}} .num{{color:#94a3b8;font-weight:400}}
  .row{{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}}
  .repo{{font-size:.75rem;color:#475569;font-weight:600}}
  .badge{{font-size:.7rem;padding:.12rem .5rem;border-radius:999px}}
  .summary{{color:#334155;font-size:.9rem}} p{{font-size:.85rem;line-height:1.45}}
  .blockers{{color:#9a3412}}
  .chips{{display:flex;flex-wrap:wrap;gap:.3rem;margin:.5rem 0}}
  .chip{{font-size:.7rem;background:#f1f5f9;color:#475569;border-radius:6px;padding:.1rem .45rem}}
  details{{margin:.5rem 0;font-size:.85rem}} summary{{cursor:pointer;color:#4f46e5;font-weight:600}}
  ol,ul{{margin:.4rem 0 0 1.1rem}} li{{margin:.2rem 0}} .pre{{margin:.4rem 0 0}}
  .actions{{display:flex;gap:.5rem;margin-top:.8rem}}
  .btn{{font-size:.8rem;padding:.4rem .7rem;border-radius:8px;border:1px solid #4f46e5;background:#4f46e5;color:#fff;text-decoration:none;cursor:pointer}}
  .btn.ghost{{background:#fff;color:#4f46e5}}
  footer{{text-align:center;color:#94a3b8;font-size:.8rem;padding:2rem}}
</style>
</head>
<body>
<header>
  <div class="wrap" style="padding-bottom:0">
    <h1>⛏️ IssueMiner AI</h1>
    <p>Feasible, high-need open issues — with an AI plan for how to solve each · {len(blueprints)} blueprints · updated {e(updated)}</p>
  </div>
</header>
<main class="wrap">
  <div class="filters">{_repo_filters(blueprints)}</div>
  <section class="grid" id="grid">{cards}</section>
</main>
<footer>Generated by IssueMiner AI · blueprints are AI suggestions — verify before contributing</footer>
<script>
  document.querySelectorAll('.filter').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      document.querySelectorAll('.filter').forEach(function(b){{b.classList.remove('active')}});
      btn.classList.add('active');
      var f = btn.getAttribute('data-filter-repo');
      document.querySelectorAll('.card').forEach(function(c){{
        c.style.display = (f === 'all' || c.getAttribute('data-repo') === f) ? '' : 'none';
      }});
    }});
  }});
  document.querySelectorAll('[data-copy]').forEach(function(btn){{
    btn.addEventListener('click', function(){{
      navigator.clipboard.writeText(btn.getAttribute('data-copy'));
      var t = btn.textContent; btn.textContent = 'Copied!';
      setTimeout(function(){{btn.textContent = t}}, 1200);
    }});
  }});
</script>
</body>
</html>"""

    PUBLIC_DIR.mkdir(exist_ok=True)
    out = PUBLIC_DIR / "index.html"
    out.write_text(html_doc, encoding="utf-8")
    return out
