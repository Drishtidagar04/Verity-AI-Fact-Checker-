"""Configuration. Secrets come from environment variables or Streamlit Secrets only."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # optional: load a local .env during development
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def get_secret(name: str, default: str | None = None) -> str | None:
    """Read a secret from the environment first, then Streamlit Secrets."""
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name]).strip() or default
    except Exception:  # no secrets file / not running in Streamlit
        pass
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(get_secret(name, str(default)) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None = field(default=None, repr=False)
    tavily_api_key: str | None = field(default=None, repr=False)
    model: str = "openai/gpt-oss-120b"
    db_path: str = "data/verity.db"
    max_upload_mb: int = 25
    max_pages: int = 80
    max_claims: int = 40
    chunk_chars: int = 7000
    workers: int = 4
    search_results: int = 6
    max_audits_per_workspace_day: int = 20   # protects your Groq/Tavily credits on a public URL (0 = unlimited)
    max_audits_per_day: int = 200
    snippet_chars: int = 550  # evidence text per source sent to the model (real citations all fall within 500)
    verdict_cache_hours: float = 12.0  # reuse a real verdict for the same claim+model+day (0 = off)
    retention_days: int = 30            # audits older than this are purged at startup
    retry_pass_delay_s: float = 20.0  # settle time before the automatic second pass after rate limits

    @property
    def keys_ready(self) -> bool:
        return bool(self.groq_api_key and self.tavily_api_key)

    @property
    def missing_keys(self) -> list[str]:
        out = []
        if not self.groq_api_key:
            out.append("GROQ_API_KEY")
        if not self.tavily_api_key:
            out.append("TAVILY_API_KEY")
        return out


def load_settings() -> Settings:
    return Settings(
        groq_api_key=get_secret("GROQ_API_KEY"),
        tavily_api_key=get_secret("TAVILY_API_KEY"),
        model=get_secret("GROQ_MODEL", "openai/gpt-oss-120b") or "openai/gpt-oss-120b",
        db_path=get_secret("VERITY_DB_PATH", "data/verity.db") or "data/verity.db",
        max_upload_mb=_int("VERITY_MAX_UPLOAD_MB", 25),
        max_pages=_int("VERITY_MAX_PAGES", 80),
        max_claims=_int("VERITY_MAX_CLAIMS", 40),
        chunk_chars=_int("VERITY_CHUNK_CHARS", 7000),
        workers=max(1, min(_int("VERITY_WORKERS", 4), 8)),
        snippet_chars=max(300, min(_int("VERITY_SNIPPET_CHARS", 550), 900)),
        verdict_cache_hours=float(get_secret("VERITY_VERDICT_CACHE_HOURS", "12") or 12),
        retention_days=_int("VERITY_RETENTION_DAYS", 30),
        search_results=max(3, min(_int("VERITY_SEARCH_RESULTS", 6), 10)),
        max_audits_per_workspace_day=_int("VERITY_MAX_AUDITS_PER_WORKSPACE_DAY", 20),
        max_audits_per_day=_int("VERITY_MAX_AUDITS_PER_DAY", 200),
    )
