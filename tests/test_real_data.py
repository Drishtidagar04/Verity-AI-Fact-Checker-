"""Regression tests built from the user's REAL v1.0 / v1.1 audit exports (Groq + Tavily, free tier)."""
import json
import os

import pytest

from verity import reports
from verity.models import AuditReport
from verity.verifier import apply_guardrails, quote_in_snippet

DATA = os.path.join(os.path.dirname(__file__), "data")


def load(name):
    return AuditReport.from_dict(json.load(open(os.path.join(DATA, name)))["audit"])


def test_real_v11_run_loads_and_summarises():
    rep = load("real_run_v11.json")
    assert len(rep.results) == 13 and rep.not_checked == 0
    assert rep.counts() == {"VERIFIED": 4, "INACCURATE": 3, "FALSE": 5, "INSUFFICIENT EVIDENCE": 1}
    assert rep.metrics["groq_client"]["rate_limit_hits"] == 28  # real free-tier behaviour
    assert reports.to_pdf(rep)[:5] == b"%PDF-"


def test_real_v10_export_still_loads_with_failed_claims_as_not_checked():
    rep = load("real_run_v10.json")
    assert rep.not_checked == 6 and rep.counts()["INSUFFICIENT EVIDENCE"] == 1
    assert rep.verified_rate == pytest.approx(3 / 7)


def test_every_real_model_citation_is_a_verbatim_fragment_of_the_retrieved_text():
    """v1.1 flagged 7/21 real citations as 'unmatched' because the model joins fragments with '...'.
    The ellipsis-aware matcher must verify all of them, and must still reject an invented quote."""
    rep = load("real_run_v11.json")
    total = ok = 0
    for r in rep.results:
        by = {s.idx: s for s in r.sources}
        for c in r.citations:
            total += 1
            ok += quote_in_snippet(c.quote, by[c.source_idx].snippet, by[c.source_idx].title)
    assert total == 21 and ok == 21
    snippet = rep.results[0].sources[0].snippet
    assert not quote_in_snippet("The Eiffel Tower was moved to Berlin in 1999", snippet, "")
    assert not quote_in_snippet("", snippet, "") and not quote_in_snippet("...", snippet, "")


def test_ellipsis_fragments_must_all_be_present():
    snip = "The tower is 330 m tall. It opened in 1889 and stands in Paris."
    assert quote_in_snippet("The tower is 330 m tall ... stands in Paris", snip)
    assert not quote_in_snippet("The tower is 330 m tall ... stands in Berlin", snip)


def test_title_quotes_are_accepted():
    assert quote_in_snippet("World Population Clock: 8.3 Billion People", "unrelated text here", "World Population Clock: 8.3 Billion People (LIVE, 2026)")


def test_guardrails_use_new_matcher_and_grounding_counts():
    from verity.models import Claim, Evidence
    ev = [Evidence(1, "T", "https://a.org/x", "a.org", "Alpha is 5 units. Beta is 7 units across the region.", 0.8)]
    data = {"verdict": "FALSE", "corrected_fact": "Beta is 7 units.", "explanation": "x",
            "citations": [{"source": 1, "stance": "contradicts", "quote": "Alpha is 5 units ... Beta is 7 units"}]}
    r = apply_guardrails(Claim("C01", "Beta is 9 units", "q", 1, "statistic", "q"), data, ev)
    assert r.citations[0].quote_matched and r.strength.factors["grounding"] == 10


def test_prompt_requires_corrected_fact_for_inaccurate_and_false():
    from verity.verifier import SYSTEM
    assert "REQUIRED for INACCURATE and FALSE" in SYSTEM
