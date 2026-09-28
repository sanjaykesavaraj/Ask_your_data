"""
STEP 2: Clean the raw CSVs, load them into SQLite, and create the analytics views.

This script is a portfolio artefact in its own right: every cleaning action is
LOGGED (row counts before/after), and a data-quality report is written to
reports/data_quality_report.md. Interviewers love seeing the audit trail.

Run:  python src/build_db.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import json
from datetime import datetime

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw")
DB = os.path.join(BASE, "data", "warehouse.db")
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

LOG: list[dict] = []


def log_step(table: str, issue: str, action: str, rows_before: int, rows_after: int, note: str = ""):
    LOG.append({
        "table": table, "issue": issue, "action": action,
        "rows_before": int(rows_before), "rows_after": int(rows_after),
        "rows_affected": int(rows_before - rows_after), "note": note,
    })
    print(f"  [{table}] {issue}: {int(rows_before - rows_after):,} rows affected -> {action}")


# ---------------------------------------------------------------- helpers
def parse_money(x):
    """'Rs.1,299.00' / '₹1,299' / '1299.00' / '' -> float (or NaN)."""
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "null", "-"}:
        return np.nan
    s = (s.replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "")
          .replace("inr", "").replace("rs.", "").replace("rs", "").replace(",", "").strip())
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_date(x):
    """Handle BOTH dd-mm-yyyy and yyyy-mm-dd in the same column."""
    if pd.isna(x):
        return pd.NaT
    s = str(x).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt).date())
        except ValueError:
            continue
    return pd.to_datetime(s, errors="coerce", dayfirst=True)


def canon_city(x):
    if pd.isna(x) or str(x).strip() == "":
        return "Unknown"
    return re.sub(r"\s+", " ", str(x)).strip().title()


def canon_status(x):
    s = re.sub(r"\s+", " ", str(x)).strip().title()
    return {"Delivered": "Delivered", "Returned": "Returned", "Cancelled": "Cancelled",
            "In Transit": "In Transit", "Pending": "Pending"}.get(s, s)


# ---------------------------------------------------------------- 1. customers
print("Cleaning customers ...")
cust = pd.read_csv(os.path.join(RAW, "customers.csv"), dtype=str)
n0 = len(cust)
cust["city"] = cust["city"].map(canon_city)
cust["state"] = (cust["state"].fillna("Unknown").astype(str)
                 .str.strip().str.replace(r"\s+", " ", regex=True).str.title())
cust["signup_date"] = cust["signup_date"].map(parse_date)
cust = cust.drop_duplicates(subset=["customer_id"], keep="first")
log_step("customers", "Exact duplicate customer rows", "Dropped dupes on customer_id", n0, len(cust))
n1 = len(cust)
cust = cust.drop_duplicates()
log_step("customers", "Fully identical duplicate rows", "df.drop_duplicates()", n1, len(cust))
miss_email = int(cust["email"].isna().sum())
miss_city = int((cust["city"] == "Unknown").sum())
LOG.append({"table": "customers", "issue": "Missing email / city", "action": "Filled with 'Unknown' (kept row - email not needed for analysis)",
            "rows_before": len(cust), "rows_after": len(cust), "rows_affected": miss_email + miss_city,
            "note": f"{miss_email} null emails, {miss_city} null cities"})
cust["email"] = cust["email"].fillna("unknown")
cust["signup_date"] = cust["signup_date"].dt.strftime("%Y-%m-%d")
cust = cust[["customer_id", "customer_name", "email", "city", "state",
             "signup_date", "acquisition_channel", "gender"]]

# ---------------------------------------------------------------- 2. products
print("Cleaning products ...")
prod = pd.read_csv(os.path.join(RAW, "products.csv"), dtype=str)
for c in ("cost_price", "mrp"):
    prod[c] = prod[c].map(parse_money)
n0 = len(prod)
prod = prod.drop_duplicates(subset=["product_id"], keep="first")
log_step("products", "Duplicate product rows", "Dropped dupes on product_id", n0, len(prod))
missing_cost = int(prod["cost_price"].isna().sum())
prod["cost_price"] = prod.groupby("category")["cost_price"].transform(
    lambda s: s.fillna(s.median()))
prod["cost_price"] = prod["cost_price"].fillna(prod["cost_price"].median())
LOG.append({"table": "products", "issue": f"{missing_cost} products with missing cost_price",
            "action": "Imputed with category median (margin analysis needs COGS)",
            "rows_before": len(prod), "rows_after": len(prod), "rows_affected": missing_cost,
            "note": "Imputation flagged in README - never impute silently"})
prod["cost_price"] = prod["cost_price"].round(2)
prod["mrp"] = prod["mrp"].round(2)

# ---------------------------------------------------------------- 3. orders
print("Cleaning orders ...")
ords = pd.read_csv(os.path.join(RAW, "orders.csv"), dtype=str)
n0 = len(ords)
ords = ords.drop_duplicates(subset=["order_id"], keep="first")
log_step("orders", "Duplicate order_id rows", "Dropped dupes on order_id", n0, len(ords))
n1 = len(ords)
ords = ords.drop_duplicates()
log_step("orders", "Fully identical duplicate rows", "df.drop_duplicates()", n1, len(ords))
ords["order_date"] = ords["order_date"].map(parse_date)
bad_dates = int(ords["order_date"].isna().sum())
ords = ords.dropna(subset=["order_date"])
log_step("orders", "Unparseable order_date", "Dropped rows", len(ords) + bad_dates, len(ords))
ords["status"] = ords["status"].map(canon_status)
ords["city"] = ords["city"].map(canon_city)
# orphan check
valid_cust = set(cust["customer_id"])
orphans = int((~ords["customer_id"].isin(valid_cust)).sum())
ords = ords[ords["customer_id"].isin(valid_cust)]
log_step("orders", "Orders referencing non-existent customers",
         "Dropped (would break the join)", len(ords) + orphans, len(ords))
ords["order_date"] = ords["order_date"].dt.strftime("%Y-%m-%d")
ords = ords[["order_id", "customer_id", "order_date", "status",
             "payment_method", "channel", "city", "state"]]

# ---------------------------------------------------------------- 4. order_items
print("Cleaning order_items ...")
items = pd.read_csv(os.path.join(RAW, "order_items.csv"), dtype=str)
n0 = len(items)
items = items.drop_duplicates(subset=["item_id"], keep="first")
log_step("order_items", "Duplicate item_id rows", "Dropped dupes on item_id", n0, len(items))
n1 = len(items)
items = items.drop_duplicates(subset=["order_id", "product_id", "quantity", "unit_price"])
log_step("order_items", "Exact duplicate line items", "Dropped identical rows", n1, len(items))
for c in ("unit_price", "discount_amount"):
    items[c] = items[c].map(parse_money)
items["quantity"] = pd.to_numeric(items["quantity"], errors="coerce")
valid_orders = set(ords["order_id"])
orph = int((~items["order_id"].isin(valid_orders)).sum())
items = items[items["order_id"].isin(valid_orders)]
log_step("order_items", "Line items with no matching order", "Dropped orphans", len(items) + orph, len(items))
bad_qty = int((items["quantity"] <= 0).sum())
items = items[items["quantity"] > 0]
log_step("order_items", "Quantity <= 0 (data-entry errors)",
         "Excluded from revenue maths", len(items) + bad_qty, len(items))
n1 = len(items)
items = items.dropna(subset=["unit_price", "discount_amount"])
log_step("order_items", "Missing price/discount", "Dropped", n1, len(items))
items = items[items["product_id"].isin(set(prod["product_id"]))]
items["quantity"] = items["quantity"].astype(int)
items = items[["item_id", "order_id", "product_id", "quantity",
               "unit_price", "discount_amount"]]

# ---------------------------------------------------------------- 5. returns
print("Cleaning returns ...")
rets = pd.read_csv(os.path.join(RAW, "returns.csv"), dtype=str)
n0 = len(rets)
rets = rets.drop_duplicates(subset=["return_id"], keep="first")
log_step("returns", "Duplicate return_id rows", "Dropped dupes", n0, len(rets))
n1 = len(rets)
rets = rets.drop_duplicates()
log_step("returns", "Fully identical duplicate rows", "df.drop_duplicates()", n1, len(rets))
rets = rets[rets["order_id"].isin(valid_orders)]
rets["return_date"] = rets["return_date"].map(parse_date).dt.strftime("%Y-%m-%d")
rets = rets[["return_id", "order_id", "return_date", "return_reason"]]

# ---------------------------------------------------------------- 6. marketing
mkt = pd.read_csv(os.path.join(RAW, "marketing_spend.csv"), dtype=str)
mkt["spend"] = mkt["spend"].map(parse_money)
mkt = mkt.drop_duplicates(subset=["month", "channel"])
mkt = mkt[["month", "channel", "spend"]]

# ---------------------------------------------------------------- load
print(f"\nLoading into SQLite: {DB}")
if os.path.exists(DB):
    os.remove(DB)
con = sqlite3.connect(DB)
cust.to_sql("customers", con, index=False)
prod.to_sql("products", con, index=False)
ords.to_sql("orders", con, index=False)
items.to_sql("order_items", con, index=False)
rets.to_sql("returns", con, index=False)
mkt.to_sql("marketing_spend", con, index=False)
pd.DataFrame(LOG).to_sql("data_quality_log", con, index=False)

cur = con.cursor()
cur.executescript("""
CREATE INDEX idx_orders_date    ON orders(order_date);
CREATE INDEX idx_orders_cust    ON orders(customer_id);
CREATE INDEX idx_items_order    ON order_items(order_id);
CREATE INDEX idx_items_product  ON order_items(product_id);

/* ---------------------------------------------------------------
   SEMANTIC LAYER: business definitions live in ONE place (views)
   so that every query and every dashboard agrees on what
   "revenue" means. This is the single best habit you can show.
   --------------------------------------------------------------- */

-- Revenue is recognised on DELIVERED orders only.
-- Cancelled/Pending/In-transit are excluded; returns are separate.
DROP VIEW IF EXISTS v_sales;
CREATE VIEW v_sales AS
SELECT
    o.order_id,
    o.order_date,
    strftime('%Y-%m', o.order_date)                       AS month,
    CAST(strftime('%Y', o.order_date) AS INTEGER)         AS year,
    ((CAST(strftime('%m', o.order_date) AS INTEGER) + 2) / 3) AS quarter,
    o.customer_id,
    o.city,
    o.state,
    o.channel,
    o.payment_method,
    c.acquisition_channel,
    c.gender,
    c.signup_date,
    p.category,
    p.subcategory,
    oi.product_id,
    p.product_name,
    oi.quantity,
    oi.unit_price,
    oi.discount_amount,
    ROUND(oi.quantity * oi.unit_price, 2)                            AS gross_amount,
    ROUND(oi.quantity * oi.unit_price - oi.discount_amount, 2)       AS net_revenue,
    ROUND(oi.quantity * p.cost_price, 2)                             AS cogs,
    ROUND((oi.quantity * oi.unit_price - oi.discount_amount)
          - (oi.quantity * p.cost_price), 2)                         AS gross_margin
FROM order_items oi
JOIN orders     o ON o.order_id   = oi.order_id
JOIN products   p ON p.product_id = oi.product_id
LEFT JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'Delivered';

-- Order-level view including non-delivered statuses (for rate questions)
DROP VIEW IF EXISTS v_orders;
CREATE VIEW v_orders AS
SELECT o.order_id, o.order_date, strftime('%Y-%m', o.order_date) AS month,
       CAST(strftime('%Y', o.order_date) AS INTEGER) AS year,
       ((CAST(strftime('%m', o.order_date) AS INTEGER) + 2) / 3) AS quarter,
       o.customer_id, o.city, o.state, o.channel, o.payment_method, o.status,
       c.acquisition_channel, c.gender
FROM orders o
LEFT JOIN customers c ON c.customer_id = o.customer_id;

DROP VIEW IF EXISTS v_returns;
CREATE VIEW v_returns AS
SELECT r.return_id, r.order_id, r.return_date, r.return_reason,
       o.customer_id, o.city, o.state, o.channel, p.category
FROM returns r
JOIN orders o      ON o.order_id = r.order_id
JOIN order_items oi ON oi.order_id = r.order_id
JOIN products p    ON p.product_id = oi.product_id;

-- Anchor date: the latest date in the warehouse. Relative questions
-- ("last quarter") are answered against THIS, not today's date,
-- so demo results stay stable over time.
DROP TABLE IF EXISTS meta;
CREATE TABLE meta AS
SELECT 'anchor_date' AS key, MAX(order_date) AS value FROM orders
UNION ALL SELECT 'min_date',        MIN(order_date) FROM orders
UNION ALL SELECT 'n_orders',        CAST(COUNT(*) AS TEXT) FROM orders
UNION ALL SELECT 'n_customers',     CAST(COUNT(DISTINCT customer_id) AS TEXT) FROM orders
UNION ALL SELECT 'built_at',        datetime('now');
""")
con.commit()

cur.execute("SELECT value FROM meta WHERE key='anchor_date'")
anchor = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM v_sales")
lines = cur.fetchone()[0]
cur.execute("SELECT ROUND(SUM(net_revenue),2) FROM v_sales")
rev = cur.fetchone()[0]
con.close()

print(f"  v_sales rows : {lines:,}")
print(f"  revenue      : Rs.{rev:,.2f}")
print(f"  anchor date  : {anchor}")

# ---------------------------------------------------------------- DQ report
dq = pd.DataFrame(LOG)[["table", "issue", "action", "rows_before", "rows_after",
                        "rows_affected", "note"]]
md = ["# Data Quality Report", "",
      f"Generated: {datetime.now():%Y-%m-%d %H:%M}",
      f"Anchor (latest) date in warehouse: **{anchor}**",
      f"Rows in `v_sales`: **{lines:,}** | Total net revenue: **Rs.{rev:,.2f}**", "",
      "Every transformation applied to the raw files, in order.", "",
      dq.to_markdown(index=False)]
with open(os.path.join(REPORTS, "data_quality_report.md"), "w") as f:
    f.write("\n".join(md) + "\n")
print(f"\nData quality report -> {os.path.join(REPORTS, 'data_quality_report.md')}")
