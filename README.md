# 🗣️ Ask Your Data — a Text-to-SQL Analytics Copilot

[![CI](https://github.com/<your-username>/ask-your-data/actions/workflows/ci.yml/badge.svg)](https://github.com/<your-username>/ask-your-data/actions/workflows/ci.yml)
![Evaluation](https://img.shields.io/badge/evaluation-55%2F55%20%7C%200%20wrong-brightgreen)
![Offline capable](https://img.shields.io/badge/runs_offline-no%20API%20key-blue)

> Replace `<your-username>` in the CI badge after you push — see [`DEPLOY.md`](DEPLOY.md).

> **One line for the CV:** Built a natural-language → SQL analytics copilot over a
> 45K-row retail warehouse: cleaning pipeline, read-only guardrails, Streamlit UI and a
> **55-question labelled evaluation suite with 0 wrong answers** (49 answered correctly,
> 6 correctly declined).

Business users ask *"which city had the worst margin last quarter?"* — this app writes the
SQL, validates it against read-only guardrails, runs it, charts it, and explains the answer
in plain English.

It runs **fully offline with no API key** (a deterministic rules engine generates the SQL),
and upgrades to an LLM back-end when you supply one.

---

## Why this project instead of another sales dashboard

| Typical fresher project | This project |
|---|---|
| Loads a clean Kaggle CSV | Generates deliberately dirty raw files, then cleans them with a logged audit trail |
| Charts a dataset | Answers open-ended questions in English |
| "Here is a dashboard" | "Here is a decision, with the number and the SQL behind it" |
| No proof it works | 55 hand-labelled questions, scored automatically, **0 wrong answers** |
| Assumes the query is safe | Three independent read-only guardrails + an interactive attack demo |

---

## Architecture

```
                    ┌────────────────────────────────────────────┐
  question in       │  src/nl2sql.py                             │
  English  ───────► │  1. normalise + detect intent/metric/dim   │
                    │  2. resolve time vs the warehouse ANCHOR   │
                    │  3. emit parameterised SQL from templates  │
                    └───────────────┬────────────────────────────┘
                                    │  (optional) LLM back-end
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │  src/guardrails.py   ← THE TRUST BOUNDARY  │
                    │  • SELECT/WITH only   • 20 blocked keywords│
                    │  • table allowlist    • single statement   │
                    │  • LIMIT injection    • read-only DB handle│
                    └───────────────┬────────────────────────────┘
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │  SQLite warehouse (data/warehouse.db)      │
                    │  semantic layer: v_sales / v_orders /      │
                    │  v_returns  →  one definition of "revenue" │
                    └───────────────┬────────────────────────────┘
                                    ▼
                    ┌────────────────────────────────────────────┐
                    │  src/narrate.py  → chart + written insight │
                    └────────────────────────────────────────────┘
```

**The anchor-date decision.** Relative questions ("last quarter") are resolved against the
latest date **in the warehouse** (31 Aug 2026), not today's date. Demo results therefore stay
stable forever, and the dataset never silently goes stale.

---

## Quick start

```bash
git clone <your-repo> && cd ask-your-data
pip install -r requirements.txt

python src/generate_data.py     # 1. create the messy raw CSVs
python src/build_db.py          # 2. clean + load SQLite + build views
python eval/run_eval.py         # 3. run the 55-question evaluation
streamlit run app/streamlit_app.py   # 4. launch the app
```

Optional LLM back-end (only used when the rules engine can't parse a question):

```bash
export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY=sk-ant-...
```

---

## Screenshots

Three screenshots are worth more than three paragraphs here. After deploying, drop them in
an `images/` folder and add them below — see [Step 5 of `DEPLOY.md`](DEPLOY.md#step-5--add-screenshots-to-the-readme-do-this-it-matters).

1. **Ask tab** — *"Top 5 cities by revenue"*: question → insight → chart → SQL
2. **Guardrails tab** — `DROP TABLE orders` being refused
3. **Evaluation tab** — the 55-question scorecard

---

## Repository layout

```
ask-your-data/
├── src/
│   ├── generate_data.py     # synthetic-but-messy raw data generator
│   ├── build_db.py          # cleaning pipeline + SQLite load + views + DQ log
│   ├── schema.py            # schema contract, business rules, metric metadata
│   ├── guardrails.py        # SQL validator + read-only connection
│   ├── nl2sql.py            # rules engine (+ optional LLM back-end)
│   └── narrate.py           # result tables -> written insights
├── app/streamlit_app.py     # 5-tab UI (Ask / Schema / DQ / Guardrails / Eval)
├── eval/
│   ├── questions.json       # 55 hand-labelled questions with GOLD SQL
│   └── run_eval.py          # harness -> reports/eval_scorecard.md
├── tests/
│   ├── test_edge_cases.py   # 25 edge cases, 20 SQL attacks, 16-thread test
│   ├── test_llm_path.py     # LLM path incl. rogue-model handling (no API key)
│   ├── test_app_smoke.py    # drives the real app through 4 interactions
│   └── mock_provider.py     # stand-in LLM for demos/CI
├── data/                    # generated - gitignored, rebuilt automatically
└── reports/                 # data_quality_report.md, eval_scorecard.md
```

---

## 1. The data is dirty on purpose

`generate_data.py` writes six raw CSVs with defects copied from real ERP exports:

| Defect | Example in the raw file |
|---|---|
| Mixed-case + padded city names | `chennai`, `CHENNAI `, `  Chennai  ` |
| Two date formats in one column | `31-08-2026` *and* `2026-08-31` |
| Currency stored as text | `Rs.1,299.00`, `₹1,299`, `INR 1,299.00` |
| Duplicate rows | 200 duplicate order lines, 120 duplicate customers |
| Orphan foreign keys | 40 line items pointing at a non-existent order |
| Negative / zero quantities | `-1`, `0` (data-entry errors) |
| Missing values | null emails, null cities, 8 products with no cost price |
| Inconsistent status casing | `DELIVERED`, `Delivered `, `delivered` |

`build_db.py` cleans each of these and **logs every action** to a `data_quality_log`
table, rendered in the app's *Data quality* tab and in
[`reports/data_quality_report.md`](reports/data_quality_report.md).

> Scale after cleaning: **36,000 orders → 45,379 revenue lines → ₹15.8 Cr net revenue**
> across 14 cities, 6 categories and 32 months.

**The one judgement call flagged in the README on purpose:** 8 products had no `cost_price`.
It was imputed with the **category median** and recorded in the log. Never impute silently.

---

## 2. The semantic layer (the habit that gets you hired)

Business definitions live in SQL **views**, not in every analyst's head:

```sql
CREATE VIEW v_sales AS
SELECT ... ROUND(oi.quantity*oi.unit_price - oi.discount_amount, 2) AS net_revenue,
           ROUND(oi.quantity*p.cost_price, 2)                       AS cogs,
           ROUND((oi.quantity*oi.unit_price - oi.discount_amount)
                 - (oi.quantity*p.cost_price), 2)                   AS gross_margin
FROM order_items oi
JOIN orders   o ON o.order_id   = oi.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'Delivered';     -- revenue recognised on delivery only
```

So *revenue*, *margin* and *AOV* mean the same thing in every query, and a question about
return rates correctly goes to `v_orders` (which still contains cancelled/returned rows)
instead of `v_sales`.

---

## 3. Guardrails — three independent layers

1. **Validator** (`validate_sql`): `SELECT`/`WITH` only; 20 destructive keywords blocked on
   word boundaries (so a column called `created_at` is fine, `CREATE TABLE` is not); every
   table checked against a 10-object allowlist; stacked `;` statements rejected; `LIMIT`
   injected when missing.
2. **Read-only connection**: `sqlite3.connect("file:warehouse.db?mode=ro", uri=True)`. Even a
   bug in layer 1 cannot write.
3. **Allowlisted schema**: `sqlite_master` and anything else is unreachable.

The app's **Guardrails tab** lets you attack it live: `DROP TABLE orders`,
`DELETE FROM ...`, stacked statements and unknown tables are all refused with a reason —
and there is a button that attempts a write at the connection level so you can watch
SQLite itself refuse.

```python
>>> validate_sql("SELECT 1; DROP TABLE orders").reason
'Blocked: multiple statements detected (';').'
>>> validate_sql("DELETE FROM orders WHERE city='Chennai'").reason
'Blocked: forbidden keyword 'DELETE'. This tool is read-only.'
```

---

## 4. Evaluation: does it actually work? — **55/55, zero wrong answers**

[`eval/questions.json`](eval/questions.json) holds 55 questions, each with **gold SQL
written by hand**. The harness runs the engine and the gold query and compares the
**result sets** (not the SQL text — an equivalent-but-different query still passes), with
a 0.01 tolerance on floats.

I optimise for **zero silently-wrong answers**, not for a high pass rate. A copilot that
declines is safe; one that answers confidently and wrongly is how stakeholders stop
trusting a tool. Of the 55 cases, **49 are answered correctly and 6 are correct
*declines*** (garbage input, destructive requests, and one out-of-scope question type).

| Type | Questions | Result |
|---|---|---|
| Scalar | 9 | 9 correct |
| Rank (top/bottom N) | 9 | 9 correct |
| Breakdown | 9 | 9 correct |
| Trend (incl. month-over-month via `LAG`) | 5 | 5 correct |
| Period comparison (2024 vs 2025) | 3 | 3 correct |
| Value comparison (Instagram vs Website) | 3 | 3 correct |
| Share of total | 3 | 3 correct |
| Rate metrics (return / cancel / ROAS) | 7 | 7 correct |
| Grain fallback | 1 | 1 correct (flagged) |
| Should refuse (noise, destructive intent) | 5 | 5 declined |
| Out of scope (cohort CLV) | 1 | 1 declined |
| **Silently wrong** | — | **0** |

Reproduce with `python eval/run_eval.py`. Full detail in
[`reports/eval_scorecard.md`](reports/eval_scorecard.md).

### Bugs the eval caught that clicking around never would have

| # | Bug | Fix |
|---|---|---|
| 1 | `"How much discount..."` returned revenue — the generic phrase `how much` tied with `discount` on length and won | Metric matching now ranks by **specificity first**, then length |
| 2 | `"share from Mobile App"` returned 7.5% instead of 27.6% — `Mobile App` matched *both* `channel` and `acquisition_channel`, ANDing two filters | Each value token is consumed **once**, at the first matching dimension |
| 3 | ROAS returned `0.02x` — joining line-item `v_sales` to monthly spend **fanned out** and multiplied spend by the row count | Pre-aggregate sales to (channel, month) **before** joining spend |
| 4 | `"revenue last quarter"` returned a 1-row trend instead of a scalar | A period is a **filter** when it isn't the grouping key |
| 5 | `"worst 3 subcategories"` read the `3` as a quarter filter | Time dimensions excluded from value-filter detection |
| 6 | Quarter trends merged Q1-2024 with Q1-2025 | Quarter keys are always `year \|\| '-Q' \|\| quarter` |
| 7 | `"which month had the highest revenue"` was treated as a trend | A superlative or explicit top-N outranks the time-dimension rule |

### Round two — found by the edge-case sweep (`tests/test_edge_cases.py`)

| # | Bug | Fix |
|---|---|---|
| 8 | **The app crashed on a fresh clone.** `warehouse.db` is generated, so a new checkout (or Streamlit Cloud) had no DB and died with `FileNotFoundError` before rendering | App self-heals: it runs the generator + build script on first launch |
| 9 | Garbage input (`""`, `asdkjhasd`, `12345`) **confidently returned total revenue** — indistinguishable from a real answer | Refuse-to-guess gate: if no metric/dimension/period/filter matched, decline instead of answering |
| 10 | `"compare roas for instagram vs website"` returned one overall number | Two values of one dimension now compile to `IN (...)` — previously `channel='Instagram' AND channel='Website'`, which is always false |
| 11 | `WITH x AS (...) SELECT * FROM x` was **blocked** as an unknown table | CTE names are exempt from the table allowlist (this would have broken the LLM path) |
| 12 | `"drop the orders table"` returned the order count | Destructive intent is refused by an intent guard before any SQL is built |
| 13 | `"YoY growth"` reported −32.6% without noting 2026 only runs Jan–Aug | Narrative adds a like-for-like caveat when the latest year is incomplete |
| 14 | `use_container_width` deprecation would break the app on newer Streamlit | Version-aware compat shim emitting `width=` or the legacy keyword |

### Round three — found under Streamlit's real threading model

| # | Bug | Fix |
|---|---|---|
| 15 | **The app broke on the second question anyone asked.** The engine held one long-lived SQLite connection, created on Streamlit's cache thread — but every rerun/interaction runs on a *new* thread, so SQLite raised `SQLite objects created in a thread can only be used in that same thread`. The first query worked; every later one failed | The engine now holds **no** connection: metadata is loaded once into plain Python, and each query opens and closes its own short-lived read-only handle. Locked in by a 16-thread concurrency test |

### Published limitations (deliberately not hidden)

- **Grain fallback.** *"Which city has the best ROAS?"* — spend is only tracked at
  (month, channel), so city-level ROAS is unknowable. The engine falls back to the finest
  **valid** grain instead of inventing numbers. A production system should answer
  *"ROAS isn't available by city"* out loud. Flagged in the eval, not counted as a silent win.
- **Known gap.** *"What is the customer lifetime value by signup cohort?"* — cohort/CLV
  analysis has no intent in the rules engine. This is deliberate scope: it is **Project 3**
  of this portfolio. The test exists so the gap is written down, not discovered in an interview.

---

---

## 5. Adding the LLM back-end (optional)

The app runs **fully offline by default** — the rules engine needs no key and no network.
Add a provider when you want to handle questions the rules engine cannot parse.

### In the app (no redeploy needed)

Open the sidebar → **LLM provider** → pick one → paste your key → **Mode** → *Test connection*.

| Provider | Notes |
|---|---|
| OpenAI | default model `gpt-4o-mini` |
| Anthropic | default `claude-sonnet-4-6` |
| Groq | OpenAI-compatible, very fast free tier |
| Google Gemini | default `gemini-2.0-flash` |
| **Ollama (local)** | **free, no key, runs on your machine** — needs `ollama serve` + a model pulled |
| OpenAI-compatible | any server speaking `/chat/completions` (Azure, OpenRouter, vLLM, a proxy) |

Keys typed into the sidebar are held **in the browser session only** — never written to disk.
For Streamlit Cloud, put them in **Settings → Secrets** instead:

```toml
OPENAI_API_KEY      = "sk-..."
ANTHROPIC_API_KEY   = "sk-ant-..."
GEMINI_API_KEY      = "..."
# optional overrides
OPENAI_MODEL        = "gpt-4o-mini"
OPENAI_BASE_URL     = "https://api.openai.com/v1"   # or Azure / OpenRouter / a proxy
```

### The three modes

| Mode | Behaviour |
|---|---|
| **Rules + LLM fallback** | Rules answer first; the LLM is asked **only** when the rules engine can't parse the question. Cheapest and safest. |
| **LLM first, rules fallback** | Ask the model first; if it errors, is unreachable, or is blocked, the rules engine covers for it. |
| **Run both and compare** | Execute both and report whether the result sets **agree**. This is the interesting one — disagreements are surfaced, not hidden. |

### The guardrails do not care who wrote the SQL

Both engines go through the identical validator. Three things are worth calling out:

1. **A rogue statement never executes.** If the model returns `DROP TABLE orders`, it is
   blocked — and if the rules engine has a safe statement for that question, the app falls
   back to it and tells you what happened.
2. **If there is no safe fallback, it refuses.** Blocked + nothing to fall back to = no
   answer, not a guessed one.
3. **A dead provider degrades gracefully.** Timeout / 401 / unreachable → the rules engine
   answers and the error is shown in the UI.

All three are covered by `tests/test_llm_path.py`, which runs against a local mock server —
**no API key required to run the tests.**

```bash
python tests/test_llm_path.py     # 13 checks incl. "model returns DROP TABLE"
```

### Score the LLM honestly

The same 55 questions can be run against the LLM path for a real comparison:

```bash
export OPENAI_API_KEY=sk-...
python eval/run_eval.py --llm                 # LLM first, rules cover
python eval/run_eval.py --llm --mode fallback
```

It reports a **back-end mix** (`{'llm': 49, 'rules': 6}`) so you can see how often the rules
engine had to rescue the model. Scoring is identical — result sets compared, no credit for
plausible-looking SQL.

> Sanity check: pointing this at a deliberately dumb mock that returns the same query every
> time scores **0%**. The harness measures the model; it does not flatter it.

## 6. Deployment

Full walkthrough: **[`DEPLOY.md`](DEPLOY.md)** — GitHub → Streamlit Cloud in ~10 minutes, free.

The app is **self-healing**: if `data/warehouse.db` is missing (fresh clone, Streamlit Cloud,
CI) it runs the generator and build script on first launch, so you can deploy straight from
a git push with no manual step.

```bash
# Streamlit Community Cloud
#   1. push this repo to GitHub
#   2. share.streamlit.io -> New app -> pick the repo
#   3. main file: app/streamlit_app.py      branch: main
#   4. optional: add OPENAI_API_KEY under Settings -> Secrets
```

Requirements are pinned in [`requirements.txt`](requirements.txt); only `pandas`, `numpy`,
`streamlit`, `plotly` and `tabulate` are needed. No API key is required to run it.

### Verify before you deploy

```bash
python tests/test_edge_cases.py   # 25 edge cases, 20 SQL attacks, 7 write attempts,
                                  # 8 data checks, 16-thread concurrency test
python tests/test_app_smoke.py    # drives the real app headlessly through 4 interactions
python tests/test_llm_path.py     # LLM path incl. rogue-model handling (mock server, no key)
python eval/run_eval.py           # 55 labelled questions -> reports/eval_scorecard.md
```

All three run clean on a fresh checkout.

`test_app_smoke.py` uses Streamlit's own `AppTest` harness, so the app is exercised under
its **real threading model** rather than a single script run. That matters: bug #15 below
only appeared on the *second* interaction, so any test that ran the app once would have
missed it.

---

## 7. What I would build next

1. **Natural-language → chart recommendation** driven by the result shape (done for
   4 chart types; push to 8 including cohort heatmaps and waterfall).
2. **Query-cost guard**: reject or warn on scans above a row threshold using
   `EXPLAIN QUERY PLAN`.
3. **Cohort + CLV intents** (the documented gap above).
4. **Evaluation on the LLM path** — same 55 questions, so rules-vs-LLM accuracy can be
   compared honestly.
5. **dbt + Postgres** instead of hand-written views, so the semantic layer is version-controlled.

---

## 8. Skills this demonstrates

| Area | Evidence in this repo |
|---|---|
| SQL | window functions (`LAG`), CTEs, views as a semantic layer, pre-aggregation to avoid fan-out |
| Python / pandas | cleaning pipeline: 17 logged checks, 1,343 rows corrected, money/date parsers |
| Data quality | orphan FKs, dupes, nulls, mixed formats — 17 logged checks, 1,343 rows handled |
| Data modelling | star-ish schema (facts + dims) and a documented grain |
| LLM engineering | multi-provider client, 3 routing modes, side-by-side rules-vs-LLM comparison, **output never trusted** |
| Security mindset | 3-layer read-only enforcement with an interactive attack demo |
| Evaluation / rigour | 55 gold-labelled questions, result-set comparison, edge-case sweep, published gaps |
| Production thinking | self-healing deploy, version-compat shim, refuse-to-guess gate, like-for-like caveats, thread-safe engine |
| Communication | one-paragraph auto-insight per answer, README, data-quality report |

---

## 9. The 60-second version for an interview

> *"Rather than another dashboard, I built a copilot that lets a business user ask a question
> in English. The interesting part wasn't the language model — it was everything around it.
> I generated deliberately dirty raw data and wrote a cleaning pipeline that runs 17 logged checks and corrects 1,343 rows.
> I put the business definitions in SQL views so revenue always means the same thing. I wrote
> a validator that blocks anything that isn't a single read-only SELECT, then opened the
> database read-only anyway. And because I didn't want to claim it works without proof, I
> wrote 55 questions with hand-checked gold SQL and scored the engine at zero wrong
> answers — 49 answered correctly, 6 correctly declined. I optimise for zero *silently
> wrong* answers, because a tool that declines is safe while one that answers confidently
> and wrongly is not. Two sweeps found fourteen bugs I'd never have found by clicking —
> including a fan-out that made ROAS wrong by a factor of 300, the fact that the app
> crashed on a fresh clone because the database is generated rather than committed, and a
> threading bug where the engine held one SQLite connection across Streamlit's per-rerun
> threads - so it broke on the second question anyone asked.
> The one question it declines is cohort CLV, and that's Project 3.
> found seven bugs I'd never have found by clicking, including a fan-out that made ROAS
> wrong by a factor of 300. The one question it fails is cohort CLV, and that's Project 3."*

---

*Built as Project 1 of a 4-project data analytics portfolio.*
