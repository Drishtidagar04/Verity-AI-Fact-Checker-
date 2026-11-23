"""Plotly charts sharing one dark theme and the verdict colour system."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..models import AuditReport, VERDICT_ORDER
from .theme import CYAN, MUTED, NOT_CHECKED_COLOR, TEXT, VERDICT_COLORS, VIOLET

_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color=TEXT, size=13),
    margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(color=MUTED)),
    hoverlabel=dict(bgcolor="#0F1738", font_color=TEXT),
)


def _style(fig: go.Figure, title: str, height: int = 320) -> go.Figure:
    fig.update_layout(**_LAYOUT, title=dict(text=title, font=dict(size=15, family="Space Grotesk, Inter, sans-serif", color=TEXT), x=0), height=height)
    fig.update_xaxes(gridcolor="rgba(255,255,255,.06)", zeroline=False, color=MUTED)
    fig.update_yaxes(gridcolor="rgba(255,255,255,.06)", zeroline=False, color=MUTED)
    return fig


def verdict_donut(counts: dict[str, int], title: str = "Verdict mix") -> go.Figure:
    labels = [v.label for v in VERDICT_ORDER]
    values = [counts.get(v.value, 0) for v in VERDICT_ORDER]
    colors = [VERDICT_COLORS[v.value] for v in VERDICT_ORDER]
    if counts.get("NOT CHECKED"):
        labels.append("Not checked (API)"); values.append(counts["NOT CHECKED"]); colors.append(NOT_CHECKED_COLOR)
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.62, sort=False, textinfo="value", textfont=dict(color="#060A1C", size=14),
        marker=dict(colors=colors, line=dict(color="#060A1C", width=3)),
        hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
    ))
    total = sum(values)
    fig.add_annotation(text=f"<b>{total}</b><br><span style='font-size:11px;color:{MUTED}'>claims</span>",
                       showarrow=False, font=dict(size=24, family="Space Grotesk"))
    return _style(fig, title)


def category_bars(report_or_df, title: str = "Verdicts by claim type") -> go.Figure:
    df = _frame(report_or_df)
    fig = go.Figure()
    if not df.empty:
        pivot = df.groupby(["category", "verdict"]).size().unstack(fill_value=0)
        for v in VERDICT_ORDER:
            if v.value in pivot:
                fig.add_bar(x=[c.replace("_", " ") for c in pivot.index], y=pivot[v.value], name=v.label,
                            marker_color=VERDICT_COLORS[v.value], hovertemplate="%{x}: %{y}<extra>" + v.label + "</extra>")
    fig.update_layout(barmode="stack")
    return _style(fig, title)


def strength_hist(report_or_df, title: str = "Evidence strength distribution") -> go.Figure:
    df = _frame(report_or_df)
    fig = go.Figure(go.Histogram(x=df["strength"] if not df.empty else [], xbins=dict(start=0, end=100, size=10),
                                 marker=dict(color=VIOLET, line=dict(color="#060A1C", width=2)),
                                 hovertemplate="Score %{x}: %{y} claims<extra></extra>"))
    fig.update_xaxes(range=[0, 100], title="Evidence strength (0–100)")
    fig.update_yaxes(title="Claims")
    return _style(fig, title)


def trend(audits: list[dict], title: str = "Verified rate per audit") -> go.Figure:
    rows = [a for a in audits if a["n_claims"]][::-1]
    fig = go.Figure(go.Scatter(
        x=[a["created_at"][:16].replace("T", " ") for a in rows], y=[a["verified"] / a["n_claims"] * 100 for a in rows],
        mode="lines+markers", line=dict(color=CYAN, width=3), marker=dict(size=9, color=VIOLET, line=dict(color=CYAN, width=2)),
        text=[a["filename"] for a in rows], hovertemplate="%{text}<br>%{y:.0f}% verified<extra></extra>"))
    fig.update_yaxes(range=[0, 105], title="% verified")
    return _style(fig, title)


def top_domains(df: pd.DataFrame, title: str = "Most-cited source domains") -> go.Figure:
    counts: dict[str, int] = {}
    for d in df["domains"].fillna(""):
        for dom in filter(None, d.split(",")):
            counts[dom] = counts.get(dom, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:10][::-1]
    fig = go.Figure(go.Bar(x=[v for _, v in top], y=[k for k, _ in top], orientation="h", marker_color=CYAN,
                           hovertemplate="%{y}: cited in %{x} claims<extra></extra>"))
    return _style(fig, title)


def _frame(report_or_df) -> pd.DataFrame:
    if isinstance(report_or_df, pd.DataFrame):
        return report_or_df
    rep: AuditReport = report_or_df
    return pd.DataFrame([{"category": r.claim.category, "verdict": r.verdict.value,
                          "strength": r.strength.score if r.strength else 0} for r in rep.results if not r.error],
                        columns=["category", "verdict", "strength"])
