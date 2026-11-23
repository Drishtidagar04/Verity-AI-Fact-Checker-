"""Unit tests: LLM client resilience, search client, scoring, PDF handling, DB, config."""
import httpx
import groq
import pytest

from verity.config import Settings
from verity.db import AuditDB
from verity.llm import GroqLLM, LLMError, parse_json_object
from verity.models import Citation, Evidence
from verity.pdf import PDFError, chunk_pages, extract_pdf
from verity.scoring import authority_tier, compute_strength
from verity.search import SearchError, TavilySearch, merge_evidence


# ---------------------------------------------------------------- JSON parsing
@pytest.mark.parametrize("text", ['{"a":1}', '```json\n{"a":1}\n```', 'Sure! {"a":1} hope that helps'])
def test_parse_json_tolerant(text):
    assert parse_json_object(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "   ", "no json", "[1,2]"])
def test_parse_json_rejects(text):
    with pytest.raises(ValueError):
        parse_json_object(text)


# ------------------------------------------------------------------ Groq client
def _resp(status, headers=None):
    return httpx.Response(status, request=httpx.Request("POST", "http://x"), headers=headers or {})


class Msg:
    def __init__(self, content, finish="stop"):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})(), "finish_reason": finish})()]


class FakeClient:
    def __init__(self, script):
        self.script, self.calls, self.kwargs = list(script), 0, []
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kw):
        self.calls += 1
        self.kwargs.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def llm_with(script, **kw):
    sleeps = []
    c = FakeClient(script)
    return GroqLLM(client=c, sleeper=sleeps.append, **kw), c, sleeps


def test_groq_retries_rate_limit_honouring_retry_after():
    rl = groq.RateLimitError("slow down", response=_resp(429, {"retry-after": "2"}), body=None)
    llm, client, sleeps = llm_with([rl, Msg('{"ok": true}')])
    assert llm.complete_json("s", "u") == {"ok": True}
    assert client.calls == 2 and 2 <= sleeps[0] < 3


def test_groq_gives_up_on_long_rate_limit_with_friendly_error():
    rl = groq.RateLimitError("daily", response=_resp(429, {"retry-after": "3600"}), body=None)
    llm, client, _ = llm_with([rl])
    with pytest.raises(LLMError) as ei:
        llm.complete_json("s", "u")
    assert ei.value.kind == "rate_limit" and client.calls == 1


def test_groq_auth_error_not_retried():
    err = groq.AuthenticationError("bad key", response=_resp(401), body=None)
    llm, client, _ = llm_with([err])
    with pytest.raises(LLMError) as ei:
        llm.complete_json("s", "u")
    assert ei.value.kind == "auth" and client.calls == 1


def test_groq_retries_5xx_and_connection_errors():
    e500 = groq.InternalServerError("oops", response=_resp(500), body=None)
    conn = groq.APIConnectionError(request=httpx.Request("POST", "http://x"))
    llm, client, _ = llm_with([e500, conn, Msg('{"a": 1}')])
    assert llm.complete_json("s", "u") == {"a": 1}


def test_groq_empty_output_is_retried_with_bigger_budget():
    llm, client, _ = llm_with([Msg("", "length"), Msg('{"a": 1}')])
    assert llm.complete_json("s", "u", max_tokens=1000) == {"a": 1}
    assert client.kwargs[1]["max_completion_tokens"] == 2000


def test_groq_network_exhaustion_message():
    conn = lambda: groq.APIConnectionError(request=httpx.Request("POST", "http://x"))
    llm, _, _ = llm_with([conn() for _ in range(4)])
    with pytest.raises(LLMError) as ei:
        llm.complete_json("s", "u")
    assert ei.value.kind == "network"


def test_default_model_and_reasoning_effort():
    llm, client, _ = llm_with([Msg("{}")])
    assert llm.model == "openai/gpt-oss-120b"
    llm.complete_json("s", "u")
    assert client.kwargs[0]["reasoning_effort"] == "low"
    assert client.kwargs[0]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------- search
class FakeTavily:
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def search(self, **kw):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_search_dedupes_filters_and_caches():
    raw = {"results": [
        {"url": "https://a.com/x", "title": "A", "content": "alpha", "score": 0.9},
        {"url": "https://a.com/x", "title": "dup", "content": "dup", "score": 0.8},
        {"url": "javascript:alert(1)", "title": "bad", "content": "evil", "score": 1},
        {"url": "https://b.com", "title": "B", "content": "", "score": 1},
        {"url": "https://www.c.org/p", "title": "C", "content": "gamma", "score": "0.5"},
    ]}
    client = FakeTavily([raw])
    s = TavilySearch(client=client, sleeper=lambda _: None)
    out = s.search("q")
    assert [e.domain for e in out] == ["a.com", "c.org"] and [e.idx for e in out] == [1, 2]
    s.search("Q")  # cache hit (case-insensitive)
    assert client.calls == 1


def test_search_retries_then_raises_typed_errors():
    s = TavilySearch(client=FakeTavily([TimeoutError("timed out")] * 3), sleeper=lambda _: None)
    with pytest.raises(SearchError) as ei:
        s.search("q")
    assert ei.value.kind == "network"
    InvalidAPIKeyError = type("InvalidAPIKeyError", (Exception,), {})
    s = TavilySearch(client=FakeTavily([InvalidAPIKeyError("Unauthorized")]), sleeper=lambda _: None)
    with pytest.raises(SearchError) as ei:
        s.search("q")
    assert ei.value.kind == "auth"
    UsageLimitExceededError = type("UsageLimitExceededError", (Exception,), {})
    s = TavilySearch(client=FakeTavily([UsageLimitExceededError("plan limit")]), sleeper=lambda _: None)
    with pytest.raises(SearchError) as ei:
        s.search("q")
    assert ei.value.kind == "rate_limit"


def test_merge_evidence_renumbers_and_prefers_best_score():
    a = [Evidence(1, "t", "https://x.com", "x.com", "s", 0.2), Evidence(2, "t", "https://y.com", "y.com", "s", 0.9)]
    b = [Evidence(1, "t", "https://x.com", "x.com", "s", 0.7)]
    m = merge_evidence(a, b)
    assert [e.url for e in m] == ["https://y.com", "https://x.com"] and [e.idx for e in m] == [1, 2]


# --------------------------------------------------------------------- scoring
def ev(i, dom, score=0.8):
    return Evidence(i, "t", f"https://{dom}/", dom, "snippet text", score)


def test_strength_zero_without_citations():
    s = compute_strength([], [ev(1, "a.com")])
    assert s.score == 0 and s.label == "None"


def test_strength_rewards_authority_diversity_and_grounding():
    srcs = [ev(1, "who.int", 0.9), ev(2, "reuters.com", 0.9), ev(3, "nasa.gov", 0.9)]
    strong = compute_strength([Citation(i, "supports", "q", True) for i in (1, 2, 3)], srcs)
    weak = compute_strength([Citation(1, "supports", "q", False)], [ev(1, "random-blog.xyz", 0.3)])
    assert strong.score >= 85 and strong.label == "Strong"
    assert weak.score < 45 and weak.label == "Weak"
    assert sum(strong.factors.values()) == pytest.approx(strong.score, abs=1)


def test_authority_tiers():
    assert authority_tier("data.worldbank.org") == 1.0 and authority_tier("cdc.gov") == 1.0
    assert authority_tier("en.wikipedia.org") == 0.7 and authority_tier("myblog.com") == 0.45


# ------------------------------------------------------------------------ PDF
def test_pdf_limits_and_chunking():
    from fixtures import build_trap_pdf
    with pytest.raises(PDFError, match="larger"):
        extract_pdf(build_trap_pdf(), max_bytes=100)
    doc = extract_pdf(build_trap_pdf())
    assert doc.total_pages == 1 and "Eiffel" in doc.pages[0][1]
    long_pages = [(i, "Sentence about a fact. " * 80) for i in range(1, 11)]
    chunks = chunk_pages(long_pages, 3000)
    assert len(chunks) > 3 and all(len(c[1]) <= 3300 for c in chunks)
    assert {p for pages, _ in chunks for p in pages} == set(range(1, 11))


def test_scanned_pdf_gets_clear_error():
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 50, 100, 100, fill=1)  # graphics only, no text
    c.save()
    with pytest.raises(PDFError, match="scanned"):
        extract_pdf(buf.getvalue())


def test_page_cap_warns():
    from reportlab.pdfgen import canvas
    import io
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(5):
        c.drawString(50, 700, f"Page {i} fact: revenue was $5 million in 2020.")
        c.showPage()
    c.save()
    doc = extract_pdf(buf.getvalue(), max_pages=2)
    assert len(doc.pages) == 2 and "first 2 of 5" in doc.warnings[0]


# -------------------------------------------------------------------------- DB
def test_db_isolation_and_delete(tmp_path):
    from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf
    from verity.pipeline import run_audit
    s = Settings(groq_api_key="x", tavily_api_key="y", db_path=str(tmp_path / "d.db"))
    rep = run_audit(build_trap_pdf(), "a.pdf", s, ScriptedLLM(), ScriptedSearch())
    db = AuditDB(s.db_path)
    db.save("w1", rep)
    assert db.get("w2", rep.id) is None and db.list_audits("w2") == []
    assert db.get("w1", rep.id).counts() == rep.counts()
    df = db.claims_frame("w1")
    assert len(df) == 13 and df["workspace"].nunique() if "workspace" in df else True
    db.save("w1", rep)  # idempotent re-save (retry flow)
    assert len(db.claims_frame("w1")) == 13
    db.delete("w2", rep.id)  # wrong workspace cannot delete
    assert db.get("w1", rep.id) is not None
    db.delete("w1", rep.id)
    assert db.claims_frame("w1").empty


def test_settings_never_leak_keys_in_repr():
    s = Settings(groq_api_key="gsk_SECRET", tavily_api_key="tvly_SECRET")
    assert "SECRET" not in repr(s) and s.keys_ready
    assert Settings().missing_keys == ["GROQ_API_KEY", "TAVILY_API_KEY"]
