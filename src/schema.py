"""
STEP 4a: The schema contract - one place that describes the warehouse.

It serves double duty:
  * it is the PROMPT CONTEXT given to an LLM (if an API key is present), and
  * it is the METADATA the rule-based engine uses (metric/dimension synonyms).
"""

TABLES_DDL = """
Table: v_sales   (grain = one order line item; ONLY delivered orders)
  order_id TEXT, order_date TEXT (YYYY-MM-DD), month TEXT (YYYY-MM), year INTEGER,
  quarter INTEGER (1-4), customer_id TEXT, city TEXT, state TEXT, channel TEXT,
  payment_method TEXT, acquisition_channel TEXT, gender TEXT, signup_date TEXT,
  category TEXT, subcategory TEXT, product_id TEXT, product_name TEXT,
  quantity INTEGER, unit_price REAL, discount_amount REAL,
  gross_amount REAL, net_revenue REAL, cogs REAL, gross_margin REAL

Table: v_orders  (grain = one order, ALL statuses incl. Cancelled/Returned/Pending)
  order_id, order_date, month, year, quarter, customer_id, city, state,
  channel, payment_method, status, acquisition_channel, gender

Table: v_returns (grain = one returned order line)
  return_id, order_id, return_date, return_reason, customer_id, city, state,
  channel, category

Table: orders            (order_id, customer_id, order_date, status, payment_method, channel, city, state)
Table: order_items       (item_id, order_id, product_id, quantity, unit_price, discount_amount)
Table: products          (product_id, product_name, category, subcategory, cost_price, mrp)
Table: customers         (customer_id, customer_name, email, city, state, signup_date, acquisition_channel, gender)
Table: marketing_spend   (month TEXT 'YYYY-MM', channel TEXT, spend REAL)
Table: meta              (key, value)  -- anchor_date, min_date, n_orders, n_customers
"""

BUSINESS_RULES = """
BUSINESS DEFINITIONS (must be used consistently):
- Revenue is recognised ONLY on orders with status = 'Delivered'.
  Use v_sales for all revenue/margin/order-count analysis. Do NOT filter by
  status again; v_sales is already filtered.
- net_revenue = (quantity * unit_price) - discount_amount
- gross_margin = net_revenue - (quantity * cost_price);  cogs = quantity * cost_price
- Average order value (AOV) = SUM(net_revenue) / COUNT(DISTINCT order_id)
- Return rate and cancellation rate must be computed from v_orders / orders
  (which contain non-delivered statuses), NOT from v_sales.
- ROAS = revenue (v_sales) / spend (marketing_spend), grouped by month+channel.
- Always alias aggregates with short snake_case names.
- Always GROUP BY and ORDER BY explicit columns; never SELECT *.
"""

DIALECT_RULES = """
SQLITE SYNTAX RULES:
- Dates are TEXT 'YYYY-MM-DD'. Use strftime('%Y-%m', order_date) for month,
  CAST(strftime('%Y', order_date) AS INTEGER) for year.
- SQLite has NO date_trunc, NO EXTRACT, NO TO_CHAR, NO DATEDIFF.
- Quarter = ((CAST(strftime('%m', order_date) AS INTEGER) + 2) / 3)  -- integer division
- Integer division: use CAST(x AS REAL) when you need a decimal.
- Relative dates are resolved by the app, not by SQL - use explicit literals.
- Return ONLY the SQL query. No markdown fences, no explanation.
"""

FULL_SCHEMA_PROMPT = f"""You are a senior analytics engineer writing SQLite for an Indian D2C retail warehouse.

{TABLES_DDL}
{BUSINESS_RULES}
{DIALECT_RULES}
"""

FEW_SHOTS = [
    ("total revenue last quarter",
     "SELECT ROUND(SUM(net_revenue),2) AS net_revenue FROM v_sales WHERE year = 2026 AND quarter = 2"),
    ("top 5 cities by revenue",
     "SELECT city, ROUND(SUM(net_revenue),2) AS net_revenue FROM v_sales "
     "GROUP BY city ORDER BY net_revenue DESC LIMIT 5"),
    ("monthly revenue trend",
     "SELECT month, ROUND(SUM(net_revenue),2) AS net_revenue FROM v_sales "
     "GROUP BY month ORDER BY month"),
    ("revenue by category in 2025",
     "SELECT category, ROUND(SUM(net_revenue),2) AS net_revenue FROM v_sales "
     "WHERE year = 2025 GROUP BY category ORDER BY net_revenue DESC"),
    ("average order value by channel",
     "SELECT channel, ROUND(SUM(net_revenue)/COUNT(DISTINCT order_id),2) AS aov "
     "FROM v_sales GROUP BY channel ORDER BY aov DESC"),
    ("return rate by category",
     "SELECT p.category, ROUND(100.0*COUNT(DISTINCT CASE WHEN o.status='Returned' THEN o.order_id END)/"
     "COUNT(DISTINCT o.order_id),2) AS return_rate_pct FROM v_orders o "
     "JOIN order_items oi ON oi.order_id=o.order_id JOIN products p ON p.product_id=oi.product_id "
     "GROUP BY p.category ORDER BY return_rate_pct DESC"),
    ("roas by channel last year",
     "SELECT s.channel, ROUND(SUM(s.net_revenue)/NULLIF(SUM(m.spend),0),2) AS roas "
     "FROM v_sales s JOIN marketing_spend m ON m.month = s.month AND m.channel = s.channel "
     "WHERE s.year = 2025 GROUP BY s.channel ORDER BY roas DESC"),
]


# --------------------------------------------------------------------------
# Metadata for the rule-based engine
# --------------------------------------------------------------------------
METRICS = {
    "revenue": {"priority": 1, "label": "Net revenue", "agg": "ROUND(SUM(net_revenue),2)",
                "fmt": "currency", "synonyms": ["revenue", "sales", "sales value", "turnover",
                                                "how much", "earned", "gmv", "income", "made"]},
    "orders": {"priority": 2, "label": "Delivered orders", "agg": "COUNT(DISTINCT order_id)",
               "fmt": "int", "synonyms": ["orders", "order count", "number of orders",
                                          "how many orders", "transactions", "order volume"]},
    "customers": {"priority": 2, "label": "Unique customers", "agg": "COUNT(DISTINCT customer_id)",
                  "fmt": "int", "synonyms": ["customers", "unique customers", "buyers",
                                             "how many customers", "shoppers", "users"]},
    "units": {"priority": 3, "label": "Units sold", "agg": "SUM(quantity)", "fmt": "int",
              "synonyms": ["units", "quantity", "items sold", "pieces", "volume sold"]},
    "aov": {"priority": 3, "label": "Avg order value", "agg": "ROUND(SUM(net_revenue)*1.0/COUNT(DISTINCT order_id),2)",
            "fmt": "currency", "synonyms": ["average order value", "aov", "avg order value",
                                            "average basket", "basket size", "order value"]},
    "margin": {"priority": 3, "label": "Gross margin", "agg": "ROUND(SUM(gross_margin),2)", "fmt": "currency",
               "synonyms": ["margin", "gross margin", "profit", "gross profit"]},
    "margin_pct": {"priority": 3, "label": "Margin %", "agg": "ROUND(100.0*SUM(gross_margin)/NULLIF(SUM(net_revenue),0),2)",
                   "fmt": "pct", "synonyms": ["margin percent", "margin %", "margin percentage",
                                              "profit margin", "margin rate"]},
    "discount": {"priority": 3, "label": "Discounts given", "agg": "ROUND(SUM(discount_amount),2)", "fmt": "currency",
                 "synonyms": ["discount", "discounts", "promo", "promotion cost"]},
}

DIMENSIONS = {
    "city": {"col": "city", "label": "City",
             "synonyms": ["city", "cities", "town", "location", "by city"]},
    "state": {"col": "state", "label": "State", "synonyms": ["state", "states"]},
    "category": {"col": "category", "label": "Category",
                 "synonyms": ["category", "categories", "product category", "department"]},
    "subcategory": {"col": "subcategory", "label": "Sub-category",
                    "synonyms": ["subcategory", "sub category", "sub-category", "subcategories"]},
    "product": {"col": "product_name", "label": "Product",
                "synonyms": ["product", "products", "sku", "item", "items", "product name"]},
    "channel": {"col": "channel", "label": "Sales channel",
                "synonyms": ["channel", "channels", "sales channel", "platform", "source"]},
    "payment_method": {"col": "payment_method", "label": "Payment method",
                       "synonyms": ["payment", "payment method", "payment mode", "payments",
                                    "upi", "cod", "cash on delivery"]},
    "acquisition_channel": {"col": "acquisition_channel", "label": "Acquisition channel",
                            "synonyms": ["acquisition channel", "acquired from", "signup channel"]},
    "gender": {"col": "gender", "label": "Gender", "synonyms": ["gender", "men", "women", "male", "female"]},
    "month": {"col": "month", "label": "Month", "synonyms": ["month", "monthly", "by month"]},
    "quarter": {"col": "quarter", "label": "Quarter", "synonyms": ["quarter", "quarterly", "q1", "q2", "q3", "q4"]},
    "year": {"col": "year", "label": "Year", "synonyms": ["year", "yearly", "annual", "annually"]},
}

SPECIAL_METRICS = {
    "return_rate": {
        "label": "Return rate %", "fmt": "pct",
        "synonyms": ["return rate", "returns rate", "return percentage", "return %",
                     "rate of returns", "returned rate"],
        "sql": ("SELECT {dim_col} AS {dim_alias}, "
                "ROUND(100.0*COUNT(DISTINCT CASE WHEN o.status='Returned' THEN o.order_id END)"
                "/NULLIF(COUNT(DISTINCT o.order_id),0),2) AS value "
                "FROM v_orders o {join} {where} GROUP BY {dim_col} {order}"),
        "scalar_sql": ("SELECT ROUND(100.0*(SELECT COUNT(*) FROM v_orders WHERE status='Returned')"
                       "/NULLIF((SELECT COUNT(*) FROM v_orders),0),2) AS value"),
    },
    "cancel_rate": {
        "label": "Cancellation rate %", "fmt": "pct",
        "synonyms": ["cancellation rate", "cancel rate", "cancelled rate", "churn of orders"],
        "sql": ("SELECT {dim_col} AS {dim_alias}, "
                "ROUND(100.0*COUNT(DISTINCT CASE WHEN o.status='Cancelled' THEN o.order_id END)"
                "/NULLIF(COUNT(DISTINCT o.order_id),0),2) AS value "
                "FROM v_orders o {join} {where} GROUP BY {dim_col} {order}"),
        "scalar_sql": ("SELECT ROUND(100.0*(SELECT COUNT(*) FROM v_orders WHERE status='Cancelled')"
                       "/NULLIF((SELECT COUNT(*) FROM v_orders),0),2) AS value"),
    },
    "roas": {
        "label": "ROAS", "fmt": "ratio",
        "synonyms": ["roas", "return on ad spend", "return on advertising spend",
                     "marketing efficiency", "ad efficiency"],
        # NOTE: pre-aggregate v_sales before joining spend. Joining the raw
        # line-item view to a monthly spend table would FAN OUT and multiply
        # spend by the number of order lines - a classic ROAS bug.
        "sql": ("SELECT s.{dim_col} AS {dim_alias}, "
                "ROUND(SUM(s.rev)/NULLIF(SUM(m.spend),0),2) AS value "
                "FROM (SELECT {dim_col}, month, SUM(net_revenue) AS rev FROM v_sales "
                "{inner_where} GROUP BY {dim_col}, month) s "
                "JOIN marketing_spend m ON m.month = s.month AND m.channel = s.channel "
                "GROUP BY s.{dim_col} {order}"),
        "scalar_sql": ("SELECT ROUND((SELECT SUM(net_revenue) FROM v_sales)"
                       "/NULLIF((SELECT SUM(spend) FROM marketing_spend),0),2) AS value"),
    },
    "spend": {
        "label": "Marketing spend", "fmt": "currency",
        "synonyms": ["marketing spend", "ad spend", "advertising spend", "spend", "budget"],
        "sql": ("SELECT {dim_col} AS {dim_alias}, ROUND(SUM(spend),2) AS value "
                "FROM marketing_spend {where} GROUP BY {dim_col} {order}"),
        "scalar_sql": "SELECT ROUND(SUM(spend),2) AS value FROM marketing_spend",
    },
}


def get_distinct_values(con, column: str, table: str = "v_sales") -> list[str]:
    rows = con.execute(
        f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1").fetchall()
    return [r[0] for r in rows]
