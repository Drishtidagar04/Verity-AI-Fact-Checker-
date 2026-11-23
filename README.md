# Verity AI — Intelligent Fact-Checking Platform

> A "Truth Layer" for marketing and research content. Upload a PDF; Verity AI extracts every checkable claim,
> verifies it against **live web evidence**, and returns a verdict, the corrected fact, source links and a
> transparent evidence-strength score.

Built for the Cog Culture *Product Management Trainee* assessment, Part 2 — **The "Fact-Check" Agent**.

**Stack:** Python · Streamlit · Groq (`openai/gpt-oss-120b`) · Tavily search · PyPDF · SQLite · Plotly · ReportLab

---

## What it does

| Step | Behaviour |
|---|---|
| **Extract** | An LLM reads the PDF page-aware and lists statistics, dates, financial and technical figures, each with its exact quote, true page number and a neutral search query. |
| **Verify** | Two live Tavily searches per claim (deep + freshness query so outdated numbers surface). The model judges using *only* the retrieved snippets. |
| **Report** | `VERIFIED` · `INACCURATE` (outdated / partly wrong) · `FALSE` (contradicted) · `INSUFFICIENT EVIDENCE`, with corrected fact, explanation, citations and evidence snippets. |

Also: contradictory-evidence and outdated-statistic flags, filterable claim cards, PDF + JSON audit reports,
per-workspace SQLite audit history, and a Plotly analytics dashboard.

### Mapping to the assessment's three labels

| Assessment | Verity AI | Rule |
|---|---|---|
| Verified (matches data) | **Verified** | Evidence confirms figure and time frame |
| Inaccurate (e.g. outdated) | **Inaccurate** | Close/once-true, evidence shows a newer or different figure → corrected value shown |
| False (no evidence found) | **False** + **Insufficient evidence** | *False* = evidence directly contradicts, or the entity/event isn't real. *Insufficient* = nothing usable found. Absence of data is never silently called "false" |

## Why the verdicts can be trusted (and where they can't)

* **No hard-coded answers.** Every verdict comes from live search + the model. There is no answer table anywhere in `verity/`.
* **Evidence-only judging.** The model sees today's date, the claim and numbered snippets — nothing else.
* **Guardrails enforced in code** (`verity/verifier.py`):
  * a verdict without a real, non-neutral citation is downgraded to *Insufficient evidence*;
  * citations to non-existent sources are discarded; source URLs only ever come from Tavily results;
  * quoted excerpts are checked verbatim against the snippet and flagged if they don't match;
  * empty search results → *Insufficient evidence*, never *False*.
* **Evidence strength is not a fake probability.** It's 0–100 computed from cited sources only: independent domains (35), source-authority tier (25, a transparent domain heuristic), search relevance (20), verbatim quote grounding (10), source agreement (10). The model's self-reported confidence is shown separately and never mixed in. The per-claim breakdown is visible in the UI.
* **Limits:** web snippets can be wrong or paywalled and the model can misread them; scanned/image PDFs need OCR first; the authority tiers are a heuristic. Treat flagged items as a first pass for human review.

## Architecture

```
app.py                     Streamlit entry point
verity/
  config.py                env / Streamlit-Secrets loading (keys never in repr, never in UI)
  pdf.py                   PyPDF extraction, encrypted/corrupt/scanned handling, page-aware chunking
  llm.py                   Groq client: JSON mode, retry/backoff, Retry-After, typed errors
  search.py                Tavily client: retry, dedupe, URL validation, cache
  extractor.py             claim extraction, quote→page matching, de-duplication
  verifier.py              search → evidence-only judgement → guardrails
  scoring.py               evidence-strength model
  pipeline.py              orchestration, parallel verification, progress, retry-failed
  db.py                    SQLite history (workspace-scoped) + analytics frame
  reports.py               JSON + PDF audit reports
  ui/                      theme (design system), components, charts, pages
tests/                     87 tests (see TEST_RESULTS.txt)
scripts/live_check.py      smoke test against the real APIs
```

**Reliability design:** parallel verification (4 workers, shared 429 cool-down); per-claim failures degrade to a flagged result with a
*Retry failed claims* button instead of crashing the audit; auth errors abort immediately to avoid wasting quota;
large PDFs are capped (80 pages / 40 claims, configurable) with an explicit warning; all untrusted text
(PDF content, model output, web snippets) is HTML-escaped before rendering and treated as data inside prompts.

## Performance diagnostics

Every audit records measured stage timings, Groq/Tavily call counts and latency, HTTP 429 hits, backoff seconds and
token usage (expand **⏱ Performance & API diagnostics** under the results, or read `metrics` in the JSON report).
See `PERFORMANCE_REPORT.md` and `EVALUATION.md`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then add your real keys
streamlit run app.py
```

Smoke-test the real APIs (needs keys): `python scripts/live_check.py [your.pdf]`

## Tests

```bash
pytest -q          # 87 tests, no network or API keys required
```

The pipeline tests run a **synthetic 13-claim trap document** (true, outdated, fabricated and unverifiable claims)
through scripted LLM/search *test doubles*. They prove the plumbing and guardrails (downgrade rules, phantom-citation
removal, retry, failure isolation, report generation), **not** live factual accuracy — that is checked by running the
app with real keys (`scripts/live_check.py`). See `TEST_RESULTS.txt`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` / `TAVILY_API_KEY` | – | **Required.** Env vars or Streamlit Secrets |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model |
| `VERITY_MAX_CLAIMS` / `VERITY_MAX_PAGES` | 40 / 80 | Cost & latency guards |
| `VERITY_WORKERS` | 4 | Parallel claim verification |
| `VERITY_DB_PATH` | `data/verity.db` | SQLite file |

## Deploy

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for GitHub + Streamlit Community Cloud steps.

> Note: Streamlit Community Cloud's filesystem is ephemeral, so SQLite history survives reruns and refreshes but may
> reset when the app is rebuilt or put to sleep. Use a persistent volume/host (Render disk, Fly volume) for durable history.

## Final-pass additions (v1.3.0)
* Optional env vars: `VERITY_MAX_CONCURRENT_AUDITS` (default 2; extra audits queue), `VERITY_RETENTION_DAYS` (default 30), `VERITY_EXCLUDE_UGC=0` to allow user-generated domains.
* Same-day verdict cache: re-checking an identical claim reuses the earlier live result (shown as "Reused today's result").
* Try it: use **Download the 13-claim sample document** on the Fact-check page.
* Test: `pip install -r requirements-dev.txt && python -m pytest -q` (100 tests; doubles only, no keys needed).
