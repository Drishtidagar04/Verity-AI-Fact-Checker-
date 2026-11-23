"""Background audit jobs.

The audit runs in a worker thread, NOT inside the Streamlit script run, so:
* the UI stays responsive and shows live progress,
* closing/refreshing the tab does not lose the audit (the finished report is saved to the database
  and re-attached when the same workspace link is opened),
* one workspace can only run one audit at a time and at most N audits run process-wide; the rest queue.
Worker threads never call Streamlit APIs; they only update this thread-safe Job object.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .db import AuditDB
from .models import AuditReport
from .pdf import PDFError
from .pipeline import AuditError, run_audit


@dataclass
class Job:
    ws: str
    filename: str
    state: str = "queued"  # queued | running | done | error
    stage: str = "read"
    done: int = 0
    total: int = 1
    message: str = "Starting…"
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    report: AuditReport | None = None
    error: str | None = None
    partial: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, stage: str, done: int, total: int, message: str) -> None:
        with self._lock:
            self.stage, self.done, self.total, self.message = stage, done, total, message

    def add_partial(self, res) -> None:
        with self._lock:
            self.partial.append(res)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            end = self.finished if self.finished is not None else time.monotonic()
            return {"state": self.state, "stage": self.stage, "done": self.done, "total": self.total,
                    "message": self.message, "elapsed": end - self.started, "error": self.error,
                    "filename": self.filename, "partial": list(self.partial)}


class JobManager:
    def __init__(self, max_concurrent: int | None = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        if max_concurrent is None:
            from .config import get_secret
            try:
                max_concurrent = int(get_secret("VERITY_MAX_CONCURRENT_AUDITS", "2") or 2)
            except ValueError:
                max_concurrent = 2
        # All visitors share one Groq/Tavily key: more than a couple of audits at once only makes every one slower.
        self._slots = threading.BoundedSemaphore(max(1, max_concurrent))

    def get(self, ws: str) -> Job | None:
        with self._lock:
            return self._jobs.get(ws)

    def clear(self, ws: str) -> None:
        with self._lock:
            job = self._jobs.get(ws)
            if job and job.state not in ("running", "queued"):
                del self._jobs[ws]

    def start(self, ws: str, filename: str, data: bytes, settings: Settings, llm: Any, searcher: Any,
              db: AuditDB, *, blocking: bool = False) -> Job | None:
        """Start an audit. Returns None if this workspace already has one running."""
        with self._lock:
            cur = self._jobs.get(ws)
            if cur and cur.state in ("running", "queued"):
                return None
            job = Job(ws=ws, filename=filename)
            self._jobs[ws] = job
        t = threading.Thread(target=self._work, args=(job, data, settings, llm, searcher, db), daemon=True,
                             name=f"verity-audit-{ws[:6]}")
        t.start()
        if blocking:
            t.join()
        return job

    def _work(self, job: Job, data: bytes, settings: Settings, llm: Any, searcher: Any, db: AuditDB) -> None:
        got_slot = False
        try:
            while not self._slots.acquire(timeout=1.0):
                job.update("queued", 0, 1, "Waiting for a free audit slot (other audits are running)")
            got_slot = True
            job.state = "running"
            report = run_audit(data, job.filename, settings, llm, searcher, job.update, on_result=job.add_partial)
            t = time.perf_counter()
            db.save(job.ws, report)
            report.metrics["db_save_s"] = round(time.perf_counter() - t, 4)
            job.report = report
            job.state = "done"
        except PDFError as exc:
            job.error, job.state = f"📄 {exc}", "error"
        except AuditError as exc:
            job.error, job.state = f"⚠️ Audit stopped: {exc}", "error"
        except Exception as exc:  # never leave a job stuck in 'running'
            job.error, job.state = f"Unexpected error ({type(exc).__name__}). Please try again.", "error"
        finally:
            if got_slot:
                self._slots.release()
            job.finished = time.monotonic()


MANAGER = JobManager()  # process-wide singleton (one per Streamlit server process)
