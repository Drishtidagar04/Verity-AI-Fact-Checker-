"""UI smoke tests using Streamlit's AppTest (no network)."""
import os

import pytest
from streamlit.testing.v1 import AppTest

from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
from verity.config import Settings
from verity.db import AuditDB
from verity.pipeline import run_audit
from verity.ui import components as ui

APP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for k in ("GROQ_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERITY_DB_PATH", str(tmp_path / "ui.db"))


def test_app_boots_without_keys_and_shows_setup(clean_env):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "Setup required" in html and "GROQ_API_KEY" in html and "TAVILY_API_KEY" in html
    assert [b for b in at.button if b.label == "Run fact-check"][0].disabled


@pytest.mark.parametrize("page", ["History", "Analytics", "Methodology"])
def test_other_pages_render_empty_state(clean_env, page):
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["nav"] = page
    at.run()
    assert not at.exception


def test_results_render_with_full_report(clean_env, tmp_path):
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=str(tmp_path / "ui.db"))
    rep = run_audit(build_trap_pdf(), "trap.pdf", s, ScriptedLLM(), ScriptedSearch())
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["report"] = rep
    at.run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert html.count('class="vc"') == 13
    assert "Contradictory evidence" in html and "Correct fact" in html


def test_history_and_analytics_after_save(clean_env, tmp_path):
    db_path = str(tmp_path / "ui.db")
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=db_path)
    rep = run_audit(build_trap_pdf(), "trap.pdf", s, ScriptedLLM(), ScriptedSearch())
    AuditDB(db_path).save("wsA", rep)
    for page in ("History", "Analytics"):
        at = AppTest.from_file(APP, default_timeout=60)
        at.query_params["ws"] = "wsA"
        at.session_state["nav"] = page
        at.run()
        assert not at.exception, page
    # another workspace must not see it
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["ws"] = "wsB"
    at.session_state["nav"] = "History"
    at.run()
    assert "No audits yet" in " ".join(m.value for m in at.markdown)


def test_html_is_escaped_in_cards():
    from verity.models import Claim, ClaimResult, Verdict
    c = Claim("C01", '<img src=x onerror=alert(1)> 5%', "<script>x</script>", 1, "statistic", "q")
    r = ClaimResult(claim=c, verdict=Verdict.FALSE, corrected_fact="<b>bold</b>", explanation="<i>x</i>")
    html = ui.verdict_card(r)
    assert "<img" not in html and "<script" not in html and "<b>bold" not in html
    assert "&lt;img" in html


def test_javascript_urls_are_not_linked():
    from verity.models import Claim, ClaimResult, Evidence, Verdict
    c = Claim("C01", "x claim text here", "q", 1, "date", "q")
    r = ClaimResult(claim=c, verdict=Verdict.INSUFFICIENT, sources=[Evidence(1, "T", "javascript:alert(1)", "x", "snip")])
    assert "href=" not in ui.sources_html(r)
