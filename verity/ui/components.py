"""HTML renderers. EVERY dynamic string is html-escaped: claims, quotes and sources are untrusted."""
from __future__ import annotations

from html import escape

from ..models import AuditReport, ClaimResult
from ..search import safe_http_url
from .theme import NOT_CHECKED_COLOR, VERDICT_COLORS, VERDICT_ICONS


def e(x) -> str:
    return escape(str(x if x is not None else ""), quote=True)


def hero() -> str:
    return """
<section class="hero" aria-label="Verity AI introduction">
  <span class="eyebrow">● Truth layer for your content</span>
  <h1>Catch the <span class="grad">stale stats</span> and fabricated facts before you publish.</h1>
  <p>Upload a PDF. Verity AI extracts every checkable claim, tests it against live web evidence, and returns
  a verdict with the corrected fact, source links and a transparent evidence-strength score.</p>
  <div class="pills"><span class="pill">Live web evidence</span><span class="pill">Source-linked verdicts</span>
  <span class="pill">Outdated-stat detection</span><span class="pill">Audit-ready PDF &amp; JSON</span></div>
</section>"""


def steps() -> str:
    items = [("01", "Extract", "An LLM pulls statistics, dates and financial or technical figures out of your PDF."),
             ("02", "Verify", "Each claim is searched on the live web; only retrieved sources can support a verdict."),
             ("03", "Report", "Verified, Inaccurate, False or Insufficient Evidence, with corrections and citations.")]
    cells = "".join(f'<div class="step"><div class="step-n">STEP {n}</div><h4>{t}</h4><p>{d}</p></div>' for n, t, d in items)
    return f'<div class="steps">{cells}</div>'


def section(title: str) -> str:
    return f'<div class="section-title"><h3>{e(title)}</h3></div>'


def metrics(report: AuditReport) -> str:
    c = report.counts()
    rate = report.verified_rate
    cells = [
        ("", "Claims checked", len(report.results)),
        ("ok", "Verified", c["VERIFIED"]), ("warn", "Inaccurate", c["INACCURATE"]),
        ("bad", "False", c["FALSE"]), ("none", "Insufficient", c["INSUFFICIENT EVIDENCE"]),
    ]
    if report.not_checked:
        cells.append(("nc", "Not checked", report.not_checked))
    cells.append(("", "Verified rate", f"{rate * 100:.0f}%" if rate is not None else "–"))
    html = "".join(f'<div class="metric {cls}"><div class="k">{k}</div><div class="v">{v}</div></div>' for cls, k, v in cells)
    return f'<div class="metrics" role="list">{html}</div>'


def notice(text: str) -> str:
    return f'<div class="notice" role="status">{e(text)}</div>'


def verdict_card(r: ClaimResult) -> str:
    v = r.verdict.value
    color = NOT_CHECKED_COLOR if r.error else VERDICT_COLORS[v]
    label, icon = ("Not checked", "↻") if r.error else (r.verdict.label, VERDICT_ICONS[v])
    flags = ""
    if r.cached_at:
        flags += '<span class="chip" title="Identical claim verified earlier today with live sources; reused to save API quota">⚡ Reused today\'s result</span>'
    if r.contradictory:
        flags += '<span class="chip flag">⚠ Contradictory evidence</span>'
    if r.outdated:
        flags += '<span class="chip flag">⏳ Outdated statistic</span>'
    if r.error:
        flags += '<span class="chip flag">API problem – not a verdict</span>'
    quote = ""
    if r.claim.quote and r.claim.quote.strip().lower() != r.claim.text.strip().lower():
        quote = f'<div class="vc-quote">In document: “{e(r.claim.quote)}”</div>'
    correct = (f'<div class="vc-correct"><div class="lab">Correct fact</div>{e(r.corrected_fact)}</div>'
               if r.corrected_fact else "")
    if not r.corrected_fact and not r.error and v in ("FALSE", "INACCURATE"):
        correct = ('<div class="vc-quote">No single corrected value was extracted from the sources; '
                   'see the explanation and the evidence below.</div>')
    meter = ""
    if r.strength:
        s = r.strength
        mc = f'<span class="chip" title="Stated by the model; not used in the strength score">Model-stated confidence: {e(r.model_confidence)}</span>' if r.model_confidence else ""
        meter = (f'<div class="meter-row"><div class="meter" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{s.score}" '
                 f'aria-label="Evidence strength">'
                 f'<div class="lab"><span>Evidence strength · {e(s.label)}</span><span>{s.score}/100</span></div>'
                 f'<div class="track"><div class="fill" style="width:{s.score}%"></div></div></div>{mc}</div>')
    return (
        f'<article class="vc" style="--accent:{color}" aria-label="Claim {e(r.claim.id)}: {e(label)}">'
        f'<div class="vc-head"><span class="badge"><span aria-hidden="true">{icon}</span>{e(label)}</span>'
        f'<span class="chip">{e(r.claim.category.replace("_", " "))}</span><span class="chip">Page {e(r.claim.page)}</span>{flags}'
        f'<span class="vc-id">{e(r.claim.id)}</span></div>'
        f'<p class="vc-claim">{e(r.claim.text)}</p>{quote}{correct}'
        f'<p class="vc-expl">{e(r.explanation)}</p>{meter}</article>'
    )


def _source_html(title, url, domain, extra="", body="") -> str:
    link = f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer">{e(title or domain)}</a>' if safe_http_url(url) else e(title)
    return f'<div class="src"><div class="t">{extra}{link}</div><div class="d">{e(domain)}</div>{body}</div>'


def sources_html(r: ClaimResult) -> str:
    out = []
    cited = r.cited_sources()
    cited_idx = {s.idx for _, s in cited}
    for c, s in cited:
        stance = f'<span class="stance {e(c.stance)}">{e(c.stance)}</span>'
        if c.quote and c.quote_matched:
            body = f'<div class="q">“{e(c.quote)}”</div>'
        else:
            body = f'<div class="q">{e(s.snippet[:260])}…</div><div class="nq">Snippet shown; the model’s quoted excerpt could not be matched verbatim.</div>'
        out.append(_source_html(s.title, s.url, s.domain, stance, body))
    others = [s for s in r.sources if s.idx not in cited_idx]
    if others:
        out.append('<div class="d" style="margin:.6rem 0 .2rem">Also retrieved (not cited)</div>')
        for s in others:
            out.append(_source_html(s.title, s.url, s.domain, "", f'<div class="q">{e(s.snippet[:200])}…</div>'))
    if not out:
        out.append('<div class="d">No web sources were retrieved for this claim.</div>')
    return "".join(out)


def strength_breakdown(r: ClaimResult) -> str:
    if not r.strength:
        return ""
    labels = {"source_count": "Independent sources", "source_quality": "Source authority (heuristic)",
              "relevance": "Search relevance", "grounding": "Quote found in source", "consistency": "Sources agree"}
    rows = "".join(
        f'<div class="meter" style="margin:.35rem 0"><div class="lab"><span>{labels[k]}</span><span>{v:g}/{r.strength.maximums[k]:g}</span></div>'
        f'<div class="track"><div class="fill" style="width:{(v / r.strength.maximums[k] * 100) if r.strength.maximums[k] else 0:.0f}%"></div></div></div>'
        for k, v in r.strength.factors.items())
    return rows + '<div class="d" style="margin-top:.4rem">Computed from the cited sources only. It is not the probability that the verdict is correct.</div>'
