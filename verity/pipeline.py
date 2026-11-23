"""Audit orchestration: PDF -> claims -> parallel verification -> report (with measured stage timings)."""
from __future__ import annotations

import time
import uuid
from dataclasses import replace
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Callable

from . import __version__
from .config import Settings
from .extractor import extract_claims
from .llm import JSONLLM, LLMError
from .metrics import Meter, TimedLLM, TimedSearch, stats_copy, stats_delta
from .models import AuditReport, ClaimResult
from .pdf import extract_pdf
from .search import Searcher, SearchError
from .verifier import failed_result, verify_claim

ProgressCb = Callable[[str, int, int, str], None]


class AuditError(Exception):
    """User-presentable failure that aborts the audit."""


def _noop(*_a) -> None:
    return None


def _verify_all(claims, llm, searcher, settings: Settings, progress: ProgressCb, label: str,
                stage: str = "verify", on_result=None) -> list[ClaimResult]:
    """Verify claims concurrently. Progress is reported as each claim COMPLETES (not in document order),
    every claim ends with a result (never silently skipped), and one bad claim cannot sink the rest."""
    total = len(claims)
    results: dict[str, ClaimResult] = {}
    failed = 0

    def work(claim):
        try:
            return verify_claim(claim, llm, searcher, max_results=settings.search_results,
                                snippet_chars=settings.snippet_chars,
                                cache_ttl_s=settings.verdict_cache_hours * 3600)
        except (LLMError, SearchError):
            raise  # auth errors: abort the audit instead of burning quota on every remaining claim
        except Exception as exc:  # bug or odd payload on ONE claim -> flagged, retryable result
            return failed_result(claim, f"Unexpected error while verifying: {type(exc).__name__}")

    def status(done: int) -> str:
        inflight = min(settings.workers, total - done)
        msg = f"{label} {done}/{total} done · {inflight} in progress · {total - done - inflight} pending · {failed} failed"
        remaining = getattr(llm, "cooldown_remaining", lambda: 0.0)()
        if remaining > 0.5:
            msg += f" · ⏳ Groq rate limit, resuming in {remaining:.0f}s"
        return msg

    progress(stage, 0, total, status(0))
    with ThreadPoolExecutor(max_workers=settings.workers) as ex:
        fut_to_claim = {ex.submit(work, c): c for c in claims}
        pending = set(fut_to_claim)
        try:
            while pending:
                finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for fut in finished:
                    res = fut.result()
                    results[fut_to_claim[fut].id] = res
                    failed += 1 if res.error else 0
                    if on_result:
                        on_result(res)  # lets the UI show finished claims while the rest are still running
                progress(stage, len(results), total, status(len(results)))  # also ticks every second while waiting
        except (LLMError, SearchError) as exc:
            for f in fut_to_claim:
                f.cancel()
            raise AuditError(str(exc)) from exc
    return [results[c.id] for c in claims]


def _second_pass(results: list[ClaimResult], llm, searcher, settings: Settings, progress: ProgressCb,
                 warnings: list[str]) -> tuple[list[ClaimResult], dict]:
    """Automatically re-verify claims that failed for API reasons (typically 429s), one at a time, after the
    rate-limit window has had time to reset. Nothing is skipped and nothing is guessed: still-failed claims
    stay flagged 'not checked'."""
    failed = [r.claim for r in results if r.error]
    info = {"attempted": len(failed), "recovered": 0}
    if not failed:
        return results, info
    if any(r.error_kind == "rate_limit" for r in results if r.error) and settings.retry_pass_delay_s > 0:
        progress("retry", 0, len(failed), f"Rate limit hit on {len(failed)} claim(s) · waiting {settings.retry_pass_delay_s:.0f}s before retrying")
        time.sleep(settings.retry_pass_delay_s)
    try:
        fresh = {r.claim.id: r for r in _verify_all(failed, llm, searcher, replace(settings, workers=1), progress,
                                                    "Retrying", stage="retry")}
    except AuditError as exc:
        warnings.append(f"Automatic retry of failed claims stopped: {exc}")
        return results, info
    info["recovered"] = sum(1 for r in fresh.values() if not r.error)
    return [fresh.get(r.claim.id, r) for r in results], info


def run_audit(data: bytes, filename: str, settings: Settings, llm: JSONLLM, searcher: Searcher,
              progress: ProgressCb = _noop, on_result=None) -> AuditReport:
    t0 = time.perf_counter()
    m_ext, m_ver, m_search = Meter(), Meter(), Meter()
    llm_before, search_before = stats_copy(llm), stats_copy(searcher)
    t_llm_ext, t_llm_ver, t_search = TimedLLM(llm, m_ext), TimedLLM(llm, m_ver), TimedSearch(searcher, m_search)

    progress("read", 0, 1, "Reading PDF")
    t = time.perf_counter()
    doc = extract_pdf(data, settings.max_pages, settings.max_upload_mb * 1024 * 1024)  # raises PDFError
    pdf_s = time.perf_counter() - t
    warnings = list(doc.warnings)

    progress("extract", 0, 1, "Extracting factual claims")
    t = time.perf_counter()
    try:
        claims, w = extract_claims(doc, t_llm_ext, chunk_chars=settings.chunk_chars, max_claims=settings.max_claims,
                                   workers=min(settings.workers, 3))
    except LLMError as exc:
        raise AuditError(f"Claim extraction failed: {exc}") from exc
    extract_s = time.perf_counter() - t
    warnings += w
    if not claims:
        warnings.append("No checkable factual claims (statistics, dates, figures) were found in this document.")
    progress("extract", 1, 1, f"Found {len(claims)} claims")

    t = time.perf_counter()
    results = _verify_all(claims, t_llm_ver, t_search, settings, progress, "Verifying", on_result=on_result) if claims else []
    results, retry_info = _second_pass(results, t_llm_ver, t_search, settings, progress, warnings) if results else (results, {"attempted": 0, "recovered": 0})
    verify_s = time.perf_counter() - t
    n_err = sum(1 for r in results if r.error)
    if n_err:
        warnings.append(f"{n_err} claim(s) could not be checked because of an API problem (shown as 'Not checked', not as a verdict). Use 'Retry failed claims'.")

    total_s = time.perf_counter() - t0
    metrics = {
        "model": settings.model, "workers": settings.workers, "claims": len(results), "claims_failed": n_err, "auto_retry": retry_info,
        "verdicts_from_cache": sum(1 for r in results if r.cached_at),
        "pdf_extract_s": round(pdf_s, 3), "claim_extraction_s": round(extract_s, 2),
        "verification_wall_s": round(verify_s, 2), "total_s": round(total_s, 2),
        "groq_extraction_calls": m_ext.snapshot(), "groq_verification_calls": m_ver.snapshot(),
        "tavily_calls": m_search.snapshot(),
        "groq_client": stats_delta(llm, llm_before), "tavily_client": stats_delta(searcher, search_before),
    }
    report = AuditReport(
        id=uuid.uuid4().hex[:12], filename=filename, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model=settings.model, pages=doc.total_pages, chars=doc.chars, sha256=doc.sha256, results=results,
        warnings=warnings, duration_s=round(total_s, 1), app_version=__version__, metrics=metrics,
    )
    progress("done", 1, 1, "Audit complete")
    return report


def retry_failed(report: AuditReport, settings: Settings, llm: JSONLLM, searcher: Searcher,
                 progress: ProgressCb = _noop) -> AuditReport:
    """Re-verify only claims whose previous attempt errored; keeps everything else untouched."""
    failed = [r.claim for r in report.results if r.error]
    if not failed:
        return report
    fresh = {r.claim.id: r for r in _verify_all(failed, llm, searcher, settings, progress, "Retrying")}
    report.results = [fresh.get(r.claim.id, r) for r in report.results]
    report.warnings = [w for w in report.warnings if "could not be checked" not in w and "still could not" not in w]
    n_err = len(report.failed_ids)
    report.metrics["claims_failed"] = n_err
    if n_err:
        report.warnings.append(f"{n_err} claim(s) still could not be checked because of an API problem.")
    return report
