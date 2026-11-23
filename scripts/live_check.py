"""Live smoke test against the REAL Groq + Tavily APIs.

Usage:
    export GROQ_API_KEY=...  TAVILY_API_KEY=...
    python scripts/live_check.py                  # audits a generated 13-claim trap PDF
    python scripts/live_check.py path/to/doc.pdf  # audits your own PDF

Prints each claim's verdict, correction and cited sources. No answers are hard-coded anywhere:
what you see is what the model concluded from live web evidence.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verity.config import load_settings
from verity.pipeline import run_audit
from verity.services import build_llm, build_search


def main() -> int:
    settings = load_settings()
    if not settings.keys_ready:
        print("Missing:", ", ".join(settings.missing_keys))
        return 2
    if len(sys.argv) > 1:
        data, name = Path(sys.argv[1]).read_bytes(), Path(sys.argv[1]).name
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
        from fixtures import build_trap_pdf

        data, name = build_trap_pdf(), "synthetic-trap.pdf"
    report = run_audit(data, name, settings, build_llm(settings), build_search(settings),
                       lambda s, d, t, m: print(f"  [{s}] {m}"))
    print(f"\n{report.filename}: {report.counts()}  ({report.duration_s}s)\n")
    for r in report.results:
        print(f"{r.claim.id} {r.verdict.label.upper():<22} {r.claim.text}")
        if r.corrected_fact:
            print(f"      correct fact : {r.corrected_fact}")
        print(f"      why          : {r.explanation}")
        if r.strength:
            print(f"      evidence     : {r.strength.score}/100 {r.strength.label}")
        for c, s in r.cited_sources():
            print(f"      - [{c.stance}] {s.url}")
    for w in report.warnings:
        print("WARNING:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
