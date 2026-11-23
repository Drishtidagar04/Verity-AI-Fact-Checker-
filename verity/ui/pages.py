"""Streamlit pages."""
from __future__ import annotations

import uuid

import streamlit as st

from .. import APP_NAME, __version__, reports
from ..config import Settings
from ..db import AuditDB
from ..models import AuditReport, VERDICT_ORDER, Verdict
from ..jobs import MANAGER
from ..pipeline import AuditError, retry_failed
from . import charts, components as ui

NAV = ["Fact-check", "History", "Analytics", "Methodology"]


def workspace_id() -> str:
    """Anonymous per-visitor workspace kept in the URL so a refresh keeps the audit history."""
    ws = st.query_params.get("ws")
    if not ws or len(ws) > 40 or not ws.replace("-", "").isalnum():
        ws = uuid.uuid4().hex[:16]
        st.query_params["ws"] = ws
    return ws


def get_services(settings: Settings):
    override = st.session_state.get("_services_override")  # test hook
    if override:
        return override
    from ..services import build_llm, build_search

    return build_llm(settings), build_search(settings)


MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def sidebar(settings: Settings) -> tuple[str, str]:
    with st.sidebar:
        st.markdown('<div class="brand"><div class="brand-mark">V</div><div><div class="brand-name">Verity AI</div>'
                    '<div class="brand-tag">FACT-CHECK INTELLIGENCE</div></div></div>', unsafe_allow_html=True)
        if "_goto" in st.session_state:  # set by other pages; applied BEFORE the radio widget is created
            st.session_state["nav"] = st.session_state.pop("_goto")
        page = st.radio("Navigate", NAV, label_visibility="collapsed", key="nav")
        st.divider()
        for name, ok in (("Groq LLM", bool(settings.groq_api_key)), ("Tavily search", bool(settings.tavily_api_key))):
            st.markdown(f'<div class="keystat"><span class="dot {"on" if ok else "off"}"></span>{name}: '
                        f'{"connected" if ok else "key missing"}</div>', unsafe_allow_html=True)
        options = MODELS if settings.model in MODELS else [settings.model] + MODELS
        model = st.selectbox("Groq model", options, index=options.index(settings.model),
                             help="120B is the accuracy default; 20B is faster and cheaper but less careful on subtle claims.")
        st.caption(f"v{__version__}")
    return page, model


# ---------------------------------------------------------------- fact-check
def page_check(settings: Settings, db: AuditDB, ws: str) -> None:
    job = MANAGER.get(ws)
    active = job is not None or st.session_state.get("report") is not None
    if not active:
        st.markdown(ui.hero(), unsafe_allow_html=True)
    else:
        st.markdown('<div class="hero-compact">🛡️ <b>Verity AI</b> · Fact-check intelligence</div>', unsafe_allow_html=True)

    if not settings.keys_ready:
        st.markdown(
            '<div class="setup"><b>Setup required.</b> Missing: ' + ", ".join(f"<code>{m}</code>" for m in settings.missing_keys)
            + '. Add them as environment variables or in Streamlit <i>Secrets</i> (see README). Keys are never shown in the UI.</div>',
            unsafe_allow_html=True)

    st.markdown(ui.section("Upload a document"), unsafe_allow_html=True)
    up = st.file_uploader("Drop a text-based PDF here", type=["pdf"], accept_multiple_files=False,
                          help=f"Up to {settings.max_upload_mb} MB · first {settings.max_pages} pages are analysed · scanned/image-only PDFs are not supported")
    busy = job is not None and job.state in ("running", "queued")
    run = st.button("Run fact-check", type="primary", disabled=(up is None or not settings.keys_ready or busy), width="stretch")

    if run and up is not None:
        try:
            llm, searcher = get_services(settings)
        except Exception as exc:
            st.error(f"Could not initialise the AI services: {exc}")
        else:
            err = try_start(settings, db, ws, up.name, up.getvalue(), llm, searcher)
            if err:
                st.warning(err)
            else:
                st.session_state.pop("report", None)
                st.rerun()

    if not busy and st.session_state.get("report") is None:
        from ..sample import build_sample_pdf
        st.download_button("⬇ Download the 13-claim sample document to try", build_sample_pdf, file_name="verity_sample_13_claims.pdf",
                           mime="application/pdf", help="A synthetic test document with true, false, outdated and unverifiable claims.")

    _job_panel(ws)

    report: AuditReport | None = st.session_state.get("report")
    if report is None:
        st.markdown(ui.steps(), unsafe_allow_html=True)
        return
    if st.button("＋ New audit", key="new_audit"):
        st.session_state.pop("report", None)
        st.rerun()
    render_report(report, settings, db, ws)


def try_start(settings: Settings, db: AuditDB, ws: str, filename: str, data: bytes, llm, searcher) -> str | None:
    """Quota check + start. Returns a user-facing error message, or None when the audit was started."""
    if (msg := check_quota(settings, db, ws)):
        return msg
    if MANAGER.start(ws, filename, data, settings, llm, searcher, db) is None:
        return "An audit is already running for this workspace."
    db.record_run(ws)
    return None


def check_quota(settings: Settings, db: AuditDB, ws: str) -> str | None:
    """Returns a user-facing message when the daily audit budget is used up, else None."""
    if settings.max_audits_per_workspace_day and db.runs_since(24, ws) >= settings.max_audits_per_workspace_day:
        return (f"Daily limit reached ({settings.max_audits_per_workspace_day} audits per workspace per 24 h). "
                "This keeps the shared API credits available for everyone. Try again later.")
    if settings.max_audits_per_day and db.runs_since(24) >= settings.max_audits_per_day:
        return "The app's daily audit budget is used up. Please try again later."
    return None


@st.fragment(run_every=1.0)
def _job_panel(ws: str) -> None:
    """Live progress for the background audit. Re-renders every second; hands over to the full app when done."""
    job = MANAGER.get(ws)
    if job is None:
        return
    snap = job.snapshot()
    if snap["state"] in ("running", "queued"):
        frac = {"read": 0.03, "extract": 0.12}.get(snap["stage"])
        if snap["stage"] == "verify":
            frac = 0.25 + 0.6 * snap["done"] / max(snap["total"], 1)
        elif snap["stage"] == "retry":
            frac = 0.85 + 0.14 * snap["done"] / max(snap["total"], 1)
        st.progress(min(frac if frac is not None else 0.05, 0.99), text=f"{snap['message']} · {snap['elapsed']:.0f}s")
        if snap["partial"]:
            st.markdown(ui.section(f"Finished so far ({len(snap['partial'])})"), unsafe_allow_html=True)
            for r in snap["partial"][-5:]:
                lab = "Not checked" if r.error else r.verdict.label
                st.markdown(f"- **{r.claim.id}** · {lab} · {r.claim.text[:110]}")
        st.caption(f"Auditing **{snap['filename']}** in the background. You can leave this tab open or come back "
                   "to the same link; the finished report is saved to your history.")
        return
    if snap["state"] == "error":
        st.error(snap["error"])
        MANAGER.clear(ws)
        return
    st.session_state["report"] = job.report
    MANAGER.clear(ws)
    st.rerun()  # full app rerun so results render outside the fragment


def render_report(report: AuditReport, settings: Settings, db: AuditDB, ws: str) -> None:
    st.markdown(ui.section(f"Results · {report.filename}"), unsafe_allow_html=True)
    for w in report.warnings:
        st.markdown(ui.notice(w), unsafe_allow_html=True)
    st.markdown(ui.metrics(report), unsafe_allow_html=True)

    if report.failed_ids and settings.keys_ready:
        if st.button(f"Retry {len(report.failed_ids)} failed claim(s)", key="retry"):
            llm, searcher = get_services(settings)
            with st.spinner("Retrying…"):
                try:
                    retry_failed(report, settings, llm, searcher)
                    db.save(ws, report)
                except AuditError as exc:
                    st.error(f"Retry stopped: {exc}")
            st.rerun()

    if not report.results:
        st.markdown('<div class="empty">No checkable claims were found in this document.</div>', unsafe_allow_html=True)
        return

    c1, c2 = st.columns([1, 1.4])
    with c1:
        counts = report.counts()
        if report.not_checked:
            counts["NOT CHECKED"] = report.not_checked
        st.plotly_chart(charts.verdict_donut(counts), width="stretch", key="donut")
    with c2:
        st.plotly_chart(charts.category_bars(report), width="stretch", key="cat")

    d1, d2, _ = st.columns([1, 1, 2])
    # callables: the PDF/JSON are generated only when clicked, not on every Streamlit rerun
    d1.download_button("⬇ PDF report", lambda: reports.to_pdf(report), f"verity-audit-{report.id}.pdf", "application/pdf", width="stretch")
    d2.download_button("⬇ JSON report", lambda: reports.to_json(report), f"verity-audit-{report.id}.json", "application/json", width="stretch")
    _perf_panel(report)

    st.markdown(ui.section("Claim-by-claim findings"), unsafe_allow_html=True)
    f1, f2 = st.columns([2, 1])
    labels = [v.label for v in VERDICT_ORDER] + (["Not checked"] if report.not_checked else [])
    shown = f1.multiselect("Filter by verdict", labels, default=labels, key="vf")
    order = f2.selectbox("Sort", ["Most serious first", "Document order"], key="sort")
    items = [r for r in report.results if (("Not checked" if r.error else r.verdict.label) in shown)]
    items.sort(key=(lambda r: (r.verdict.severity, r.claim.id)) if order.startswith("Most") else (lambda r: (r.claim.page, r.claim.id)))
    if not items:
        st.markdown('<div class="empty">No claims match the selected filters.</div>', unsafe_allow_html=True)
    for r in items:
        st.markdown(ui.verdict_card(r), unsafe_allow_html=True)
        with st.expander(f"Evidence & sources · {r.claim.id}"):
            st.markdown(ui.sources_html(r), unsafe_allow_html=True)
            if r.strength:
                st.markdown("**How evidence strength was computed**")
                st.markdown(ui.strength_breakdown(r), unsafe_allow_html=True)


def _perf_panel(report: AuditReport) -> None:
    m = report.metrics
    if not m:
        return
    with st.expander("⏱ Performance & API diagnostics (measured for this audit)"):
        c = st.columns(4)
        c[0].metric("Total", f"{m.get('total_s', report.duration_s)}s")
        c[1].metric("PDF read", f"{m.get('pdf_extract_s', 0)}s")
        c[2].metric("Claim extraction", f"{m.get('claim_extraction_s', 0)}s")
        c[3].metric("Verification (wall)", f"{m.get('verification_wall_s', 0)}s")
        names = {"groq_extraction_calls": "Groq · claim extraction", "groq_verification_calls": "Groq · verification",
                 "tavily_calls": "Tavily · searches"}
        rows = [{"Stage": names[k], "Calls": int(v["calls"]), "Failed": int(v["failures"]),
                 "Total time (s)": f"{v['cumulative_s']:.1f}", "Avg per call (s)": f"{v['avg_s']:.1f}",
                 "Slowest (s)": f"{v['max_s']:.1f}"} for k in names if (v := m.get(k))]
        if rows:
            st.table(rows)
        g, t = m.get("groq_client"), m.get("tavily_client")
        if g:
            st.caption(f"Groq: {g['http_calls']} HTTP calls · {g['retries']} retries · {g['rate_limit_hits']} rate-limit (429) hits · "
                       f"{g['backoff_wait_s']}s spent waiting · {g['prompt_tokens']} prompt ({g.get('cached_tokens', 0)} cached) + {g['completion_tokens']} completion tokens")
        if t:
            st.caption(f"Tavily: {t['http_calls']} HTTP calls · {t['cache_hits']} cache hits · {t['retries']} retries · {t['backoff_wait_s']}s backoff")
        st.caption(f"Model {m.get('model')} · {m.get('workers')} parallel workers · DB save {m.get('db_save_s', 'n/a')}s. "
                   "Cumulative call times can exceed wall time because calls run in parallel.")


# ------------------------------------------------------------------- history
def page_history(settings: Settings, db: AuditDB, ws: str) -> None:
    st.markdown("## Audit history")
    st.caption("Audits are stored in this app's SQLite database and scoped to your private workspace link.")
    audits = db.list_audits(ws)
    if not audits:
        st.markdown('<div class="empty">No audits yet. Run your first fact-check.</div>', unsafe_allow_html=True)
        return
    for a in audits:
        with st.container(border=True):
            c = st.columns([3, 1, 1, 1, 1, 1, 1.4])
            c[0].markdown(f"**{ui.e(a['filename'])}**  \n<span style='color:#A3ADCB;font-size:.8rem'>{a['created_at'][:16].replace('T', ' ')} UTC · {a['pages']} pages</span>", unsafe_allow_html=True)
            c[1].metric("Verified", a["verified"])
            c[2].metric("Inaccurate", a["inaccurate"])
            c[3].metric("False", a["false_n"])
            c[4].metric("Insuff.", a["insufficient"])
            c[5].metric("Not checked", a["not_checked"])
            if c[6].button("Open", key=f"open_{a['id']}", width="stretch"):
                rep = db.get(ws, a["id"])
                if rep:
                    st.session_state["report"] = rep
                    st.session_state["_goto"] = "Fact-check"
                    st.rerun()
            if c[6].button("Delete", key=f"del_{a['id']}", width="stretch"):
                db.delete(ws, a["id"])
                cur = st.session_state.get("report")
                if cur is not None and cur.id == a["id"]:
                    st.session_state.pop("report", None)
                st.rerun()


# ----------------------------------------------------------------- analytics
def page_analytics(settings: Settings, db: AuditDB, ws: str) -> None:
    st.markdown("## Analytics")
    audits = db.list_audits(ws)
    df_all = db.claims_frame(ws)
    df = df_all[df_all["verdict"] != "NOT CHECKED"]
    if df.empty:
        st.markdown('<div class="empty">Analytics appear after your first audit.</div>', unsafe_allow_html=True)
        return
    totals = {v.value: int((df["verdict"] == v.value).sum()) for v in VERDICT_ORDER}
    k = st.columns(4)
    k[0].metric("Audits", len(audits))
    k[1].metric("Claims checked", len(df), help=f"{len(df_all) - len(df)} more could not be checked (API problems)" if len(df_all) != len(df) else None)
    k[2].metric("Verified rate", f"{totals[Verdict.VERIFIED.value] / len(df) * 100:.0f}%")
    k[3].metric("Flagged (inaccurate + false)", totals["INACCURATE"] + totals["FALSE"])
    a, b = st.columns(2)
    a.plotly_chart(charts.verdict_donut(totals, "All-time verdict mix"), width="stretch", key="a1")
    b.plotly_chart(charts.category_bars(df), width="stretch", key="a2")
    c, d = st.columns(2)
    c.plotly_chart(charts.strength_hist(df), width="stretch", key="a3")
    d.plotly_chart(charts.trend(audits), width="stretch", key="a4")
    if df["domains"].fillna("").str.len().sum():
        st.plotly_chart(charts.top_domains(df), width="stretch", key="a5")


# --------------------------------------------------------------- methodology
def page_method(settings: Settings, db: AuditDB, ws: str) -> None:
    st.markdown("## How Verity AI decides")
    st.markdown(f"""
**1. Extract.** A language model (`{settings.model}` on Groq) reads the PDF in page-aware chunks and lists each
checkable claim (statistic, date, financial or technical figure) with its exact quote and a neutral search query.
Quotes are matched back to the PDF to find the true page number.

**2. Retrieve.** Every claim triggers two live Tavily searches: a primary deep query and a freshness query aimed at
the latest official figures, so outdated numbers can be spotted. Nothing is cached across sessions.

**3. Judge, evidence-only.** The model sees *only* the retrieved snippets, today's date and the claim. It must cite
the numbered sources it relied on. Code then enforces guardrails:

- a verdict other than *Insufficient Evidence* with no real, non-neutral citation is downgraded;
- citations to sources that don't exist are discarded;
- quoted excerpts are checked verbatim against the snippet and flagged when they don't match;
- if the web returns nothing, the claim is **Insufficient Evidence**. It is never called false for lack of data.

**Verdicts.** **Verified** – evidence confirms it. **Inaccurate** – partly right or outdated; the corrected figure is shown.
**False** – evidence contradicts it or shows the entity/event isn't real. **Insufficient evidence** – can't be decided from public sources
(the brief's "no evidence found" case).

**Evidence strength (0–100).** Computed in code from the cited sources: independent domains (35), source-authority tier (25, a transparent
domain heuristic), search relevance (20), verbatim quote grounding (10) and agreement between sources (10). It measures *how well-supported
the verdict is*, not the probability it is right. The model's self-reported confidence is shown separately.

**Limits.** Web snippets can be wrong or paywalled, and the model can still misread them. Treat Verity AI as a fast first-pass auditor and review flagged items before publishing.
Scanned PDFs need OCR first, and claims beyond the configured page/claim limits are skipped (a warning tells you).
""")
    st.caption(f"{APP_NAME} v{__version__}")
