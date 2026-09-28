# Case Study — Ask Your Data: a Text-to-SQL Analytics Copilot

**Role:** Analytics Engineer (solo project) · **Stack:** Python, SQL (SQLite), pandas, Streamlit, Plotly
**Domain:** Indian D2C retail · **Data:** 36,000 orders → 45,379 revenue lines → ₹15.8 Cr net revenue, 32 months

---

## The problem

A Category Manager needs to know *"which city had the worst margin last quarter?"*. Today that
means raising a ticket with the data team and waiting two days — or, worse, exporting to Excel
and getting a different number than Finance did.

**Business impact of the status quo:** self-serve questions took **2 days**; the same KPI
computed by two people produced **two different numbers** because "revenue" was defined
differently in each spreadsheet.

## What I built

An internal copilot: the user types a business question in English, and the app writes the SQL,
validates it, runs it, charts it, and explains the answer — in about a second.

## Approach

**1. Fix the definitions first (before writing any feature).**
I put every business definition into SQL views, so there is exactly one meaning of revenue:

```sql
net_revenue = (quantity × unit_price) − discount      -- delivered orders only
gross_margin = net_revenue − (quantity × cost_price)
```

Return and cancellation rates deliberately read from a *different* view (`v_orders`), because
`v_sales` excludes non-delivered statuses by design. Getting this wrong is the single most
common analytics bug — it's why two analysts get two numbers.

**2. Earn trust with dirty data, not clean data.**
I generated raw exports with the defects real ERPs produce (mixed-case cities, two date
formats, `Rs.1,299.00` as text, duplicate rows, orphan foreign keys, negative quantities) and
wrote a cleaning pipeline that runs **17 logged quality checks**, quarantining or correcting **1,343 rows** and
the rest loaded — with a full audit trail.

**3. Never trust the generated SQL.**
Three independent layers: a validator (only single read-only `SELECT`, 20 blocked keywords,
10-table allowlist, automatic `LIMIT`), a `mode=ro` database handle, and an allowlisted schema.
The demo tab lets anyone try `DROP TABLE orders` and watch it get refused.

**4. Prove it works instead of claiming it does.**
55 questions with hand-written gold SQL, scored on the **result set** (not the SQL string).

## Results

| Metric | Result |
|---|---|
| Questions answered correctly | **49 / 55** (6 correctly declined) |
| Coverage | scalar, top-N, breakdown, trend, A-vs-B, share-of-total, rate metrics |
| Time to answer | **~1 second** vs 2 days of analyst queue |
| Data quality checks logged | **17 checks · 1,343 rows corrected/quarantined** |
| Blocked unsafe statements | **100%** in the live attack demo (20 SQL attacks + 7 write attempts) |
| Silently wrong answers | **0** |

### Insights the tool surfaced on day one

- **₹15.8 Cr** net revenue over 32 months; December 2025 was the peak month (₹77.8 L).
- **Return rate is 8.7% and almost flat** across every category (8.56%–8.85%) — this is a
  *process* problem, not a category problem. Returns should be attacked at fulfilment, not by
  delisting products.
- **Mobile App returns ₹6.18 per ₹1 of spend vs Instagram's ₹2.38** — shifting ₹10 L of
  Instagram budget to App/Marketplace is the single highest-confidence reallocation available.
- **Electronics is 21.1% of revenue**, and Chennai alone is 15.9% — meaningful concentration
  risk in one city.

## Limitations I'd flag to a stakeholder

- Marketing spend is only tracked at (month, channel) grain, so **city-level ROAS is not
  computable**. The tool falls back to the valid grain and says so, rather than inventing a
  number.
- **Cohort retention and CLV are out of scope** for this release (in progress as the next
  project). The tool declines those questions rather than guessing, and the evaluation
  suite records the decline explicitly.
- The rules engine covers a curated question space. Novel phrasings fall back to an LLM, whose
  output passes the same validator.

## What I'd do next

1. Cohort retention + CLV intents (the documented gap).
2. Re-run the same 55-question suite against the LLM path to compare accuracy honestly.
3. Query-cost guard using `EXPLAIN QUERY PLAN` before execution.
4. Move the views into dbt so the semantic layer is version-controlled and testable.
