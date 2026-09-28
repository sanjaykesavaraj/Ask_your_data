"""
End-to-end test of the OPTIONAL LLM back-end - without needing a real API key.

A tiny HTTP server mimics the OpenAI /chat/completions API, so we can exercise
every code path, including the one that matters most: what happens when the
model returns something dangerous.

Run:  python tests/test_llm_path.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from llm import LlmConfig          # noqa: E402
from nl2sql import Nl2SqlEngine    # noqa: E402

GOOD_SQL = ("SELECT city AS city, ROUND(SUM(net_revenue),2) AS revenue "
            "FROM v_sales GROUP BY city ORDER BY revenue DESC LIMIT 5")
DANGEROUS_SQL = "DROP TABLE orders"
DIFFERENT_SQL = ("SELECT city AS city, ROUND(SUM(net_revenue),2) AS revenue "
                 "FROM v_sales WHERE city = 'Chennai'")

# question substring -> what the "model" returns
RESPONSES = {
    "[danger]": DANGEROUS_SQL,      # rules CAN parse this; model goes rogue
    "[diff]": DIFFERENT_SQL,        # rules CAN parse this; model answers differently
}
calls = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # silence request logging
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(
            int(self.headers.get("Content-Length", 0))).decode())
        question = body["messages"][-1]["content"]
        calls.append(question)
        key = next((k for k in RESPONSES if k in question.lower()), None)
        sql = RESPONSES.get(key, GOOD_SQL)
        payload = {"choices": [{"message": {"content": f"```sql\n{sql}\n```"}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# Bind to port 0 so the OS hands us a free port - a hard-coded port collides
# with the standalone mock server (and with other jobs in CI).
server = HTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

engine = Nl2SqlEngine()
cfg = LlmConfig("OpenAI-compatible", "test-key-not-real",
                "mock-model", f"http://127.0.0.1:{PORT}/v1")

fails = []


def check(name, cond, detail=""):
    print(f"  {'OK  ' if cond else 'FAIL'} {name}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        fails.append(name)


print("\n=== 1. LLM-first mode: model SQL is used and validated ===")
r = engine.answer("Top 5 cities by revenue", llm_cfg=cfg, llm_mode="llm_first")
check("LLM answered", r["ok"] and r["source"] == "llm", r.get("error", "")[:80])
check("result shape correct", r["ok"] and r["df"].shape == (5, 2), str(r.get("df", ""))[:40])

print("\n=== 2. THE IMPORTANT ONE: model returns DROP TABLE ===")
# The rules engine CAN answer this, so there is a safe statement to fall back to.
r = engine.answer("Top 5 cities by revenue [danger]", llm_cfg=cfg, llm_mode="llm_first")
check("did not execute DROP", r["ok"], r.get("error", "")[:80])
check("fell back to the rules engine", r["ok"] and r["source"] == "rules",
      r.get("source", ""))
check("warning explains the block",
      any("guardrails" in w.lower() for w in r.get("warnings", [])),
      str(r.get("warnings"))[:70])

print("\n=== 3. Side-by-side mode: engines agree ===")
r = engine.answer("Top 5 cities by revenue", llm_cfg=cfg, llm_mode="both")
c = r.get("compare", {})
check("comparison present", bool(c))
check("engines agree", c.get("agrees") is True, str(c.get("agrees")))

print("\n=== 4. Side-by-side mode: engines DISAGREE ===")
r = engine.answer("Top 5 cities by revenue [diff]", llm_cfg=cfg, llm_mode="both")
c = r.get("compare", {})
check("disagreement detected", c.get("agrees") is False, str(c.get("agrees")))

print("\n=== 5. Fallback mode: rules answer first, LLM not called ===")
calls.clear()
r = engine.answer("Top 5 cities by revenue", llm_cfg=cfg, llm_mode="fallback")
check("rules answered", r["ok"] and r["source"] == "rules")
check("LLM was NOT called", len(calls) == 0, f"{len(calls)} call(s)")

print("\n=== 6. Fallback mode: rules cannot parse -> LLM is asked ===")
calls.clear()
r = engine.answer("qwerty zxcv nonsense", llm_cfg=cfg, llm_mode="fallback")
check("LLM was called", len(calls) == 1, f"{len(calls)} call(s)")
check("LLM answered it", r["ok"] and r["source"] == "llm", r.get("error", "")[:80])

print("\n=== 6b. Rogue model AND no rules fallback -> refuse outright ===")
r = engine.answer("qwerty nonsense [danger]", llm_cfg=cfg, llm_mode="llm_first")
check("refused, nothing executed", (not r["ok"]) and "GUARDRAILS" in r.get("error", ""),
      r.get("error", "")[:70])

print("\n=== 6c. The database survived all of that ===")
check("v_sales still intact",
      engine.run_query("SELECT COUNT(*) AS n FROM v_sales").iloc[0, 0] > 40000)

print("\n=== 7. Provider unreachable -> graceful degradation ===")
bad = LlmConfig("OpenAI-compatible", "k", "m",
                    "http://127.0.0.1:9/v1")   # port 9 = discard, nothing there
r = engine.answer("Top 5 cities by revenue", llm_cfg=bad, llm_mode="llm_first")
check("still answered", r["ok"] and r["source"] == "rules")
check("error surfaced", bool(r.get("llm_error")), str(r.get("llm_error"))[:60])

print("\n=== 8. No key configured -> pure offline rules ===")
r = engine.answer("Top 5 cities by revenue", llm_cfg=LlmConfig("OpenAI", ""),
                  llm_mode="llm_first")
check("offline answer", r["ok"] and r["source"] == "rules")

server.shutdown()
print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)} FAILURE(S): {fails}")
    sys.exit(1)
print("All LLM-path tests passed (no real API key required).")
