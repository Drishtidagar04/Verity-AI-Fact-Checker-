import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from verity.config import Settings


@pytest.fixture(autouse=True)
def _fresh_caches():
    from verity.verifier import VERDICT_CACHE
    VERDICT_CACHE.clear()
    yield
    VERDICT_CACHE.clear()


@pytest.fixture
def settings(tmp_path):
    return Settings(groq_api_key="test", tavily_api_key="test", db_path=str(tmp_path / "t.db"), workers=2, retry_pass_delay_s=0)
