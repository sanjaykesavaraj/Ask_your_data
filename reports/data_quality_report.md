# Data Quality Report

Generated: 2026-09-28 05:52
Anchor (latest) date in warehouse: **2026-08-31**
Rows in `v_sales`: **45,379** | Total net revenue: **Rs.158,050,502.81**

Every transformation applied to the raw files, in order.

| table       | issue                                     | action                                                           |   rows_before |   rows_after |   rows_affected | note                                                 |
|:------------|:------------------------------------------|:-----------------------------------------------------------------|--------------:|-------------:|----------------:|:-----------------------------------------------------|
| customers   | Exact duplicate customer rows             | Dropped dupes on customer_id                                     |          6120 |         6000 |             120 |                                                      |
| customers   | Fully identical duplicate rows            | df.drop_duplicates()                                             |          6000 |         6000 |               0 |                                                      |
| customers   | Missing email / city                      | Filled with 'Unknown' (kept row - email not needed for analysis) |          6000 |         6000 |             300 | 180 null emails, 120 null cities                     |
| products    | Duplicate product rows                    | Dropped dupes on product_id                                      |           420 |          420 |               0 |                                                      |
| products    | 8 products with missing cost_price        | Imputed with category median (margin analysis needs COGS)        |           420 |          420 |               8 | Imputation flagged in README - never impute silently |
| orders      | Duplicate order_id rows                   | Dropped dupes on order_id                                        |         36000 |        36000 |               0 |                                                      |
| orders      | Fully identical duplicate rows            | df.drop_duplicates()                                             |         36000 |        36000 |               0 |                                                      |
| orders      | Unparseable order_date                    | Dropped rows                                                     |         36000 |        36000 |               0 |                                                      |
| orders      | Orders referencing non-existent customers | Dropped (would break the join)                                   |         36000 |        36000 |               0 |                                                      |
| order_items | Duplicate item_id rows                    | Dropped dupes on item_id                                         |         71947 |        71747 |             200 |                                                      |
| order_items | Exact duplicate line items                | Dropped identical rows                                           |         71747 |        71741 |               6 |                                                      |
| order_items | Line items with no matching order         | Dropped orphans                                                  |         71741 |        71701 |              40 |                                                      |
| order_items | Quantity <= 0 (data-entry errors)         | Excluded from revenue maths                                      |         71701 |        71057 |             644 |                                                      |
| order_items | Missing price/discount                    | Dropped                                                          |         71057 |        71057 |               0 |                                                      |
| returns     | Duplicate return_id rows                  | Dropped dupes                                                    |          3166 |         3141 |              25 |                                                      |
| returns     | Fully identical duplicate rows            | df.drop_duplicates()                                             |          3141 |         3141 |               0 |                                                      |
