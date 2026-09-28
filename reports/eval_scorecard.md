# Evaluation Scorecard - Ask Your Data (Text-to-SQL)

Generated: 2026-09-28 13:32  |  Engine: **rules (offline, deterministic)**



## Headline: **55/55 (100.0%)** with **0 wrong answers**

| Outcome | Count |
|---|---|
| Labelled questions | 55 |
| Correct result set | 55 |
| **Silently wrong (the only real failure mode)** | **0** |
| Engine error / unparsed | 0 |

Of the 55 passes, 6 are cases where the correct behaviour was to **decline to answer** (garbage input, destructive requests, or a question type that is out of scope). A copilot that refuses is safe; one that answers confidently and wrongly is not.

### Accuracy by question type

| category      |   total |   passed |   accuracy |
|:--------------|--------:|---------:|-----------:|
| breakdown     |       9 |        9 |        100 |
| comparison    |       3 |        3 |        100 |
| degraded      |       1 |        1 |        100 |
| out_of_scope  |       1 |        1 |        100 |
| rank          |       9 |        9 |        100 |
| rate_metric   |       7 |        7 |        100 |
| refusal       |       5 |        5 |        100 |
| scalar        |       9 |        9 |        100 |
| share         |       3 |        3 |        100 |
| trend         |       5 |        5 |        100 |
| value_compare |       3 |        3 |        100 |

## Full results

|   id | category      | question                                              | status   | intent     | metric      | dim                 | reason   |
|-----:|:--------------|:------------------------------------------------------|:---------|:-----------|:------------|:--------------------|:---------|
|    1 | scalar        | What was total revenue last quarter?                  | PASS     | scalar     | revenue     | -                   |          |
|    2 | scalar        | What is our total revenue?                            | PASS     | scalar     | revenue     | -                   |          |
|    3 | scalar        | How many orders were delivered last month?            | PASS     | scalar     | orders      | -                   |          |
|    4 | scalar        | How many customers did we have last month?            | PASS     | scalar     | customers   | -                   |          |
|    5 | scalar        | What was the average order value in 2025?             | PASS     | scalar     | aov         | -                   |          |
|    6 | scalar        | How many units were sold in Q1 2026?                  | PASS     | scalar     | units       | -                   |          |
|    7 | scalar        | How much discount did we give last year?              | PASS     | scalar     | discount    | -                   |          |
|    8 | scalar        | What was our gross margin in 2024?                    | PASS     | scalar     | margin      | -                   |          |
|    9 | scalar        | What was the revenue in Electronics in Chennai?       | PASS     | scalar     | revenue     | -                   |          |
|   10 | rank          | Top 5 cities by revenue                               | PASS     | rank       | revenue     | city                |          |
|   11 | rank          | Top 3 categories by margin                            | PASS     | rank       | margin      | category            |          |
|   12 | rank          | Which product has the highest revenue?                | PASS     | rank       | revenue     | product             |          |
|   13 | rank          | Worst 3 subcategories by margin                       | PASS     | rank       | margin      | subcategory         |          |
|   14 | rank          | Which month had the highest revenue?                  | PASS     | rank       | revenue     | month               |          |
|   15 | rank          | Which channel has the highest average order value?    | PASS     | rank       | aov         | channel             |          |
|   16 | rank          | Bottom 5 cities by customers                          | PASS     | rank       | customers   | city                |          |
|   17 | rank          | Top 10 products by units sold                         | PASS     | rank       | units       | product             |          |
|   18 | rank          | Which state has the lowest revenue?                   | PASS     | rank       | revenue     | state               |          |
|   19 | breakdown     | Revenue by category                                   | PASS     | breakdown  | revenue     | category            |          |
|   20 | breakdown     | Revenue by city in 2025                               | PASS     | breakdown  | revenue     | city                |          |
|   21 | breakdown     | Average order value by channel                        | PASS     | breakdown  | aov         | channel             |          |
|   22 | breakdown     | Units sold by payment method                          | PASS     | breakdown  | units       | payment_method      |          |
|   23 | breakdown     | Revenue by gender                                     | PASS     | breakdown  | revenue     | gender              |          |
|   24 | breakdown     | Margin by subcategory                                 | PASS     | breakdown  | margin      | subcategory         |          |
|   25 | breakdown     | Customers by acquisition channel                      | PASS     | breakdown  | customers   | acquisition_channel |          |
|   26 | breakdown     | Revenue by channel last quarter                       | PASS     | breakdown  | revenue     | channel             |          |
|   27 | breakdown     | Discounts by category                                 | PASS     | breakdown  | discount    | category            |          |
|   28 | trend         | Monthly revenue trend                                 | PASS     | trend      | revenue     | month               |          |
|   29 | trend         | Quarterly revenue trend                               | PASS     | trend      | revenue     | quarter             |          |
|   30 | trend         | Yearly revenue trend                                  | PASS     | trend      | revenue     | year                |          |
|   31 | trend         | Monthly orders trend                                  | PASS     | trend      | orders      | month               |          |
|   32 | comparison    | Compare revenue in 2025 vs 2024                       | PASS     | comparison | revenue     | -                   |          |
|   33 | comparison    | Compare revenue in 2024 vs 2026                       | PASS     | comparison | revenue     | -                   |          |
|   34 | comparison    | YoY revenue growth                                    | PASS     | comparison | revenue     | -                   |          |
|   35 | share         | What share of revenue comes from Chennai?             | PASS     | share      | revenue     | -                   |          |
|   36 | share         | What percentage of revenue comes from Electronics?    | PASS     | share      | revenue     | -                   |          |
|   37 | share         | What share of revenue comes from Mobile App?          | PASS     | share      | revenue     | -                   |          |
|   38 | rate_metric   | What is the return rate?                              | PASS     | scalar     | return_rate | -                   |          |
|   39 | rate_metric   | Return rate by category                               | PASS     | breakdown  | return_rate | category            |          |
|   40 | rate_metric   | Cancellation rate by city                             | PASS     | breakdown  | cancel_rate | city                |          |
|   41 | rate_metric   | ROAS by channel last year                             | PASS     | breakdown  | roas        | channel             |          |
|   42 | rate_metric   | What was the marketing spend in 2025?                 | PASS     | scalar     | spend       | -                   |          |
|   43 | rate_metric   | What is our overall ROAS?                             | PASS     | scalar     | roas        | -                   |          |
|   44 | rate_metric   | Which product has the worst return rate?              | PASS     | rank       | return_rate | product             |          |
|   45 | degraded      | Which city has the best ROAS?                         | PASS     | rank       | roas        | city                |          |
|   46 | out_of_scope  | What is the customer lifetime value by signup cohort? | PASS     | fallback   | nan         | nan                 |          |
|   47 | trend         | How did revenue grow month over month in 2025?        | PASS     | mom        | revenue     | -                   |          |
|   48 | value_compare | Compare ROAS for Instagram vs Website                 | PASS     | breakdown  | roas        | channel             |          |
|   49 | value_compare | Compare revenue for Chennai vs Mumbai                 | PASS     | breakdown  | revenue     | city                |          |
|   50 | value_compare | Compare revenue for Chennai vs Mumbai last quarter    | PASS     | breakdown  | revenue     | city                |          |
|   51 | refusal       | asdkjhasd kjhasd                                      | PASS     | fallback   | nan         | nan                 |          |
|   52 | refusal       |                                                       | PASS     | fallback   | nan         | nan                 |          |
|   53 | refusal       | 12345                                                 | PASS     | fallback   | nan         | nan                 |          |
|   54 | refusal       | drop the orders table                                 | PASS     | fallback   | nan         | nan                 |          |
|   55 | refusal       | delete all customers please                           | PASS     | fallback   | nan         | nan                 |          |

## Known failures and limitations (published on purpose)

None - all questions pass.

## How to read this

- Comparison is done on the **result set**, not the SQL string, so an equivalent-but-different query still counts as correct.
- Floats are compared with a tolerance of 0.01 after rounding to 2 dp.
- `degraded` = the engine refuses to fabricate an answer at an invalid grain and falls back to the finest valid grain.
- `known_gap` = a question type the rules engine genuinely cannot build yet. Publishing it is the point: it shows what you know you don't know.

Reproduce with: `python eval/run_eval.py`
