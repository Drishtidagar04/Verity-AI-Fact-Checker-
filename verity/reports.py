"""Downloadable audit reports: machine-readable JSON and a formatted PDF."""
from __future__ import annotations

import io
import json
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import APP_NAME
from .models import AuditReport, ClaimResult, Verdict

SCHEMA_VERSION = "1.0"

_VERDICT_COLORS = {
    Verdict.VERIFIED: "#059669", Verdict.INACCURATE: "#B45309",
    Verdict.FALSE: "#DC2626", Verdict.INSUFFICIENT: "#475569",
}
_PUNCT = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
          " ": " ", "•": "-", "→": "->", "≈": "~", "≥": ">=", "≤": "<="}


def _t(text: str | None) -> str:
    """Make text safe for the built-in Helvetica font and for reportlab's XML-ish paragraphs."""
    s = str(text or "")
    for k, v in _PUNCT.items():
        s = s.replace(k, v)
    s = s.encode("latin-1", "replace").decode("latin-1")
    return escape(s)


def to_json(report: AuditReport) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generator": APP_NAME,
        "summary": {
            "claims": len(report.results),
            "counts": report.counts(),
            "not_checked": report.not_checked,
            "verified_rate": report.verified_rate,
        },
        "audit": report.to_dict(),
        "notes": (
            "evidence_strength is computed from cited-source signals (count, authority tier, retrieval relevance, "
            "quote grounding, consistency); it is not the probability that a verdict is correct. "
            "model_confidence is the model's own statement and is reported separately."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def to_pdf(report: AuditReport) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Verity AI audit - {report.filename}", author=APP_NAME)
    ss = getSampleStyleSheet()
    navy, violet = colors.HexColor("#0B1030"), colors.HexColor("#7C3AED")
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=navy, fontSize=22, alignment=TA_LEFT, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], textColor=colors.HexColor("#475569"), fontSize=9)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=violet, fontSize=13, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8.2, leading=11, textColor=colors.HexColor("#334155"))
    claim_st = ParagraphStyle("claim", parent=body, fontSize=10.5, leading=14, textColor=navy)

    story = [Paragraph(f"{APP_NAME} - Fact-Check Audit", h1),
             Paragraph(_t(f"{report.filename} | {report.pages} pages | model {report.model} | {report.created_at} UTC"), sub),
             Paragraph(_t(f"Source SHA-256: {report.sha256}"), sub),
             HRFlowable(width="100%", color=violet, thickness=1.2, spaceBefore=6, spaceAfter=8)]

    counts = report.counts()
    rate = report.verified_rate
    rows = [["Claims", "Verified", "Inaccurate", "False", "Insufficient", "Not checked", "Verified rate"],
            [len(report.results), counts["VERIFIED"], counts["INACCURATE"], counts["FALSE"],
             counts["INSUFFICIENT EVIDENCE"], report.not_checked, f"{rate * 100:.0f}%" if rate is not None else "n/a"]]
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t, Spacer(1, 4)]
    for w in report.warnings:
        story.append(Paragraph(_t(f"Note: {w}"), small))

    story.append(Paragraph("Findings", h2))
    for r in sorted(report.results, key=lambda r: (r.verdict.severity, r.claim.id)):
        story.append(_claim_block(r, body, small, claim_st))

    story += [Spacer(1, 8), HRFlowable(width="100%", color=colors.HexColor("#CBD5E1")),
              Paragraph(_t("Evidence strength reflects the number, authority and relevance of cited sources and whether "
                           "quoted text was found in the retrieved snippet. It is not the probability that a verdict is "
                           "correct. Verdicts are produced by an AI model from live web evidence and should be reviewed "
                           "by a human before publication."), small)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(18 * mm, 9 * mm, f"{APP_NAME} audit {report.id}")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _claim_block(r: ClaimResult, body, small, claim_st):
    col = _VERDICT_COLORS[r.verdict]
    head = (f'<font color="{col}"><b>{"NOT CHECKED (API PROBLEM)" if r.error else _t(r.verdict.label.upper())}</b></font> &nbsp; '
            f'<font color="#64748B">{_t(r.claim.id)} | {_t(r.claim.category)} | page {r.claim.page}</font>')
    parts = [Paragraph(head, body), Paragraph(_t(r.claim.text), claim_st)]
    if r.corrected_fact:
        parts.append(Paragraph(f"<b>Correct fact:</b> {_t(r.corrected_fact)}", body))
    if r.explanation:
        parts.append(Paragraph(_t(r.explanation), body))
    if r.strength:
        mc = f" | model-stated confidence: {r.model_confidence}" if r.model_confidence else ""
        flags = (" | CONTRADICTORY EVIDENCE" if r.contradictory else "") + (" | OUTDATED FIGURE" if r.outdated else "")
        parts.append(Paragraph(_t(f"Evidence strength: {r.strength.score}/100 ({r.strength.label}){mc}{flags}"), small))
    for c, s in r.cited_sources():
        q = f' - "{_t(c.quote)}"' if c.quote else ""
        parts.append(Paragraph(f'[{_t(c.stance)}] <a href="{escape(s.url, {chr(34): "&quot;"})}" color="#4F46E5">{_t(s.title or s.domain)}</a> ({_t(s.domain)}){q}', small))
    if r.error:
        parts.append(Paragraph(_t(f"Verification error: {r.error}"), small))
    parts += [Spacer(1, 3), HRFlowable(width="100%", color=colors.HexColor("#E2E8F0"), thickness=0.5), Spacer(1, 5)]
    return KeepTogether(parts)
