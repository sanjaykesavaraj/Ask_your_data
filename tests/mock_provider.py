"""
Mock LLM provider for DEMONSTRATING the LLM path without any API key or model.

It speaks the OpenAI /chat/completions protocol, so the app treats it exactly
like a real provider. It implements a deliberately simple "model":

  * some questions it answers the SAME way as the rules engine  -> agree
  * one question it answers DIFFERENTLY                         -> disagree
    (it forgets that revenue is recognised on delivery only)

That difference is the whole point of the "Run both and compare" mode.

Run:    python tests/mock_provider.py
Then in the app sidebar:
    provider = OpenAI-compatible
    base URL = http://127.0.0.1:8787/v1
    model    = mock-model
    key      = anything (e.g. "demo")
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8787


def extract_question(prompt: str) -> str:
    """The app sends schema + few-shot examples + the question.

    A real model reads all of it; our mock must pull out ONLY the last
    "Q: ..." line, otherwise the few-shot examples match first and the mock
    answers the wrong question.
    """
    idx = prompt.rfind("Q:")
    return prompt[idx + 2:].strip() if idx != -1 else prompt.strip()


def mock_model(prompt: str) -> str:
    """A very small, very literal 'language model'."""
    q = extract_question(prompt).lower().strip()

    # --- deliberately WRONG: sums every order, ignoring the delivered-only rule
    if "return rate" in q:
        return ("SELECT category, ROUND(100.0*COUNT(*)/"
                "(SELECT COUNT(*) FROM v_orders),2) AS value "
                "FROM v_orders o JOIN order_items oi ON oi.order_id=o.order_id "
                "JOIN products p ON p.product_id=oi.product_id "
                "GROUP BY category ORDER BY value DESC")

    # --- trend
    if "trend" in q or "over time" in q or "monthly" in q:
        return ("SELECT month, ROUND(SUM(net_revenue),2) AS revenue "
                "FROM v_sales GROUP BY month ORDER BY month")

    # --- top-N style
    m = re.search(r"top\s+(\d+)", q)
    # mirror the rules engine: explicit top-N, otherwise a full breakdown
    n = int(m.group(1)) if m else 25

    if "categor" in q:
        dim = "category"
    elif "channel" in q:
        dim = "channel"
    elif "subcategor" in q:
        dim = "subcategory"
    elif "product" in q:
        dim = "product_name"
    elif "payment" in q:
        dim = "payment_method"
    else:
        dim = "city"

    if "margin" in q:
        agg = "ROUND(SUM(gross_margin),2) AS margin"
        order = "margin"
    elif "order" in q and "value" in q:
        agg = "ROUND(SUM(net_revenue)*1.0/COUNT(DISTINCT order_id),2) AS aov"
        order = "aov"
    elif "unit" in q:
        agg = "SUM(quantity) AS units"
        order = "units"
    else:
        agg = "ROUND(SUM(net_revenue),2) AS revenue"
        order = "revenue"

    return (f"SELECT {dim} AS {dim.replace('_name','')}, {agg} "
            f"FROM v_sales GROUP BY {dim} ORDER BY {order} DESC LIMIT {n}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # keep the console clean
        pass

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))).decode())
            question = body["messages"][-1]["content"]
            sql = mock_model(question)
            print(f"[mock] {question[:60]!r} -> {sql[:70]}...", flush=True)
        except Exception as e:
            sql = f"-- mock error: {e}"
        data = json.dumps(
            {"choices": [{"message": {"content": f"```sql\n{sql}\n```"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"Mock LLM provider listening on http://127.0.0.1:{PORT}/v1")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
