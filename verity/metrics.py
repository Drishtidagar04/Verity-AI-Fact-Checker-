"""Lightweight, thread-safe instrumentation so real per-stage timings are measured, never guessed."""
from __future__ import annotations

import threading
import time
from typing import Any


class Meter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.failures = 0
        self.total_s = 0.0  # cumulative across threads (can exceed wall-clock time when parallel)
        self.max_s = 0.0

    def record(self, seconds: float, ok: bool) -> None:
        with self._lock:
            self.calls += 1
            self.failures += 0 if ok else 1
            self.total_s += seconds
            self.max_s = max(self.max_s, seconds)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls, "failures": self.failures, "cumulative_s": round(self.total_s, 2),
                "avg_s": round(self.total_s / self.calls, 2) if self.calls else 0.0, "max_s": round(self.max_s, 2),
            }


class TimedLLM:
    def __init__(self, inner: Any, meter: Meter) -> None:
        self.inner, self.meter = inner, meter

    def __getattr__(self, name: str):  # expose e.g. cooldown_remaining() of the wrapped client
        return getattr(self.inner, name)

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]:
        t = time.perf_counter()
        ok = False
        try:
            out = self.inner.complete_json(system, user, max_tokens=max_tokens)
            ok = True
            return out
        finally:
            self.meter.record(time.perf_counter() - t, ok)


class TimedSearch:
    def __init__(self, inner: Any, meter: Meter) -> None:
        self.inner, self.meter = inner, meter

    def search(self, query: str, *, max_results: int = 6, depth: str = "advanced"):
        t = time.perf_counter()
        ok = False
        try:
            out = self.inner.search(query, max_results=max_results, depth=depth)
            ok = True
            return out
        finally:
            self.meter.record(time.perf_counter() - t, ok)


def stats_delta(inner: Any, before: dict[str, Any] | None) -> dict[str, Any] | None:
    """Difference of an API client's own counters (rate-limit hits, retries, tokens) over one audit."""
    now = getattr(inner, "stats", None)
    if now is None:
        return None
    base = before or {}
    return {k: round(v - base.get(k, 0), 2) if isinstance(v, float) else v - base.get(k, 0) for k, v in now.items()}


def stats_copy(inner: Any) -> dict[str, Any] | None:
    s = getattr(inner, "stats", None)
    return dict(s) if s is not None else None
