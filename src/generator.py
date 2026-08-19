"""Static site generator — writes public/index.html.

SECURITY: every dynamic value (issue text AND AI output) is treated as untrusted
and HTML-escaped via `e()`. Links are validated to https-only. A Content-Security
-Policy meta tag is defense-in-depth. Even a fully-injected blueprint can only
ever render as plain visible text.

The page answers three questions the earlier version couldn't:
  "is this still open?"  -> resolved issues stay on the page, dimmed + badged,
                            instead of silently vanishing when they get fixed
  "how old is this?"     -> every card carries opened / last-active / analyzed
                            dates, relative for scanning and absolute on hover
  "what's new?"          -> a NEW badge on recent blueprints, plus sort controls
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

# A blueprint written within this many days is flagged NEW.
NEW_AFTER_DAYS = 2
# Upstream-activity thresholds behind the freshness dot on each card.
FRESH_DAYS, SLOWING_DAYS = 30, 180


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def safe_url(url: str) -> str:
    url = (url or "").strip()
    return e(url) if url.lower().startswith("https://") else "#"


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def _dt(iso: str | None) -> datetime | None:
    """Parse an ISO timestamp from any forge (GitHub's Z suffix, Gitea's +02:00)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(iso: str | None) -> float | None:
    dt = _dt(iso)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _rel(iso: str | None) -> str:
    """'5d ago' / '3mo ago' / '2y ago' — coarse on purpose, for scanning."""
    days = _age_days(iso)
    if days is None:
        return "unknown"
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 45:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days / 30)}mo ago"
    years = days / 365
    return f"{years:.1f}y ago" if years < 10 else f"{int(years)}y ago"


def _abs(iso: str | None) -> str:
    """Absolute timestamp for the hover tooltip."""
    dt = _dt(iso)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if dt else "unknown"


def _epoch(iso: str | None) -> int:
    dt = _dt(iso)
    return int(dt.timestamp()) if dt else 0


def _dated(label: str, iso: str | None) -> str:
    """One 'label 5d ago' fact, with the exact timestamp on hover."""
    if not iso:
        return ""
    return f'<span class="fact" title="{e(_abs(iso))}">{e(label)} <b>{e(_rel(iso))}</b></span>'


# --------------------------------------------------------------------------- #
# Cards
# --------------------------------------------------------------------------- #
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

    resolved = bool(bp.get("resolved"))
    status_badge = (
        '<span class="badge status-done">✓ Resolved upstream</span>'
        if resolved
        else '<span class="badge status-open">● Open</span>'
    )

    # NEW tracks first_seen, never processed_at — the 14-day re-analysis cycle
    # rewrites processed_at, which would otherwise re-flag months-old finds.
    added_age = _age_days(bp.get("first_seen") or bp.get("processed_at"))
    is_new = added_age is not None and added_age < NEW_AFTER_DAYS and not resolved
    new_badge = '<span class="badge badge-new">NEW</span>' if is_new else ""

    # Freshness of the upstream conversation, not of our analysis.
    upstream_age = _age_days(bp.get("updated_at"))
    if resolved:
        dot, dot_title = "done", "This issue is closed upstream"
    elif upstream_age is None:
        dot, dot_title = "stale", "No activity date recorded"
    elif upstream_age < FRESH_DAYS:
        dot, dot_title = "fresh", f"Active upstream in the last {FRESH_DAYS} days"
    elif upstream_age < SLOWING_DAYS:
        dot, dot_title = "slowing", f"No upstream activity for over {FRESH_DAYS} days"
    else:
        dot, dot_title = "stale", f"No upstream activity for over {SLOWING_DAYS} days"

    # "added to IssueMiner" is the headline date; the re-analysis date is only
    # worth the space when it actually differs from it.
    first_seen = bp.get("first_seen") or bp.get("processed_at")
    reanalyzed = (
        _dated("re-analyzed", bp.get("processed_at"))
        if bp.get("processed_at") and bp.get("processed_at") != first_seen
        else ""
    )
    facts = " ".join(
        f for f in (
            _dated("opened upstream", bp.get("created_at")),
            _dated("last active", bp.get("updated_at")),
            _dated("resolved", bp.get("resolved_at")) if resolved else "",
            f'<span class="fact added" title="{e(_abs(first_seen))}">'
            f"added here <b>{e(_rel(first_seen))}</b></span>" if first_seen else "",
            reanalyzed,
        ) if f
    )

    copy_text = e(
        f"Repo: {bp.get('repo')} #{bp.get('number')} — {bp.get('title')}\n"
        f"Problem: {bp.get('problem_summary')}\n"
        f"Approach: {bp.get('suggested_approach')}\n"
        f"Source: {bp.get('source_url')}"
    )
    return f"""
    <article class="card{' is-resolved' if resolved else ''}"
             data-repo="{e(bp.get('repo'))}" data-feas="{e(feas)}"
             data-resolved="{'1' if resolved else '0'}"
             data-need="{e(bp.get('need_score') or 0)}"
             data-created="{_epoch(bp.get('created_at'))}"
             data-updated="{_epoch(bp.get('updated_at'))}"
             data-added="{_epoch(first_seen)}">
      <div class="row">
        <span class="dot {dot}" title="{e(dot_title)}"></span>
        <span class="repo">{e(bp.get('repo'))}</span>
        {status_badge}
        {new_badge}
        <span class="badge" style="{FEAS_BADGE.get(feas, '')}">feasible: {e(feas)}</span>
        <span class="badge" style="background:#eef2ff;color:#3730a3">{e(effort)}</span>
        {'<span class="badge" style="background:#f0fdfa;color:#115e59">self-contained</span>' if bp.get('self_contained') else ''}
        {flag}
      </div>
      <h3>{e(bp.get('title'))} <span class="num">#{e(bp.get('number'))}</span></h3>
      <div class="meta">{facts}</div>
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
    counts: dict[str, int] = {}
    for bp in blueprints:
        counts[bp.get("repo", "")] = counts.get(bp.get("repo", ""), 0) + 1
    out = f'<button class="filter active" data-filter-repo="all">All repos <i>{len(blueprints)}</i></button>'
    out += "".join(
        f'<button class="filter" data-filter-repo="{e(r)}">{e(r)} <i>{counts[r]}</i></button>'
        for r in sorted(counts)
    )
    return out


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'">
<title>IssueMiner AI</title>
<style>
  :root{color-scheme:light}
  body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;margin:0;background:#f8fafc;color:#0f172a}
  header{padding:2rem 1.5rem 1.5rem;background:linear-gradient(120deg,#4f46e5,#7c3aed);color:#fff}
  header h1{margin:0;font-size:1.6rem} header p{margin:.35rem 0 0;opacity:.9;font-size:.9rem}
  .stats{display:flex;flex-wrap:wrap;gap:1.2rem;margin-top:.9rem;font-size:.8rem}
  .stats b{display:block;font-size:1.15rem;font-weight:700}
  .stats span{opacity:.85}
  .wrap{max-width:1100px;margin:0 auto;padding:1.5rem}
  .controls{display:flex;flex-direction:column;gap:.5rem;margin-bottom:1.2rem}
  .filters{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
  .flabel{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:#64748b;font-weight:700;min-width:3.6rem}
  .filter{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:.3rem .8rem;font-size:.8rem;cursor:pointer;color:#0f172a}
  .filter i{font-style:normal;opacity:.55;font-size:.72rem;margin-left:.15rem}
  .filter.active{background:#4f46e5;color:#fff;border-color:#4f46e5}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem}
  .card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:1.1rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}
  .card.is-resolved{opacity:.62;background:#fbfdfb;border-color:#d1fae5}
  .card.is-resolved h3{text-decoration:line-through;text-decoration-color:#94a3b8}
  .card h3{font-size:1rem;margin:.5rem 0} .num{color:#94a3b8;font-weight:400}
  .row{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
  .repo{font-size:.75rem;color:#475569;font-weight:600}
  .badge{font-size:.7rem;padding:.12rem .5rem;border-radius:999px}
  .status-open{background:#eff6ff;color:#1d4ed8;font-weight:600}
  .status-done{background:#dcfce7;color:#166534;font-weight:600}
  .badge-new{background:#fb923c;color:#fff;font-weight:700;letter-spacing:.03em}
  .dot{width:.5rem;height:.5rem;border-radius:50%;flex:0 0 auto}
  .dot.fresh{background:#22c55e} .dot.slowing{background:#f59e0b}
  .dot.stale{background:#cbd5e1} .dot.done{background:#166534}
  .meta{display:flex;flex-wrap:wrap;gap:.15rem .7rem;font-size:.72rem;color:#64748b;
        margin:.1rem 0 .6rem;padding-bottom:.55rem;border-bottom:1px dashed #e2e8f0}
  .meta .fact{white-space:nowrap;cursor:help} .meta b{color:#334155;font-weight:600}
  .meta .added{color:#4338ca} .meta .added b{color:#4338ca}
  .summary{color:#334155;font-size:.9rem} p{font-size:.85rem;line-height:1.45}
  .blockers{color:#9a3412}
  .chips{display:flex;flex-wrap:wrap;gap:.3rem;margin:.5rem 0}
  .chip{font-size:.7rem;background:#f1f5f9;color:#475569;border-radius:6px;padding:.1rem .45rem}
  details{margin:.5rem 0;font-size:.85rem} summary{cursor:pointer;color:#4f46e5;font-weight:600}
  ol,ul{margin:.4rem 0 0 1.1rem} li{margin:.2rem 0} .pre{margin:.4rem 0 0}
  .actions{display:flex;gap:.5rem;margin-top:.8rem}
  .btn{font-size:.8rem;padding:.4rem .7rem;border-radius:8px;border:1px solid #4f46e5;background:#4f46e5;color:#fff;text-decoration:none;cursor:pointer}
  .btn.ghost{background:#fff;color:#4f46e5}
  #empty{display:none;text-align:center;color:#64748b;padding:3rem 1rem;font-size:.9rem}
  footer{text-align:center;color:#94a3b8;font-size:.8rem;padding:2rem}
  .legend{font-size:.72rem;color:#64748b;margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.9rem;align-items:center}
  .legend .dot{display:inline-block;margin-right:.25rem;vertical-align:middle}
</style>
</head>
<body>
<header>
  <div class="wrap" style="padding-bottom:0">
    <h1>⛏️ IssueMiner AI</h1>
    <p>Feasible, high-need open issues — with an AI plan for how to solve each</p>
    <div class="stats">
      <div><b>__OPEN__</b><span>open blueprints</span></div>
      <div><b>__RESOLVED__</b><span>resolved upstream</span></div>
      <div><b>__NEW__</b><span>added in last __NEWDAYS__ days</span></div>
      <div><b>__REPOS__</b><span>projects tracked</span></div>
      <div><b>__UPDATED__</b><span>last mined</span></div>
    </div>
  </div>
</header>
<main class="wrap">
  <div class="controls">
    <div class="filters"><span class="flabel">Project</span>__REPOFILTERS__</div>
    <div class="filters"><span class="flabel">Status</span>
      <button class="filter active" data-filter-status="open">Open <i>__OPEN__</i></button>
      <button class="filter" data-filter-status="resolved">Resolved <i>__RESOLVED__</i></button>
      <button class="filter" data-filter-status="all">All <i>__TOTAL__</i></button>
    </div>
    <div class="filters"><span class="flabel">Sort</span>
      <button class="filter active" data-sort="need">Most needed</button>
      <button class="filter" data-sort="updated">Recently active</button>
      <button class="filter" data-sort="added">Newest to IssueMiner</button>
      <button class="filter" data-sort="created">Oldest issue</button>
    </div>
    <div class="legend">
      <span><span class="dot fresh"></span>active &lt;__FRESH__d</span>
      <span><span class="dot slowing"></span>quiet &lt;__SLOWING__d</span>
      <span><span class="dot stale"></span>stale</span>
      <span><span class="dot done"></span>closed upstream</span>
      <span>· hover any date for the exact timestamp</span>
    </div>
  </div>
  <section class="grid" id="grid">__CARDS__</section>
  <div id="empty">No issues match these filters.</div>
</main>
<footer>Generated by IssueMiner AI · blueprints are AI suggestions — verify before contributing<br>
Dates reflect the last mining run, not live upstream state.</footer>
<script>
(function(){
  var grid = document.getElementById('grid');
  var empty = document.getElementById('empty');
  var state = {repo:'all', status:'open', sort:'need'};

  function num(card, attr){ return parseFloat(card.getAttribute(attr)) || 0; }

  function apply(){
    var cards = Array.prototype.slice.call(grid.querySelectorAll('.card'));
    var shown = 0;
    cards.forEach(function(c){
      var isResolved = c.getAttribute('data-resolved') === '1';
      var okRepo = state.repo === 'all' || c.getAttribute('data-repo') === state.repo;
      var okStatus = state.status === 'all'
        || (state.status === 'open' && !isResolved)
        || (state.status === 'resolved' && isResolved);
      var visible = okRepo && okStatus;
      c.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });
    empty.style.display = shown ? 'none' : 'block';

    cards.sort(function(a, b){
      // Resolved items always sink, whichever sort is active.
      var ra = a.getAttribute('data-resolved') === '1' ? 1 : 0;
      var rb = b.getAttribute('data-resolved') === '1' ? 1 : 0;
      if (ra !== rb) return ra - rb;
      if (state.sort === 'created') {
        // Ascending (oldest first), but a missing date is stored as 0 — push
        // those to the end instead of letting them masquerade as the oldest.
        var ca = num(a,'data-created') || Infinity, cb = num(b,'data-created') || Infinity;
        return ca - cb;
      }
      return num(b, 'data-' + state.sort) - num(a, 'data-' + state.sort);
    });
    cards.forEach(function(c){ grid.appendChild(c); });
  }

  function wire(attr, key){
    document.querySelectorAll('[' + attr + ']').forEach(function(btn){
      btn.addEventListener('click', function(){
        document.querySelectorAll('[' + attr + ']').forEach(function(b){ b.classList.remove('active'); });
        btn.classList.add('active');
        state[key] = btn.getAttribute(attr);
        apply();
      });
    });
  }
  wire('data-filter-repo', 'repo');
  wire('data-filter-status', 'status');
  wire('data-sort', 'sort');
  apply();

  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click', function(){
      navigator.clipboard.writeText(btn.getAttribute('data-copy'));
      var t = btn.textContent; btn.textContent = 'Copied!';
      setTimeout(function(){ btn.textContent = t; }, 1200);
    });
  });
})();
</script>
</body>
</html>"""


def generate(blueprints: list[dict[str, Any]]) -> Path:
    """Render every stored blueprint — including resolved ones, which stay
    visible (dimmed, badged, sorted last) so a fixed issue reads as 'fixed'
    rather than silently disappearing from the page."""
    blueprints = sorted(blueprints, key=lambda b: -float(b.get("need_score") or 0))
    resolved = [b for b in blueprints if b.get("resolved")]
    open_ = [b for b in blueprints if not b.get("resolved")]
    fresh = [
        b for b in open_
        if (age := _age_days(b.get("first_seen") or b.get("processed_at"))) is not None
        and age < NEW_AFTER_DAYS
    ]
    repos = {b.get("repo", "") for b in blueprints}

    doc = TEMPLATE
    for key, val in {
        "__CARDS__": "".join(_card(b) for b in open_ + resolved),
        "__REPOFILTERS__": _repo_filters(blueprints),
        "__OPEN__": str(len(open_)),
        "__RESOLVED__": str(len(resolved)),
        "__NEW__": str(len(fresh)),
        "__NEWDAYS__": str(NEW_AFTER_DAYS),
        "__TOTAL__": str(len(blueprints)),
        "__REPOS__": str(len(repos)),
        "__UPDATED__": e(datetime.now(timezone.utc).strftime("%b %d")),
        "__FRESH__": str(FRESH_DAYS),
        "__SLOWING__": str(SLOWING_DAYS),
    }.items():
        doc = doc.replace(key, val)

    PUBLIC_DIR.mkdir(exist_ok=True)
    out = PUBLIC_DIR / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out
