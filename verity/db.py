"""SQLite audit history. Every query is scoped to a workspace id so visitors never see each other's audits."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

from .models import AuditReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL,
    model TEXT, pages INTEGER, n_claims INTEGER, verified INTEGER, inaccurate INTEGER, false_n INTEGER,
    insufficient INTEGER, duration_s REAL, sha256 TEXT, report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audits_ws ON audits(workspace, created_at DESC);
CREATE TABLE IF NOT EXISTS usage (ts TEXT NOT NULL, workspace TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
CREATE TABLE IF NOT EXISTS claims (
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE, claim_id TEXT NOT NULL, page INTEGER,
    category TEXT, verdict TEXT, strength INTEGER, n_cited INTEGER, domains TEXT,
    PRIMARY KEY (audit_id, claim_id)
);
"""


class AuditDB:
    def __init__(self, path: str = "data/verity.db"):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(audits)")}
            if "not_checked" not in cols:  # migrate databases created by v1.0
                c.execute("ALTER TABLE audits ADD COLUMN not_checked INTEGER DEFAULT 0")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, workspace: str, report: AuditReport) -> None:
        k = report.counts()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO audits (id, workspace, filename, created_at, model, pages, n_claims, verified, "
                "inaccurate, false_n, insufficient, duration_s, sha256, report_json, not_checked) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (report.id, workspace, report.filename, report.created_at, report.model, report.pages,
                 len(report.results), k["VERIFIED"], k["INACCURATE"], k["FALSE"], k["INSUFFICIENT EVIDENCE"],
                 report.duration_s, report.sha256, json.dumps(report.to_dict()), report.not_checked),
            )
            c.execute("DELETE FROM claims WHERE audit_id = ?", (report.id,))
            c.executemany(
                "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                [(report.id, r.claim.id, r.claim.page, r.claim.category, "NOT CHECKED" if r.error else r.verdict.value,
                  r.strength.score if r.strength else 0, len(r.citations),
                  ",".join(sorted({s.domain for _, s in r.cited_sources()})))
                 for r in report.results],
            )

    def purge(self, retention_days: int = 30) -> int:
        """Delete audits older than the retention window and old usage rows. Returns audits removed."""
        from datetime import datetime, timedelta, timezone
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        usage_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        with self._conn() as c:
            n = c.execute("DELETE FROM audits WHERE created_at < ?", (cutoff,)).rowcount
            c.execute("DELETE FROM usage WHERE ts < ?", (usage_cutoff,))
        return n

    def record_run(self, workspace: str) -> None:
        """Count every audit attempt (independent of history deletion) for abuse/credit protection."""
        from datetime import datetime, timezone
        with self._conn() as c:
            c.execute("INSERT INTO usage VALUES (?, ?)", (datetime.now(timezone.utc).isoformat(timespec="seconds"), workspace))

    def runs_since(self, hours: float = 24, workspace: str | None = None) -> int:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        q, args = "SELECT COUNT(*) FROM usage WHERE ts >= ?", [cutoff]
        if workspace is not None:
            q += " AND workspace = ?"
            args.append(workspace)
        with self._conn() as c:
            return int(c.execute(q, args).fetchone()[0])

    def list_audits(self, workspace: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, filename, created_at, model, pages, n_claims, verified, inaccurate, false_n, insufficient, duration_s, COALESCE(not_checked, 0) AS not_checked "
                "FROM audits WHERE workspace = ? ORDER BY created_at DESC", (workspace,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, workspace: str, audit_id: str) -> AuditReport | None:
        with self._conn() as c:
            row = c.execute("SELECT report_json FROM audits WHERE id = ? AND workspace = ?", (audit_id, workspace)).fetchone()
        return AuditReport.from_dict(json.loads(row["report_json"])) if row else None

    def delete(self, workspace: str, audit_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM audits WHERE id = ? AND workspace = ?", (audit_id, workspace))

    def claims_frame(self, workspace: str) -> pd.DataFrame:
        with self._conn() as c:
            rows = c.execute(
                "SELECT c.*, a.filename, a.created_at FROM claims c JOIN audits a ON a.id = c.audit_id "
                "WHERE a.workspace = ?", (workspace,)
            ).fetchall()
        cols = ["audit_id", "claim_id", "page", "category", "verdict", "strength", "n_cited", "domains", "filename", "created_at"]
        return pd.DataFrame([dict(r) for r in rows], columns=cols)
