"""Background jobs, token-saving and source-quality regressions."""
import threading
import time

import pytest

from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
from test_units import FakeTavily
from verity.db import AuditDB
from verity.jobs import JobManager
from verity.models import Evidence
from verity.scoring import authority_tier
from verity.search import EXCLUDED_DOMAINS, TavilySearch
from verity.verifier import SYSTEM, _clip, format_evidence


def wait(job, timeout=10):
    t = time.time()
    while job.state == "running" and time.time() - t < timeout:
        time.sleep(0.02)
    return job


def test_job_runs_in_background_saves_and_exposes_progress(settings):
    m, db = JobManager(), AuditDB(settings.db_path)
    seen = []

    class Slow(ScriptedSearch):
        def search(self, q, **kw):
            time.sleep(0.02)
            return super().search(q, **kw)

    job = m.start("w1", "trap.pdf", build_trap_pdf(), settings, ScriptedLLM(), Slow(), db)
    assert job.state in ("running", "done")
    while job.state == "running":
        sn = job.snapshot()
        seen.append((sn["stage"], sn["done"]) if sn["stage"] == "verify" else ("-", 0))
    wait(job)
    assert job.state == "done" and len(job.report.results) == 13 and job.error is None
    assert db.get("w1", job.report.id) is not None  # persisted even if nobody is watching
    assert job.report.metrics["db_save_s"] >= 0
    verify_done = [d for st, d in seen if st == "verify"]
    assert verify_done == sorted(verify_done)
    assert job.snapshot()["elapsed"] > 0


def test_only_one_running_job_per_workspace(settings):
    m, db = JobManager(), AuditDB(settings.db_path)
    gate = threading.Event()

    class Blocked(ScriptedLLM):
        def complete_json(self, system, user, **kw):
            gate.wait(5)
            return super().complete_json(system, user, **kw)

    j1 = m.start("w", "a.pdf", build_trap_pdf(), settings, Blocked(), ScriptedSearch(), db)
    assert m.start("w", "b.pdf", build_trap_pdf(), settings, ScriptedLLM(), ScriptedSearch(), db) is None
    other = m.start("w2", "c.pdf", build_trap_pdf(), settings, ScriptedLLM(), ScriptedSearch(), db)
    assert other is not None
    m.clear("w")  # must not clear a running job
    assert m.get("w") is j1
    gate.set()
    wait(j1); wait(other)
    m.clear("w")
    assert m.get("w") is None
    assert m.start("w", "again.pdf", build_trap_pdf(), settings, ScriptedLLM(), ScriptedSearch(), db) is not None


@pytest.mark.parametrize("data,llm,expect", [
    (b"not a pdf", ScriptedLLM(), "does not look like a PDF"),
    (None, ScriptedLLM(raise_kind="auth"), "Audit stopped"),
])
def test_job_errors_are_reported_not_stuck(settings, data, llm, expect):
    m = JobManager()
    job = m.start("w", "x.pdf", data or build_trap_pdf(), settings, llm, ScriptedSearch(), AuditDB(settings.db_path), blocking=True)
    assert job.state == "error" and expect in job.error and job.finished is not None


def test_unexpected_exception_does_not_leave_job_running(settings):
    class Bad:
        def complete_json(self, *a, **k):
            raise ZeroDivisionError("bug")

    job = JobManager().start("w", "x.pdf", build_trap_pdf(), settings, Bad(), ScriptedSearch(), AuditDB(settings.db_path), blocking=True)
    assert job.state == "error" and "ZeroDivisionError" in job.error


# ---- token saving / source quality
def test_snippets_are_clipped_at_word_boundary_and_cut_prompt_size():
    text = "word " * 400
    c = _clip(text, 550)
    assert len(c) <= 551 and c.endswith("…") and not c[:-1].endswith("wor")
    ev = [Evidence(i, "t", f"https://x{i}.com", f"x{i}.com", "alpha beta gamma " * 60, 0.5) for i in range(1, 9)]
    assert len(format_evidence(ev, 550)) < len(format_evidence(ev, 900)) * 0.75
    assert _clip("short", 550) == "short"


def test_ugc_domains_excluded_from_search_and_low_authority():
    seen = []

    class C(FakeTavily):
        def search(self, **kw):
            seen.append(kw)
            return super().search(**kw)

    TavilySearch(client=C([{"results": []}]), sleeper=lambda _: None).search("q")
    assert seen[0]["exclude_domains"] == EXCLUDED_DOMAINS and "youtube.com" in EXCLUDED_DOMAINS
    assert authority_tier("medium.com") == 0.2 and authority_tier("blog.medium.com") == 0.2
    assert authority_tier("nasa.gov") >= 0.7 and authority_tier("data.worldbank.org") == 1.0


def test_prompt_requires_corrected_fact_for_inaccurate_and_false():
    assert 'REQUIRED' in SYSTEM and "INACCURATE and FALSE" in SYSTEM
