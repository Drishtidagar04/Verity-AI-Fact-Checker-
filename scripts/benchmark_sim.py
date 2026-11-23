"""Benchmark harness. usage: bench.py <project_root> <label>
REAL measurements: PDF extraction, DB save, JSON/PDF report build (all real code, real files).
SIMULATED: pipeline orchestration with ASSUMED API latencies (scaled x0.1 so it runs fast). Not real API speed."""
import sys, time, json, io, tempfile, statistics
root, label = sys.argv[1], sys.argv[2]
sys.path.insert(0, root); sys.path.insert(0, root + "/tests")
from fixtures import ScriptedLLM, ScriptedSearch, build_trap_pdf, TRAP_CLAIMS
from verity.config import Settings
from verity.pipeline import run_audit
from verity.pdf import extract_pdf
from verity import reports
from verity.db import AuditDB
from reportlab.pdfgen import canvas

def big_pdf(pages):
    b = io.BytesIO(); c = canvas.Canvas(b)
    for p in range(pages):
        y = 800
        for i in range(45):
            c.setFont("Helvetica", 9); c.drawString(40, y, f"Para {p}.{i}: In 20{10+i%14} the company reported revenue of ${i*3+7} million, up {i%9+2}% year on year across 4 regions.")
            y -= 17
        c.showPage()
    c.save(); return b.getvalue()

out = {"label": label}
def best(fn, n=5):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); fn(); ts.append(time.perf_counter() - t)
    return round(statistics.median(ts) * 1000, 1)
for pages in (1, 20, 80):
    data = big_pdf(pages) if pages > 1 else build_trap_pdf()
    out[f"pdf_extract_{pages}p_ms"] = best(lambda: extract_pdf(data, 80))

class SlowLLM(ScriptedLLM):
    EX, VE = 0.6, 0.4
    def complete_json(self, system, user, **kw):
        time.sleep(self.EX if "claim-extraction stage" in system else self.VE)
        return super().complete_json(system, user, **kw)
class SlowSearch(ScriptedSearch):
    ADV, BAS = 0.25, 0.10
    def search(self, query, *, max_results=6, depth="advanced"):
        time.sleep(self.ADV if depth == "advanced" else self.BAS)
        return super().search(query, max_results=max_results, depth=depth)

tmp = tempfile.mkdtemp()
st = Settings(groq_api_key="x", tavily_api_key="y", db_path=tmp + "/b.db", workers=3)
for n in (3, 10, 13):
    pdf = build_trap_pdf(TRAP_CLAIMS[:n])
    ev = []
    t = time.perf_counter()
    rep = run_audit(pdf, "b.pdf", st, SlowLLM(), SlowSearch(), lambda *a: ev.append((time.perf_counter(), a)))
    out[f"sim_total_{n}_claims_s"] = round(time.perf_counter() - t, 2)
    # time until the first verify-progress event => how "stuck" the bar looks
    first = [e for e in ev if e[1][0] == "verify"]
    out[f"sim_first_verify_progress_{n}_s"] = round(first[0][0] - (ev[0][0]), 2) if first else None
    out[f"sim_progress_events_{n}"] = len(first)

# real post-processing costs at 13 and 40 claims
rep13 = run_audit(build_trap_pdf(), "b.pdf", st, ScriptedLLM(), ScriptedSearch())
out["pipeline_overhead_zero_latency_13_ms"] = best(lambda: run_audit(build_trap_pdf(), "b.pdf", st, ScriptedLLM(), ScriptedSearch()), 3)
db = AuditDB(tmp + "/c.db")
out["db_save_13_claims_ms"] = best(lambda: db.save("w", rep13))
out["report_json_13_ms"] = best(lambda: reports.to_json(rep13))
out["report_pdf_13_ms"] = best(lambda: reports.to_pdf(rep13))
big = rep13; big.results = big.results * 3
out["report_pdf_39_ms"] = best(lambda: reports.to_pdf(big), 3)
print(json.dumps(out, indent=1))
