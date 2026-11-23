"""Tavily live web search with retries, de-duplication and caching."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from .models import Evidence


class SearchError(Exception):
    """kind: auth | rate_limit | network | other"""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


class Searcher(Protocol):
    def search(self, query: str, *, max_results: int = 6, depth: str = "advanced") -> list[Evidence]: ...


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def safe_http_url(url: str) -> bool:
    try:
        return urlparse(url).scheme in ("http", "https") and bool(urlparse(url).netloc)
    except Exception:
        return False


# Social/UGC sites are poor evidence for fact-checking and waste prompt tokens.
EXCLUDED_DOMAINS = ["youtube.com", "facebook.com", "tiktok.com", "instagram.com", "pinterest.com", "quora.com",
                    "reddit.com", "x.com", "twitter.com"]


class TavilySearch:
    def __init__(self, api_key: str | None = None, *, client: Any = None, max_attempts: int = 3,
                 sleeper: Callable[[float], None] = time.sleep):
        if client is None:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
        self.client = client
        self.exclude_ugc = os.environ.get("VERITY_EXCLUDE_UGC", "1") != "0"  # A/B switch for latency tests
        self.max_attempts = max_attempts
        self._sleep = sleeper
        self._cache: dict[tuple[str, int, str], tuple[float, list[Evidence]]] = {}
        self.cache_ttl_s = 6 * 3600.0
        self._lock = threading.Lock()
        self.stats = {"http_calls": 0, "cache_hits": 0, "retries": 0, "backoff_wait_s": 0.0}

    @staticmethod
    def _classify(exc: Exception) -> str:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if "invalidapikey" in name or "unauthorized" in msg or "invalid api key" in msg:
            return "auth"
        if "usagelimit" in name or "rate" in msg or "429" in msg or "limit" in msg:
            return "rate_limit"
        if "timeout" in name or "connection" in name or "timed out" in msg:
            return "network"
        return "other"

    def search(self, query: str, *, max_results: int = 6, depth: str = "advanced") -> list[Evidence]:
        query = (query or "").strip()[:380]
        if not query:
            return []
        key = (query.lower(), max_results, depth)
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self.cache_ttl_s:
                self.stats["cache_hits"] += 1
                return list(hit[1])

        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                with self._lock:
                    self.stats["http_calls"] += 1
                    self.stats["retries"] += 1 if attempt else 0
                resp = self.client.search(
                    query=query, search_depth=depth, max_results=max_results,
                    include_answer=False, include_raw_content=False, timeout=30,
                    **({"exclude_domains": EXCLUDED_DOMAINS} if self.exclude_ugc else {}),
                )
                results = self._to_evidence(resp.get("results", []) if isinstance(resp, dict) else [])
                with self._lock:
                    self._cache[key] = (time.monotonic(), results)
                return list(results)
            except Exception as exc:
                last = exc
                kind = self._classify(exc)
                if kind == "auth":
                    raise SearchError("Tavily rejected the API key (authentication failed).", "auth") from exc
                if kind == "rate_limit" and "usagelimit" in type(exc).__name__.lower():
                    raise SearchError("Tavily usage quota exhausted for this key.", "rate_limit") from exc
                if attempt < self.max_attempts - 1:
                    wait = min(2 ** attempt, 8)
                    with self._lock:
                        self.stats["backoff_wait_s"] += wait
                    self._sleep(wait)
        kind = self._classify(last) if last else "other"
        label = {"rate_limit": "Tavily rate limit reached.", "network": "Could not reach Tavily."}.get(
            kind, "Web search failed."
        )
        raise SearchError(label, kind) from last

    @staticmethod
    def _to_evidence(raw: list[dict[str, Any]]) -> list[Evidence]:
        seen: set[str] = set()
        out: list[Evidence] = []
        for r in raw:
            url = str(r.get("url") or "").strip()
            snippet = " ".join(str(r.get("content") or "").split())
            if not safe_http_url(url) or not snippet or url in seen:
                continue
            seen.add(url)
            try:
                score = float(r.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            out.append(Evidence(
                idx=len(out) + 1, title=str(r.get("title") or domain_of(url))[:200], url=url,
                domain=domain_of(url), snippet=snippet[:900], score=max(0.0, min(score, 1.0)),
                published=(str(r["published_date"]) if r.get("published_date") else None),
            ))
        return out


def merge_evidence(*groups: list[Evidence], limit: int = 8) -> list[Evidence]:
    """Merge result lists, de-duplicate by URL, keep best-scoring first, and re-number 1..n."""
    best: dict[str, Evidence] = {}
    for g in groups:
        for e in g:
            if e.url not in best or e.score > best[e.url].score:
                best[e.url] = e
    ranked = sorted(best.values(), key=lambda e: e.score, reverse=True)[:limit]
    return [Evidence(**{**e.__dict__, "idx": i + 1}) for i, e in enumerate(ranked)]
