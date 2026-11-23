"""End-to-end pipeline on the synthetic 13-claim trap document (test doubles for LLM + search)."""
import json

import pytest

from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
from verity import reports
from verity.models import AuditReport, Verdict
from verity.pdf import PDFError
from verity.pipeline import AuditError, retry_failed, run_audit


@pytest.fixture
def report(settings):
    return run_audit(build_trap_pdf(), "trap.pdf", settings, ScriptedLLM(), ScriptedSearch())


def by_text(report, fragment):
    return next(r for r in report.results if fragment in r.claim.text)


def test_extracts_all_13_claims(report):
    assert len(report.results) == 13
    assert [r.claim.id for r in report.results] == [f"C{i:02d}" for i in range(1, 14)]
    assert report.pages == 1 and report.sha256


def test_all_four_verdict_classes_produced(report):
    c = report.counts()
    assert c["VERIFIED"] == 4
    assert c["INACCURATE"] == 3  # 2 outdated + 1 conflicting
    assert c["FALSE"] == 4
    assert c["INSUFFICIENT EVIDENCE"] == 2


def test_no_evidence_means_insufficient_never_false(report):
    r = by_text(report, "Zeta-Index")
    assert r.verdict == Verdict.INSUFFICIENT and r.strength.score == 0 and r.strength.label == "None"
    assert r.corrected_fact is None


def test_overreach_with_evidence_but_no_citations_downgraded(settings):
    claims = [("Acme Corp's internal customer NPS reached 73 in Q2.", "none")]
    rep = run_audit(build_trap_pdf(claims), "x.pdf", settings, ScriptedLLM(), ScriptedSearch(empty_for=()))
    r = rep.results[0]
    assert r.verdict == Verdict.INSUFFICIENT
    assert "did not tie its conclusion" in r.explanation


def test_phantom_citations_are_discarded_and_ungrounded_quotes_flagged(report):
    r = by_text(report, "Python was first released")
    assert r.verdict == Verdict.FALSE
    assert [c.source_idx for c in r.citations] == [1]  # source 99 does not exist
    assert r.citations[0].quote_matched is False  # invented quote not in snippet
    assert r.strength.factors["grounding"] == 0


def test_verified_claims_have_grounded_quotes_and_strength(report):
    r = by_text(report, "Eiffel Tower")
    assert r.verdict == Verdict.VERIFIED and all(c.quote_matched for c in r.citations)
    assert r.strength.score > 0 and r.strength.label in ("Moderate", "Strong")
    for _, ev in r.cited_sources():
        assert ev.url.startswith("https://")


def test_contradictory_evidence_flagged_and_reduces_consistency(report):
    r = by_text(report, "smartphone shipments")
    assert r.contradictory is True
    assert r.strength.factors["consistency"] == 0


def test_outdated_flag(report):
    assert by_text(report, "7.5 billion").outdated is True
    assert by_text(report, "7.5 billion").corrected_fact


def test_search_uses_live_queries_per_claim(settings):
    s = ScriptedSearch()
    run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(), s)
    assert len(s.queries) == 26  # two searches (primary + freshness) for each of 13 claims


def test_json_report_roundtrip(report):
    data = json.loads(reports.to_json(report))
    assert data["summary"]["claims"] == 13
    again = AuditReport.from_dict(data["audit"])
    assert again.counts() == report.counts()
    assert again.results[0].strength.score == report.results[0].strength.score


def test_pdf_report_generates(report):
    pdf = reports.to_pdf(report)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 3000


def test_pdf_report_survives_hostile_text(report):
    report.results[0].explanation = "<b>unclosed & “smart” ☃ <script>"
    assert reports.to_pdf(report)[:5] == b"%PDF-"


def test_rate_limited_claim_is_recovered_by_automatic_second_pass(settings):
    llm = ScriptedLLM(fail_verify_for={"Python was first released in 1985."})
    rep = run_audit(build_trap_pdf(), "t.pdf", settings, llm, ScriptedSearch())
    assert rep.failed_ids == [] and rep.results[3].verdict == Verdict.FALSE and rep.not_checked == 0
    assert rep.metrics["auto_retry"] == {"attempted": 1, "recovered": 1}


def test_persistent_failures_are_flagged_not_checked_and_manual_retry_recovers(settings):
    class Flaky(ScriptedLLM):
        outage = True

        def complete_json(self, system, user, **kw):
            if self.outage and "CLAIM: Python" in user:
                from verity.llm import LLMError
                raise LLMError("Groq rate limit reached.", "rate_limit")
            return super().complete_json(system, user, **kw)

    llm = Flaky()
    rep = run_audit(build_trap_pdf(), "t.pdf", settings, llm, ScriptedSearch())
    assert rep.failed_ids == ["C04"] and rep.not_checked == 1
    r = rep.results[3]
    assert r.error_kind == "rate_limit" and "rate limit" in r.error
    assert sum(rep.counts().values()) == 12  # the failed claim is NOT counted as 'insufficient evidence'
    assert rep.counts()["INSUFFICIENT EVIDENCE"] == 2  # only the two genuinely unverifiable claims
    assert rep.verified_rate == pytest.approx(4 / 12)
    assert any("Retry failed claims" in w for w in rep.warnings)
    llm.outage = False
    rep = retry_failed(rep, settings, llm, ScriptedSearch())
    assert rep.failed_ids == [] and rep.results[3].verdict == Verdict.FALSE and rep.verified_rate == pytest.approx(4 / 13)


def test_auth_error_aborts_instead_of_burning_quota(settings):
    with pytest.raises(AuditError):
        run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(raise_kind="auth"), ScriptedSearch())


def test_search_auth_error_aborts(settings):
    with pytest.raises(AuditError):
        run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(), ScriptedSearch(raise_kind="auth"))


def test_search_outage_gives_flagged_results_not_crash(settings):
    rep = run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(), ScriptedSearch(raise_kind="network"))
    assert len(rep.failed_ids) == 13 and all(r.verdict == Verdict.INSUFFICIENT for r in rep.results)


def test_claim_cap_warns(settings):
    from dataclasses import replace
    rep = run_audit(build_trap_pdf(), "t.pdf", replace(settings, max_claims=5), ScriptedLLM(), ScriptedSearch())
    assert len(rep.results) == 5 and any("first 5" in w for w in rep.warnings)


def test_bad_pdfs_raise_friendly_errors(settings):
    for blob in (b"", b"not a pdf at all", b"%PDF-1.4 garbage"):
        with pytest.raises(PDFError):
            run_audit(blob, "x.pdf", settings, ScriptedLLM(), ScriptedSearch())


def test_progress_callback_reports_every_claim(settings):
    events = []
    run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(), ScriptedSearch(), lambda *a: events.append(a))
    assert [e for e in events if e[0] == "verify"][-1][1:3] == (13, 13)
    assert events[-1][0] == "done"
