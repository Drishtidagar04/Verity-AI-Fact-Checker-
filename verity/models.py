"""Domain models. Plain dataclasses with lossless dict round-tripping."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    INACCURATE = "INACCURATE"
    FALSE = "FALSE"
    INSUFFICIENT = "INSUFFICIENT EVIDENCE"

    @property
    def label(self) -> str:
        return {
            "VERIFIED": "Verified",
            "INACCURATE": "Inaccurate",
            "FALSE": "False",
            "INSUFFICIENT EVIDENCE": "Insufficient evidence",
        }[self.value]

    @property
    def severity(self) -> int:
        """Sort key: most actionable first."""
        return {"FALSE": 0, "INACCURATE": 1, "INSUFFICIENT EVIDENCE": 2, "VERIFIED": 3}[self.value]


VERDICT_ORDER = [Verdict.VERIFIED, Verdict.INACCURATE, Verdict.FALSE, Verdict.INSUFFICIENT]
CATEGORIES = ["statistic", "date", "financial", "technical", "other_fact"]
STANCES = ["supports", "contradicts", "updates", "neutral"]


@dataclass
class Claim:
    id: str
    text: str
    quote: str
    page: int
    category: str
    search_query: str


@dataclass
class Evidence:
    idx: int
    title: str
    url: str
    domain: str
    snippet: str
    score: float = 0.0
    published: str | None = None


@dataclass
class Citation:
    source_idx: int
    stance: str
    quote: str
    quote_matched: bool


@dataclass
class Strength:
    score: int
    label: str
    factors: dict[str, float]
    maximums: dict[str, float]


@dataclass
class ClaimResult:
    claim: Claim
    verdict: Verdict
    corrected_fact: str | None = None
    explanation: str = ""
    citations: list[Citation] = field(default_factory=list)
    sources: list[Evidence] = field(default_factory=list)
    strength: Strength | None = None
    model_confidence: str | None = None  # as stated by the model; never computed
    contradictory: bool = False
    outdated: bool = False
    error: str | None = None  # set when verification could not complete
    error_kind: str | None = None  # rate_limit | network | other
    cached_at: str | None = None   # set when this result was reused from an earlier identical check

    def cited_sources(self) -> list[tuple[Citation, Evidence]]:
        by_idx = {s.idx: s for s in self.sources}
        return [(c, by_idx[c.source_idx]) for c in self.citations if c.source_idx in by_idx]


@dataclass
class AuditReport:
    id: str
    filename: str
    created_at: str
    model: str
    pages: int
    chars: int
    sha256: str
    results: list[ClaimResult]
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    app_version: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """Verdict counts over claims that were actually checked. API failures are NOT 'insufficient evidence'."""
        out = {v.value: 0 for v in VERDICT_ORDER}
        for r in self.results:
            if not r.error:
                out[r.verdict.value] += 1
        return out

    @property
    def not_checked(self) -> int:
        return sum(1 for r in self.results if r.error)

    @property
    def verified_rate(self) -> float | None:
        checked = len(self.results) - self.not_checked
        return (self.counts()[Verdict.VERIFIED.value] / checked) if checked else None

    @property
    def failed_ids(self) -> list[str]:
        return [r.claim.id for r in self.results if r.error]

    # ---- serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for r_dict, r in zip(d["results"], self.results):
            r_dict["verdict"] = r.verdict.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditReport":
        results = []
        for r in d["results"]:
            s = r.get("strength")
            results.append(
                ClaimResult(
                    claim=Claim(**r["claim"]),
                    verdict=Verdict(r["verdict"]),
                    corrected_fact=r.get("corrected_fact"),
                    explanation=r.get("explanation", ""),
                    citations=[Citation(**c) for c in r.get("citations", [])],
                    sources=[Evidence(**e) for e in r.get("sources", [])],
                    strength=Strength(**s) if s else None,
                    model_confidence=r.get("model_confidence"),
                    contradictory=r.get("contradictory", False),
                    outdated=r.get("outdated", False),
                    error=r.get("error"), error_kind=r.get("error_kind"), cached_at=r.get("cached_at"),
                )
            )
        return cls(
            id=d["id"], filename=d["filename"], created_at=d["created_at"], model=d["model"],
            pages=d["pages"], chars=d["chars"], sha256=d.get("sha256", ""), results=results,
            warnings=d.get("warnings", []), duration_s=d.get("duration_s", 0.0),
            app_version=d.get("app_version", ""), metrics=d.get("metrics", {}),
        )
