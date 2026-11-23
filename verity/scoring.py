"""Evidence-strength scoring.

The score is computed ONLY from observable signals about the sources the verdict actually cites. It is not
a probability that the verdict is correct, and the model's own stated confidence is displayed separately
and never mixed in. Every component is exposed so the UI can show the breakdown.

Components (max points):
  source_count   35  distinct cited domains (3+ = full marks)
  source_quality 25  authority tier of cited domains (heuristic: official/academic/major reference = high)
  relevance      20  mean Tavily relevance score of cited results
  grounding      10  share of citations whose quoted text was found verbatim in the retrieved snippet
  consistency    10  cited sources agree (0 if supporting and contradicting sources are both cited)
"""
from __future__ import annotations

from .models import Citation, Evidence, Strength

MAXIMUMS = {"source_count": 35.0, "source_quality": 25.0, "relevance": 20.0, "grounding": 10.0, "consistency": 10.0}

_HIGH_SUFFIX = (".gov", ".edu", ".mil", ".int", ".gov.uk", ".gov.in", ".nic.in", ".ac.uk", ".ac.in", ".europa.eu", ".gc.ca", ".gov.au")
_HIGH = {
    "who.int", "worldbank.org", "imf.org", "oecd.org", "un.org", "data.worldbank.org", "sec.gov",
    "nature.com", "science.org", "nih.gov", "reuters.com", "apnews.com", "bloomberg.com", "statista.com",
    "federalreserve.gov", "ecb.europa.eu", "iea.org", "ourworldindata.org",
}
_MID = {
    "wikipedia.org", "en.wikipedia.org", "britannica.com", "bbc.com", "bbc.co.uk", "nytimes.com", "wsj.com",
    "ft.com", "economist.com", "forbes.com", "cnbc.com", "theguardian.com", "techcrunch.com", "theverge.com",
    "wired.com", "washingtonpost.com", "investopedia.com", "crunchbase.com", "macrotrends.net", "nasa.gov",
}


_LOW = {"medium.com", "blogspot.com", "wordpress.com", "substack.com", "tumblr.com", "quora.com", "reddit.com", "youtube.com"}


def authority_tier(domain: str) -> float:
    d = (domain or "").lower()
    if d in _LOW or any(d.endswith("." + x) for x in _LOW):
        return 0.2
    if d in _HIGH or d.endswith(_HIGH_SUFFIX) or any(d.endswith("." + h) for h in _HIGH):
        return 1.0
    if d in _MID or any(d.endswith("." + m) for m in _MID):
        return 0.7
    return 0.45 if d else 0.0


def label_for(score: int) -> str:
    if score <= 0:
        return "None"
    if score >= 70:
        return "Strong"
    if score >= 45:
        return "Moderate"
    return "Weak"


def compute_strength(citations: list[Citation], sources: list[Evidence]) -> Strength:
    by_idx = {s.idx: s for s in sources}
    used = [(c, by_idx[c.source_idx]) for c in citations if c.source_idx in by_idx]
    if not used:
        zero = {k: 0.0 for k in MAXIMUMS}
        return Strength(score=0, label="None", factors=zero, maximums=dict(MAXIMUMS))

    domains = {e.domain for _, e in used}
    f_count = MAXIMUMS["source_count"] * min(len(domains), 3) / 3
    tiers = [authority_tier(d) for d in domains]
    f_quality = MAXIMUMS["source_quality"] * (sum(tiers) / len(tiers))
    f_rel = MAXIMUMS["relevance"] * (sum(e.score for _, e in used) / len(used))
    f_ground = MAXIMUMS["grounding"] * (sum(1 for c, _ in used if c.quote_matched) / len(used))
    stances = {c.stance for c, _ in used}
    conflict = "contradicts" in stances and "supports" in stances
    f_cons = 0.0 if conflict else MAXIMUMS["consistency"]

    factors = {
        "source_count": round(f_count, 1), "source_quality": round(f_quality, 1),
        "relevance": round(f_rel, 1), "grounding": round(f_ground, 1), "consistency": round(f_cons, 1),
    }
    score = int(round(sum(factors.values())))
    return Strength(score=score, label=label_for(score), factors=factors, maximums=dict(MAXIMUMS))
