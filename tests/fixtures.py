"""Test doubles + a synthetic 13-claim 'trap' document.

IMPORTANT: this is NOT the assessor's trap document (which was not provided). The scripted LLM/search below
exist only to exercise the pipeline's plumbing and guardrails deterministically; the production app contains
no hard-coded answers. Live accuracy must be judged by running the real app with real API keys.
"""
from __future__ import annotations

import io
import re

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from verity.models import Evidence

# (claim text in document, scenario)  scenario: verified | outdated | false | none | conflict
TRAP_CLAIMS = [
    ("The Eiffel Tower is located in Paris, France.", "verified"),
    ("Apple became the first US company to reach a $3 trillion market cap in January 2022.", "verified"),
    ("The world population is 7.5 billion people.", "outdated"),
    ("Python was first released in 1985.", "false"),
    ("India has 38 states and 8 union territories.", "outdated"),
    ("Tesla delivered 1.8 million vehicles in 2019.", "false"),
    ("The Great Wall of China is visible from the Moon with the naked eye.", "false"),
    ("Acme Corp's internal customer NPS reached 73 in Q2.", "none"),
    ("Global smartphone shipments were 1.2 billion units in 2023.", "conflict"),
    ("The speed of light is 299,792 kilometres per second.", "verified"),
    ("ChatGPT launched publicly in November 2022.", "verified"),
    ("Bitcoin's maximum supply is 25 million coins.", "false"),
    ("The company's proprietary Zeta-Index grew 412% last year.", "none"),
]


def build_trap_pdf(claims=TRAP_CLAIMS) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y, page = 800, 1
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Q3 Market Brief (synthetic trap document)")
    y -= 40
    c.setFont("Helvetica", 11)
    for i, (text, _) in enumerate(claims, 1):
        c.drawString(50, y, f"{i}. {text}")
        y -= 34
        if y < 80:
            c.showPage(); c.setFont("Helvetica", 11); y, page = 800, page + 1
    c.save()
    return buf.getvalue()


def scenario_for(claim_text: str) -> str:
    for text, sc in TRAP_CLAIMS:
        if text.lower().rstrip(".") in claim_text.lower() or claim_text.lower().rstrip(".") in text.lower():
            return sc
    return "none"


class ScriptedLLM:
    """Simulates the model: extraction = one claim per numbered line; verification follows the scenario."""

    def __init__(self, fail_verify_for: set[str] | None = None, raise_kind: str | None = None):
        self.calls = 0
        self.fail_verify_for = fail_verify_for or set()
        self.raise_kind = raise_kind

    def complete_json(self, system, user, *, max_tokens=4096):
        self.calls += 1
        if "claim-extraction stage" in system:
            claims = []
            for m in re.finditer(r"\[Page (\d+)\]|^(\d+)\. (.+)$", user, re.M):
                pass
            page = 1
            for line in user.splitlines():
                pm = re.match(r"\[Page (\d+)\]", line)
                if pm:
                    page = int(pm.group(1))
                    continue
                nm = re.match(r"^\d+\. (.+)$", line.strip())
                if nm:
                    t = nm.group(1)
                    claims.append({"claim": t, "quote": t, "category": "statistic", "page": page,
                                   "search_query": " ".join(t.split()[:8])})
            return {"claims": claims}

        claim = re.search(r"CLAIM: (.+)", user).group(1)
        if self.raise_kind:
            from verity.llm import LLMError
            raise LLMError("boom", self.raise_kind)
        if claim in self.fail_verify_for:
            from verity.llm import LLMError
            self.fail_verify_for.discard(claim)
            raise LLMError("Groq rate limit reached.", "rate_limit")
        sc = scenario_for(claim)
        snip = {i: self._snippet(user, i) for i in (1, 2, 3)}
        if sc == "verified":
            return {"verdict": "VERIFIED", "corrected_fact": None, "explanation": "Sources agree.",
                    "citations": [{"source": 1, "stance": "supports", "quote": snip[1][:80]},
                                  {"source": 2, "stance": "supports", "quote": snip[2][:80]}],
                    "model_confidence": "high", "contradictory_evidence": False, "outdated": False}
        if sc == "outdated":
            return {"verdict": "INACCURATE", "corrected_fact": "Updated figure from source.", "explanation": "Superseded.",
                    "citations": [{"source": 1, "stance": "updates", "quote": snip[1][:80]}],
                    "model_confidence": "medium", "contradictory_evidence": False, "outdated": True}
        if sc == "false":
            return {"verdict": "FALSE", "corrected_fact": "The documented fact.", "explanation": "Contradicted.",
                    "citations": [{"source": 1, "stance": "contradicts", "quote": "text that is not in the snippet at all"},
                                  {"source": 99, "stance": "contradicts", "quote": "phantom source"}],
                    "model_confidence": "high", "contradictory_evidence": False, "outdated": False}
        if sc == "conflict":
            return {"verdict": "INACCURATE", "corrected_fact": "Range of figures.", "explanation": "Sources conflict.",
                    "citations": [{"source": 1, "stance": "supports", "quote": snip[1][:60]},
                                  {"source": 2, "stance": "contradicts", "quote": snip[2][:60]}],
                    "model_confidence": "low", "contradictory_evidence": True, "outdated": False}
        # 'none': model overreaches with a verdict but cites nothing -> guardrail must downgrade
        return {"verdict": "FALSE", "corrected_fact": "Invented.", "explanation": "No idea.", "citations": [],
                "model_confidence": "high"}

    @staticmethod
    def _snippet(user, i):
        m = re.search(rf"\[{i}\] [^\n]*\n([^\n]+)", user)
        return m.group(1) if m else ""


class ScriptedSearch:
    def __init__(self, empty_for: tuple[str, ...] = ("Zeta", "NPS", "internal"), raise_kind: str | None = None):
        self.empty_for = empty_for
        self.raise_kind = raise_kind
        self.queries: list[str] = []

    def search(self, query, *, max_results=6, depth="advanced"):
        from verity.search import SearchError
        self.queries.append(query)
        if self.raise_kind:
            raise SearchError("nope", self.raise_kind)
        if any(k.lower() in query.lower() for k in self.empty_for):
            return []
        base = abs(hash(query.split(" latest")[0])) % 10_000
        out = []
        for i, dom in enumerate(["en.wikipedia.org", "www.nasa.gov", "example-blog.com"], 1):
            out.append(Evidence(idx=i, title=f"Result {i}", url=f"https://{dom}/page-{base}-{i}", domain=dom.replace("www.", ""),
                                snippet=f"Evidence text number {i} about {query.split(' latest')[0]} with details and figures.",
                                score=0.9 - 0.1 * i))
        return out
