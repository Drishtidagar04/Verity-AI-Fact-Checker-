from test_units import FakeClient, Msg
from verity.llm import GroqLLM
from verity.search import TavilySearch
from test_units import FakeTavily


def test_cached_tokens_recorded():
    m = Msg('{"a":1}')
    m.usage = type("U", (), {"prompt_tokens": 2000, "completion_tokens": 100,
                             "prompt_tokens_details": type("D", (), {"cached_tokens": 540})()})()
    llm = GroqLLM(client=FakeClient([m]), sleeper=lambda _: None)
    llm.complete_json("s", "u")
    assert llm.stats["cached_tokens"] == 540 and llm.stats["prompt_tokens"] == 2000


def test_ugc_exclusion_can_be_switched_off(monkeypatch):
    seen = []

    class C(FakeTavily):
        def search(self, **kw):
            seen.append(kw)
            return super().search(**kw)

    monkeypatch.setenv("VERITY_EXCLUDE_UGC", "0")
    TavilySearch(client=C([{"results": []}]), sleeper=lambda _: None).search("q")
    assert "exclude_domains" not in seen[0]
