"""Regression tests for the performance / observability work."""
import os
import threading
import time

import groq
from streamlit.testing.v1 import AppTest

from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
from test_units import FakeClient, FakeTavily, Msg, _resp
from verity import reports
from verity.llm import GroqLLM
from verity.models import Claim, Verdict
from verity.pipeline import run_audit
from verity.search import TavilySearch
from verity.verifier import gather_evidence

APP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


def test_progress_reports_completion_counts_including_failures(settings):
    llm = ScriptedLLM(fail_verify_for={"Python was first released in 1985."})
    events = []
    run_audit(build_trap_pdf(), "t.pdf", settings, llm, ScriptedSearch(), lambda *a: events.append(a))
    verify = [e for e in events if e[0] == "verify"]
    assert verify[0][1] == 0 and verify[-1][1] == 13
    assert [e[1] for e in verify] == sorted(e[1] for e in verify)  # monotonic
    assert "1 failed" in verify[-1][3] and "13/13 done" in verify[-1][3]
    assert "pending" in verify[1][3] and "in progress" in verify[1][3]


def test_unexpected_exception_on_one_claim_is_isolated_and_flagged(settings):
    class Boom(ScriptedLLM):
        def complete_json(self, system, user, **kw):
            if "CLAIM: Tesla" in user:
                raise KeyError("weird payload")
            return super().complete_json(system, user, **kw)

    rep = run_audit(build_trap_pdf(), "t.pdf", settings, Boom(), ScriptedSearch())
    assert len(rep.results) == 13 and len(rep.failed_ids) == 1
    bad = next(r for r in rep.results if r.error)
    assert "Tesla" in bad.claim.text and bad.verdict == Verdict.INSUFFICIENT and "KeyError" in bad.error
    assert sum(1 for r in rep.results if not r.error) == 12


def test_metrics_are_measured_and_serialised(settings):
    rep = run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(), ScriptedSearch())
    m = rep.metrics
    assert m["groq_extraction_calls"]["calls"] == 1
    assert m["groq_verification_calls"]["calls"] == 11  # 2 claims had no web results -> no model call needed
    assert m["tavily_calls"]["calls"] == 26 and m["tavily_calls"]["failures"] == 0
    assert m["total_s"] >= m["verification_wall_s"] >= 0 and m["claims"] == 13
    again = type(rep).from_dict(rep.to_dict())
    assert again.metrics == rep.metrics
    assert '"metrics"' in reports.to_json(rep)


def test_failed_calls_counted_in_metrics(settings):
    rep = run_audit(build_trap_pdf(), "t.pdf", settings, ScriptedLLM(raise_kind="rate_limit"), ScriptedSearch())
    assert rep.metrics["claims_failed"] == 11 and rep.metrics["auto_retry"] == {"attempted": 11, "recovered": 0}
    assert rep.metrics["groq_verification_calls"]["failures"] == 22  # first pass + automatic second pass


def test_primary_and_freshness_searches_run_concurrently():
    class Slow:
        def __init__(self):
            self.active = self.peak = 0
            self.lock = threading.Lock()

        def search(self, q, *, max_results=6, depth="advanced"):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.2)
            with self.lock:
                self.active -= 1
            return ScriptedSearch().search(q, max_results=max_results, depth=depth)

    s = Slow()
    t = time.perf_counter()
    ev = gather_evidence(Claim("C01", "x claim here", "q", 1, "statistic", "some query"), s)
    assert s.peak == 2 and time.perf_counter() - t < 0.36 and ev


def test_one_429_pauses_all_threads_via_shared_cooldown():
    rl = groq.RateLimitError("slow", response=_resp(429, {"retry-after": "3"}), body=None)
    sleeps = []
    client = FakeClient([rl, Msg('{"a":1}'), Msg('{"b":2}')])
    llm = GroqLLM(client=client, sleeper=sleeps.append)
    assert llm.complete_json("s", "u") == {"a": 1}
    sleeps.clear()
    assert llm.complete_json("s", "u") == {"b": 2}  # second caller arrives while cooldown is still active
    assert sleeps and sleeps[0] > 1.5
    assert llm.stats["rate_limit_hits"] == 1 and llm.stats["retries"] == 1 and llm.stats["backoff_wait_s"] > 3


def test_token_usage_is_recorded_from_groq_responses():
    m = Msg('{"a":1}')
    m.usage = type("U", (), {"prompt_tokens": 1200, "completion_tokens": 300})()
    llm = GroqLLM(client=FakeClient([m]), sleeper=lambda _: None)
    llm.complete_json("s", "u")
    assert llm.stats["prompt_tokens"] == 1200 and llm.stats["completion_tokens"] == 300 and llm.stats["http_calls"] == 1


def test_tavily_cache_hits_and_timeout_are_applied():
    seen = []

    class C(FakeTavily):
        def search(self, **kw):
            seen.append(kw)
            return super().search(**kw)

    s = TavilySearch(client=C([{"results": [{"url": "https://a.com", "content": "x" * 20, "score": 0.5}]}]), sleeper=lambda _: None)
    s.search("same"); s.search("same")
    assert s.stats["http_calls"] == 1 and s.stats["cache_hits"] == 1 and seen[0]["timeout"] == 30


def test_downloads_are_not_generated_on_render(monkeypatch, tmp_path):
    from verity.config import Settings
    calls = {"pdf": 0}
    real = reports.to_pdf
    monkeypatch.setattr(reports, "to_pdf", lambda r: calls.__setitem__("pdf", calls["pdf"] + 1) or real(r))
    for k in ("GROQ_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERITY_DB_PATH", str(tmp_path / "u.db"))
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=str(tmp_path / "u.db"))
    rep = run_audit(build_trap_pdf(), "t.pdf", s, ScriptedLLM(), ScriptedSearch())
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["report"] = rep
    at.run()
    assert not at.exception and calls["pdf"] == 0


def test_model_selector_defaults_to_120b(monkeypatch, tmp_path):
    for k in ("GROQ_API_KEY", "TAVILY_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERITY_DB_PATH", str(tmp_path / "m.db"))
    at = AppTest.from_file(APP, default_timeout=30).run()
    sb = at.sidebar.selectbox[0]
    assert sb.value == "openai/gpt-oss-120b" and "openai/gpt-oss-20b" in sb.options


def test_progress_ticks_while_waiting_and_reports_rate_limit_status(settings):
    """While every call is slow/throttled the callback must keep firing (elapsed counter alive) and mention the wait."""
    import time as _t

    class Throttled(ScriptedLLM):
        def cooldown_remaining(self):
            return 7.0

        def complete_json(self, system, user, **kw):
            if "CLAIM:" in user:
                _t.sleep(1.6)
            return super().complete_json(system, user, **kw)

    events = []
    run_audit(build_trap_pdf(__import__("fixtures").TRAP_CLAIMS[:2]), "t.pdf", settings, Throttled(), ScriptedSearch(),
              lambda *a: events.append(a))
    verify = [e for e in events if e[0] == "verify"]
    assert len(verify) >= 3  # initial + at least one 1-second tick + completions
    assert any("rate limit, resuming in 7s" in e[3] for e in verify)
