"""Wiring. LLM and search clients are process-wide singletons per (key, model) so that ALL visitors share one
rate-limit cool-down and one search cache; per-audit instances would each hammer the same Groq key blindly."""
from __future__ import annotations

import threading

from .config import Settings
from .db import AuditDB
from .llm import GroqLLM
from .search import TavilySearch

_LOCK = threading.Lock()
_LLMS: dict[tuple, GroqLLM] = {}
_SEARCHES: dict[tuple, TavilySearch] = {}


def get_llm(settings: Settings) -> GroqLLM:
    key = (settings.groq_api_key, settings.model)
    with _LOCK:
        if key not in _LLMS:
            _LLMS[key] = GroqLLM(settings.groq_api_key, settings.model)
        return _LLMS[key]


def get_search(settings: Settings) -> TavilySearch:
    key = (settings.tavily_api_key,)
    with _LOCK:
        if key not in _SEARCHES:
            _SEARCHES[key] = TavilySearch(settings.tavily_api_key)
        return _SEARCHES[key]


build_llm, build_search = get_llm, get_search  # backwards-compatible names


def build_db(settings: Settings) -> AuditDB:
    return AuditDB(settings.db_path)
