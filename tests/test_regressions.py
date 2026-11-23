"""Regressions found in the user's real run (v1.0): History->Open crash, 429 handling, unchecked claims."""
import os
import sqlite3
import threading
import time

import groq
import pytest
from streamlit.testing.v1 import AppTest

from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
from test_units import FakeClient, Msg, _resp
from verity import reports
from verity.config import Settings
from verity.db import AuditDB
from verity.llm import GroqLLM, LLMError
from verity.pipeline import run_audit
from verity.ui import components as ui

APP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("GROQ_API_KEY", "TAVILY_API_KEY", "GROQ_MODEL"):
        monkeypatch.delenv(k, raising=False)
    path = str(tmp_path / "r.db")
    monkeypatch.setenv("VERITY_DB_PATH", path)
    return path


def test_history_open_button_does_not_crash_and_shows_report(env):
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=env, retry_pass_delay_s=0)
    rep = run_audit(build_trap_pdf(), "trap.pdf", s, ScriptedLLM(), ScriptedSearch())
    AuditDB(env).save("wsH", rep)
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["ws"] = "wsH"
    at.session_state["nav"] = "History"
    at.run()
    assert not at.exception
    [b for b in at.button if b.label == "Open"][0].click()
    at.run()
    assert not at.exception  # was StreamlitWidgetAlreadyInstantiatedError
    assert at.session_state["nav"] == "Fact-check"
    assert " ".join(m.value for m in at.markdown).count('class="vc"') == 13


def test_old_v10_database_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE audits (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, filename TEXT NOT NULL,
        created_at TEXT NOT NULL, model TEXT, pages INTEGER, n_claims INTEGER, verified INTEGER, inaccurate INTEGER,
        false_n INTEGER, insufficient INTEGER, duration_s REAL, sha256 TEXT, report_json TEXT NOT NULL);
        CREATE TABLE claims (audit_id TEXT NOT NULL, claim_id TEXT NOT NULL, page INTEGER, category TEXT, verdict TEXT,
        strength INTEGER, n_cited INTEGER, domains TEXT, PRIMARY KEY (audit_id, claim_id));
        INSERT INTO audits VALUES ('a','w','old.pdf','2026-01-01T00:00:00',NULL,1,3,1,1,0,1,1.0,'','{}');""")
    con.commit(); con.close()
    db = AuditDB(path)
    assert db.list_audits("w")[0]["not_checked"] == 0
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=path, retry_pass_delay_s=0)
    db.save("w", run_audit(build_trap_pdf(), "n.pdf", s, ScriptedLLM(), ScriptedSearch()))
    assert len(db.list_audits("w")) == 2


def test_real_v10_report_json_still_loads():
    """A v1.0 export (no error_kind/metrics fields) must keep loading."""
    from verity.models import AuditReport
    s = Settings(groq_api_key="x", tavily_api_key="y", retry_pass_delay_s=0)
    d = run_audit(build_trap_pdf(), "n.pdf", s, ScriptedLLM(), ScriptedSearch()).to_dict()
    d.pop("metrics"); [r.pop("error_kind") for r in d["results"]]
    assert len(AuditReport.from_dict(d).results) == 13


def test_not_checked_card_pdf_and_json(settings):
    class Down(ScriptedLLM):
        def complete_json(self, system, user, **kw):
            if "CLAIM: Tesla" in user:
                raise LLMError("Groq rate limit reached.", "rate_limit")
            return super().complete_json(system, user, **kw)

    rep = run_audit(build_trap_pdf(), "t.pdf", settings, Down(), ScriptedSearch())
    bad = next(r for r in rep.results if r.error)
    html = ui.verdict_card(bad)
    assert "Not checked" in html and "API problem" in html and "Insufficient" not in html
    assert '"not_checked": 1' in reports.to_json(rep)
    assert reports.to_pdf(rep)[:5] == b"%PDF-"
    assert "Not checked" in ui.metrics(rep)


def test_many_429s_are_waited_out_instead_of_failing_after_four_attempts():
    rl = lambda: groq.RateLimitError("slow", response=_resp(429, {"retry-after": "2"}), body=None)
    sleeps = []
    llm = GroqLLM(client=FakeClient([rl() for _ in range(6)] + [Msg('{"ok": 1}')]), sleeper=sleeps.append)
    assert llm.complete_json("s", "u") == {"ok": 1}
    assert llm.stats["rate_limit_hits"] == 6


def test_rate_limit_waiting_budget_is_bounded():
    rl = lambda: groq.RateLimitError("slow", response=_resp(429, {"retry-after": "60"}), body=None)
    client = FakeClient([rl() for _ in range(10)])
    llm = GroqLLM(client=client, sleeper=lambda _: None)
    with pytest.raises(LLMError) as ei:
        llm.complete_json("s", "u")
    assert ei.value.kind == "rate_limit" and client.calls == 3  # 60+60 allowed, third pushes past the 150s budget


def test_after_first_429_calls_are_serialised():
    state = {"active": 0, "peak": 0, "first": True}
    lock = threading.Lock()

    class Client:
        chat = None

        def __init__(self):
            self.chat = type("C", (), {"completions": self})()

        def create(self, **kw):
            with lock:
                if state["first"]:
                    state["first"] = False
                    raise groq.RateLimitError("x", response=_resp(429, {"retry-after": "0"}), body=None)
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return Msg('{"ok": 1}')

    llm = GroqLLM(client=Client(), sleeper=lambda _: None)
    ts = [threading.Thread(target=llm.complete_json, args=("s", "u")) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert llm._throttled and state["peak"] == 1


def test_quota_guard_limits_per_workspace_and_globally(tmp_path):
    from dataclasses import replace
    from verity.ui.pages import check_quota
    db = AuditDB(str(tmp_path / "q.db"))
    s = Settings(groq_api_key="x", tavily_api_key="y", max_audits_per_workspace_day=2, max_audits_per_day=3)
    assert check_quota(s, db, "a") is None
    db.record_run("a"); db.record_run("a")
    assert "Daily limit" in check_quota(s, db, "a")
    assert check_quota(s, db, "b") is None  # other visitors unaffected
    db.record_run("b")
    assert "daily audit budget" in check_quota(s, db, "c")
    assert check_quota(replace(s, max_audits_per_workspace_day=0, max_audits_per_day=0), db, "a") is None  # 0 = unlimited
