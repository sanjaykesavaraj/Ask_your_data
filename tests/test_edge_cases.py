"""
Error sweep: edge cases, adversarial input and guardrail bypass attempts.

Run:  python tests/test_edge_cases.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from guardrails import validate_sql, connect_readonly  # noqa: E402
from nl2sql import Nl2SqlEngine                        # noqa: E402
from narrate import narrate                            # noqa: E402

engine = Nl2SqlEngine()

EDGE_QUESTIONS = [
    "", "   ", "?", "asdkjhasd kjhasd", "12345", "revenue",
    "drop the orders table",
    "delete all customers please",
    "please update every price to zero",
    "show me everything",
    "select * from v_sales",
    "revenue'; DROP TABLE orders; --",
    "What's the revenue for Men's Wear?",
    "top 5 cities by revenue " * 30,
    "🏏 revenue by city 🏏",
    "REVENUE BY CITY IN 2025",
    "revenue by city in 2025; drop table orders",
    "how much money did we make in chennai from electronics last quarter",
    "which subcategory has the best margin in Fashion",
    "compare roas for instagram vs website",
    "what percentage of revenue is from upi",
    "worst city for returns",
    "mom revenue growth in 2025",
    "null",
    "'; --",
]

GUARDRAIL_ATTACKS = [
    "DROP TABLE orders",
    "drop table orders",
    "DELETE FROM orders WHERE 1=1",
    "UPDATE products SET mrp = 0",
    "INSERT INTO orders VALUES (1,2,3)",
    "ALTER TABLE orders ADD COLUMN x TEXT",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM users",
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM v_sales; DELETE FROM orders",
    "ATTACH DATABASE '/etc/passwd' AS p",
    "PRAGMA writable_schema = 1",
    "SELECT load_extension('evil.so')",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "SeLeCt city, SUM(net_revenue) FROM v_sales GROUP BY city",
    "SELECT * FROM v_sales -- just a comment",
    "/* comment */ SELECT * FROM v_sales",
    "SELECT * FROM v_sales /* c */ ; DROP TABLE orders",
    "SELECT * FROM v_sales",
    "   SELECT city FROM v_sales   ",
]


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


fails = []

# ------------------------------------------------------------------ 1. engine
section("1. ENGINE EDGE CASES (must never raise, never return a broken frame)")
for q in EDGE_QUESTIONS:
    try:
        r = engine.answer(q)
        if r["ok"]:
            df = r["df"]
            assert isinstance(df, pd.DataFrame), "result is not a DataFrame"
            text = narrate(q, df, r["parsed"], engine.anchor)
            assert isinstance(text, str) and text, "empty narrative"
            print(f"  OK    {q[:52]!r:<56} -> {r['parsed'].intent:<10} "
                  f"{df.shape} rows={len(df)}")
        else:
            print(f"  NOANS {q[:52]!r:<56} -> {r.get('error','')[:60]}")
    except Exception as e:
        fails.append(("engine", q, repr(e)))
        print(f"  CRASH {q[:52]!r:<56} -> {type(e).__name__}: {e}")

# -------------------------------------------------------------- 2. guardrails
section("2. GUARDRAIL ATTACKS")
for sql in GUARDRAIL_ATTACKS:
    try:
        g = validate_sql(sql)
        flag = "ALLOW" if g.ok else "BLOCK"
        print(f"  {flag}  {sql[:58]!r:<62} {'' if g.ok else g.reason[:52]}")
        if g.ok:
            con = connect_readonly()
            try:
                pd.read_sql_query(g.sql, con)
            except Exception as e:
                fails.append(("guardrails-allow-ran", sql, repr(e)))
                print(f"        !! allowed but failed to run: {e}")
            finally:
                con.close()
    except Exception as e:
        fails.append(("guardrails", sql, repr(e)))
        print(f"  CRASH {sql[:58]!r:<62} {type(e).__name__}: {e}")

# ------------------------------------------------- 3. read-only enforcement
section("3. READ-ONLY ENFORCEMENT AT THE CONNECTION")
for bad in ["DELETE FROM orders",
            "UPDATE orders SET status='x'",
            "DROP TABLE orders",                      # a real table, not a view
            "DROP TABLE customers",
            "INSERT INTO orders VALUES ('o','c','2025-01-01','Delivered','UPI','Website','Chennai','Tamil Nadu')",
            "CREATE TABLE hacked (x TEXT)",
            "ALTER TABLE orders ADD COLUMN hacked TEXT"]:
    con = connect_readonly()
    try:
        con.execute(bad)
        fails.append(("readonly", bad, "WRITE SUCCEEDED"))
        print(f"  LEAK  {bad}")
    except Exception as e:
        print(f"  BLOCK {bad:<45} -> {type(e).__name__}: {str(e)[:45]}")
    finally:
        con.close()

# ------------------------------------------------------------ 4. data sanity
section("4. DATA SANITY CHECKS")
con = connect_readonly()
checks = {
    "no negative revenue lines": "SELECT COUNT(*) FROM v_sales WHERE net_revenue < 0",
    "no zero-quantity lines": "SELECT COUNT(*) FROM v_sales WHERE quantity <= 0",
    "no orphan order_items": "SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o ON o.order_id=oi.order_id WHERE o.order_id IS NULL",
    "no orphan orders": "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.customer_id=o.customer_id WHERE c.customer_id IS NULL",
    "no duplicate order_ids": "SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY 1 HAVING COUNT(*)>1)",
    "no null city in v_sales": "SELECT COUNT(*) FROM v_sales WHERE city IS NULL",
    "all statuses canonical": "SELECT COUNT(*) FROM orders WHERE status NOT IN ('Delivered','Returned','Cancelled','In Transit','Pending')",
    "dates parse as YYYY-MM-DD": "SELECT COUNT(*) FROM orders WHERE order_date NOT LIKE '____-__-__'",
}
for name, q in checks.items():
    n = con.execute(q).fetchone()[0]
    status = "OK  " if n == 0 else "FAIL"
    if n != 0:
        fails.append(("data", name, f"{n} rows"))
    print(f"  {status} {name:<32} {n}")
con.close()

# ------------------------------------------------------------ 5. thread safety
section("5. THREAD SAFETY")
# Regression test for a real production bug:
#   "SQLite objects created in a thread can only be used in that same thread"
# Streamlit creates the cached engine on one thread and runs every rerun /
# widget interaction on a DIFFERENT thread. Holding a long-lived sqlite3
# connection therefore breaks the app on the second interaction.
import threading  # noqa: E402

shared = Nl2SqlEngine()          # built on THIS thread...
results, errors = [], []
lock = threading.Lock()


def worker(i):
    try:
        q = ["Top 5 cities by revenue", "Monthly revenue trend",
             "Return rate by category", "What is the return rate?",
             "ROAS by channel last year"][i % 5]
        r = shared.answer(q)
        with lock:
            if r["ok"]:
                results.append(len(r["df"]))
            else:
                errors.append((i, q, r.get("error")))
    except Exception as e:
        with lock:
            errors.append((i, "exception", repr(e)))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
for t in threads:
    t.start()
for t in threads:
    t.join()

if errors:
    fails.append(("threading", "16 concurrent queries", f"{len(errors)} errors"))
    for e in errors[:4]:
        print(f"  FAIL thread {e[0]} on {e[1]!r}: {e[2][:110]}")
else:
    print(f"  OK   16 concurrent queries from 16 threads -> {len(results)} results, "
          f"0 threading errors")

# also verify a raw connection used from another thread still behaves
err = []


def raw_query():
    try:
        c = connect_readonly()
        try:
            pd.read_sql_query("SELECT COUNT(*) AS n FROM v_sales", c)
        finally:
            c.close()
    except Exception as e:
        err.append(repr(e))


t = threading.Thread(target=raw_query)
t.start()
t.join()
if err:
    fails.append(("threading", "raw connect_readonly", err[0]))
    print(f"  FAIL raw connection from another thread: {err[0][:110]}")
else:
    print("  OK   connect_readonly() opened+closed inside a worker thread")

# ------------------------------------------------------------------ summary
section("SUMMARY")
if fails:
    print(f"{len(fails)} FAILURE(S):")
    for area, item, err in fails:
        print(f"  [{area}] {item} -> {err}")
    sys.exit(1)
print("All edge cases, attacks, read-only checks and data checks passed.")
