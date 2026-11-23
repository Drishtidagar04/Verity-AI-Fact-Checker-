"""Groq LLM client: JSON-mode completions with retry, backoff and typed errors."""
from __future__ import annotations

import contextlib
import json
import random
import re
import threading
import time
from typing import Any, Callable, Protocol


class LLMError(Exception):
    """kind: auth | rate_limit | network | bad_response | other"""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


class JSONLLM(Protocol):
    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]: ...


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences and surrounding prose."""
    if not text or not text.strip():
        raise ValueError("empty response")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found")
        obj = json.loads(t[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON root is not an object")
    return obj


class GroqLLM:
    RL_MAX_WAIT_S = 75.0   # a single Retry-After longer than this is treated as an exhausted quota
    RL_BUDGET_S = 150.0    # total time one call may spend waiting out rate limits

    def __init__(self, api_key: str | None = None, model: str = "openai/gpt-oss-120b", *,
                 max_attempts: int = 4, client: Any = None, sleeper: Callable[[float], None] = time.sleep):
        import groq  # local import keeps tests/other modules light

        self._groq = groq
        self.model = model
        self.max_attempts = max_attempts
        self._sleep = sleeper
        self._reasoning_supported = True
        self._lock = threading.Lock()
        self._throttled_until = 0.0  # serialisation applies for THROTTLE_S after the latest 429, then lifts
        self._serial = threading.Lock()
        self._cooldown_until = 0.0  # shared by all worker threads: one 429 pauses everyone (no retry stampede)
        self.stats = {"http_calls": 0, "retries": 0, "rate_limit_hits": 0, "backoff_wait_s": 0.0,
                      "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        self.client = client or groq.Groq(api_key=api_key, max_retries=0, timeout=45.0)

    def _bump(self, **inc) -> None:
        with self._lock:
            for k, v in inc.items():
                self.stats[k] += v

    def _wait_cooldown(self) -> None:
        with self._lock:
            wait = self._cooldown_until - time.monotonic()
        if wait > 0:
            self._bump(backoff_wait_s=wait)
            self._sleep(wait)

    def cooldown_remaining(self) -> float:
        """Seconds until the shared rate-limit cool-down ends (0 when not throttled)."""
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def _set_cooldown(self, seconds: float) -> None:
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def _backoff(self, attempt: int, exc: Exception | None = None) -> float:
        retry_after = None
        try:
            hdr = exc.response.headers.get("retry-after") if exc is not None else None  # type: ignore[union-attr]
            retry_after = float(hdr) if hdr else None
        except Exception:
            retry_after = None
        base = retry_after if retry_after is not None else min(2 ** attempt, 16)
        return base + random.uniform(0, 0.5)

    def _create(self, system: str, user: str, max_tokens: int):
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        if self._reasoning_supported and "gpt-oss" in self.model:
            kwargs["reasoning_effort"] = "low"
        return self.client.chat.completions.create(**kwargs)

    THROTTLE_S = 90.0

    @property
    def _throttled(self) -> bool:
        return time.monotonic() < self._throttled_until

    def _gate(self):
        """After the first 429 every call is serialised: parallelism cannot beat a token-per-minute cap."""
        return self._serial if self._throttled else contextlib.nullcontext()

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]:
        g = self._groq
        last: Exception | None = None
        tokens = max_tokens
        rl_extra = 0      # rate-limit waits do not consume normal retry attempts...
        rl_waited = 0.0   # ...but are bounded by a total waiting budget
        attempt = -1
        while True:
            attempt += 1
            n = attempt - rl_extra  # attempts used by non-429 problems
            if n >= self.max_attempts:
                break
            if attempt:
                self._bump(retries=1)
            self._wait_cooldown()
            try:
                self._bump(http_calls=1)
                with self._gate():
                    resp = self._create(system, user, tokens)
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    details = getattr(usage, "prompt_tokens_details", None)
                    self._bump(prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                               completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                               cached_tokens=int(getattr(details, "cached_tokens", 0) or 0))
                choice = resp.choices[0]
                content = choice.message.content or ""
                try:
                    return parse_json_object(content)
                except ValueError as exc:
                    last = exc
                    if getattr(choice, "finish_reason", None) == "length":
                        tokens = min(tokens * 2, 12000)  # reasoning ate the budget
                    if n == self.max_attempts - 1:
                        raise LLMError("The model returned an unreadable response.", "bad_response") from exc
                    self._sleep(0.5)
                    continue
            except g.AuthenticationError as exc:
                raise LLMError("Groq rejected the API key (authentication failed).", "auth") from exc
            except g.PermissionDeniedError as exc:
                raise LLMError("Groq denied access to this model or key.", "auth") from exc
            except g.RateLimitError as exc:
                last = exc
                self._bump(rate_limit_hits=1)
                self._throttled_until = time.monotonic() + self.THROTTLE_S
                wait = self._backoff(min(rl_extra, 4), exc)
                rl_waited += wait
                if wait > self.RL_MAX_WAIT_S or rl_waited > self.RL_BUDGET_S:
                    self._set_cooldown(min(wait, self.RL_MAX_WAIT_S))
                    raise LLMError(
                        "Groq rate limit reached. Wait a minute and retry (or your quota is exhausted).",
                        "rate_limit",
                    ) from exc
                rl_extra += 1
                self._set_cooldown(wait)
                self._bump(backoff_wait_s=wait)
                self._sleep(wait)
            except (g.APIConnectionError, g.APITimeoutError) as exc:
                last = exc
                if n == self.max_attempts - 1:
                    raise LLMError("Could not reach Groq (network issue or timeout).", "network") from exc
                self._sleep(self._backoff(n))
            except g.BadRequestError as exc:
                msg = str(exc).lower()
                if self._reasoning_supported and "reasoning" in msg:
                    self._reasoning_supported = False  # model/version without reasoning_effort
                    rl_extra += 1
                    continue
                raise LLMError(f"Groq rejected the request: {str(exc)[:200]}", "other") from exc
            except g.APIStatusError as exc:
                last = exc
                status = getattr(exc, "status_code", 0)
                if status >= 500 and n < self.max_attempts - 1:
                    self._sleep(self._backoff(n, exc))
                    continue
                raise LLMError(f"Groq returned an error (HTTP {status}).", "other") from exc
        raise LLMError(f"The model call failed after retries: {last}", "other")
