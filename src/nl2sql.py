"""
STEP 4b: The natural-language -> SQL engine.

Design decision worth defending in interviews:
  Two back-ends, one validator.
    (a) RULES ENGINE  - deterministic, offline, free, testable. Parses intent +
        slots and emits parameterised SQL from templates. This is what makes the
        evaluation harness meaningful (same input -> same SQL every time).
    (b) LLM BACK-END  - optional. Used only when the rules engine cannot parse a
        question, or when the user switches it on. Its output goes through the
        EXACT same guardrails.

Because (a) exists, the project runs on a laptop with no API key and no bill -
and the accuracy scorecard is reproducible by whoever reads your repo.
"""
from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, field

import pandas as pd

from guardrails import validate_sql, connect_readonly
from schema import (METRICS, DIMENSIONS, SPECIAL_METRICS, FULL_SCHEMA_PROMPT,
                    FEW_SHOTS, get_distinct_values)
from llm import LlmConfig, generate_sql


# --------------------------------------------------------------------------
# Parsed representation
# --------------------------------------------------------------------------
@dataclass
class Parsed:
    question: str
    intent: str = "fallback"          # scalar|rank|breakdown|trend|comparison|share|fallback
    metric: str = "revenue"
    metric_matched: bool = False          # was a metric word really found?
    dimension: str | None = None
    filters: list = field(default_factory=list)   # [(dim, value)]
    n: int | None = None
    direction: str = "desc"
    time: tuple | None = None          # (where_clause, human_label, kind)
    compare: list | None = None        # [(clause, label)]
    confidence: float = 0.0

    @property
    def metric_label(self) -> str:
        if self.metric in METRICS:
            return METRICS[self.metric]["label"]
        return SPECIAL_METRICS[self.metric]["label"]


# --------------------------------------------------------------------------
# Time parsing (anchored to the warehouse's latest date, NOT today)
# --------------------------------------------------------------------------
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


class TimeParser:
    def __init__(self, anchor: pd.Timestamp, min_date: pd.Timestamp):
        self.anchor = anchor
        self.min_date = min_date

    def _mstr(self, ts) -> str:
        return ts.strftime("%Y-%m")

    def parse(self, q: str):
        """Return (clause, label, kind) or None. Clause uses {p} prefix slot."""
        a = self.anchor

        # ---- explicit year(s)
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", q)]

        # ---- explicit quarter(s): "q3 2025", "quarter 3", "q3"
        qmatch = re.findall(r"\bq([1-4])\b(?:\s*(?:of\s*)?(20\d{2}))?", q)
        qmatch += re.findall(r"\bquarter\s*([1-4])\b(?:\s*(?:of\s*)?(20\d{2}))?", q)

        # ---- explicit month name(s): "january 2025", "jan 2025"
        mmatch = []
        for name, num in MONTHS.items():
            for m in re.finditer(rf"\b{re.escape(name)}\b(?:\s*(20\d{2}))?", q):
                yr = int(m.group(1)) if m.group(1) else (years[0] if years else a.year)
                mmatch.append((f"{yr}-{num:02d}", yr, num))

        # ---- relative: last N months / days / weeks
        m_rel = re.search(r"\blast\s+(\d+)\s+months?\b", q)
        d_rel = re.search(r"\blast\s+(\d+)\s+days?\b", q)
        w_rel = re.search(r"\blast\s+(\d+)\s+weeks?\b", q)

        if m_rel:
            n = int(m_rel.group(1))
            start = (a - pd.DateOffset(months=n)).strftime("%Y-%m-%d")
            return (f"{{p}}order_date >= '{start}'", f"last {n} months", "range")
        if d_rel:
            n = int(d_rel.group(1))
            start = (a - pd.DateOffset(days=n)).strftime("%Y-%m-%d")
            return (f"{{p}}order_date >= '{start}'", f"last {n} days", "range")
        if w_rel:
            n = int(w_rel.group(1))
            start = (a - pd.DateOffset(weeks=n)).strftime("%Y-%m-%d")
            return (f"{{p}}order_date >= '{start}'", f"last {n} weeks", "range")

        # ---- relative: last/this month
        if re.search(r"\blast month\b", q):
            pm = a - pd.DateOffset(months=1)
            return (f"{{p}}month = '{self._mstr(pm)}'", f"{pm:%B %Y}", "month")
        if re.search(r"\bthis month\b|\bcurrent month\b", q):
            return (f"{{p}}month = '{self._mstr(a)}'", f"{a:%B %Y}", "month")

        # ---- relative: last/this quarter
        if re.search(r"\blast quarter\b|\bprevious quarter\b", q):
            aq = (a.month - 1) // 3 + 1
            py, pq = (a.year, aq - 1) if aq > 1 else (a.year - 1, 4)
            return (f"{{p}}year = {py} AND {{p}}quarter = {pq}", f"Q{pq} {py}", "quarter")
        if re.search(r"\bthis quarter\b|\bcurrent quarter\b", q):
            aq = (a.month - 1) // 3 + 1
            return (f"{{p}}year = {a.year} AND {{p}}quarter = {aq}", f"Q{aq} {a.year}", "quarter")

        # ---- relative: last/this year
        if re.search(r"\blast year\b", q):
            return (f"{{p}}year = {a.year - 1}", str(a.year - 1), "year")
        if re.search(r"\bthis year\b|\bcurrent year\b|\bso far\b|\bytd\b", q):
            return (f"{{p}}year = {a.year}", str(a.year), "year")

        # ---- explicit quarter
        if qmatch:
            num = int(qmatch[0][0])
            yr = int(qmatch[0][1]) if qmatch[0][1] else (years[0] if years else a.year)
            return (f"{{p}}year = {yr} AND {{p}}quarter = {num}", f"Q{num} {yr}", "quarter")

        # ---- explicit month name
        if mmatch:
            ms, yr, num = mmatch[0]
            return (f"{{p}}month = '{ms}'", f"{pd.Timestamp(yr, num, 1):%B %Y}", "month")

        # ---- explicit YYYY-MM such as 2025-11
        ym = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q)
        if ym:
            return (f"{{p}}month = '{ym.group(0)}'", ym.group(0), "month")

        # ---- plain year
        if years:
            return (f"{{p}}year = {years[0]}", str(years[0]), "year")

        return None


TREND_WORDS = ["trend", "over time", "over the", "monthly", "quarterly", "yearly",
               "each month", "each quarter", "growth", "changed", "evolution",
               "time series", "how has", "day by day", "weekly"]
SHARE_WORDS = ["share of", "share ", "percentage of total", "percent of total",
               "what percent", "what %", "contribution", "proportion"]
COMPARE_WORDS = [" vs ", " vs. ", " versus ", " compared to", " compare ", "yoy",
                 "year over year", "than last", "against last"]

# Someone typing "drop the orders table" into a copilot is not asking a
# question. Refuse the request outright instead of answering a different one -
# answering "23,005 orders" to "delete all customers" is how trust in a tool dies.
DESTRUCTIVE_RE = re.compile(
    r"\b(drop|delete|truncate|erase|wipe|destroy|remove|kill)\b"
    r"[\s\S]{0,25}?\b(table|database|db|rows|records|everything|all|every|"
    r"customers|orders|products|data)\b", re.I)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
class Nl2SqlEngine:
    def __init__(self):
        # THREAD SAFETY: this engine is created once (Streamlit's
        # @st.cache_resource) but every user interaction runs on a DIFFERENT
        # thread. A long-lived sqlite3 connection belongs to the thread that
        # created it, and reusing it elsewhere raises:
        #   "SQLite objects created in a thread can only be used in that same thread"
        # So we hold NO connection: metadata is loaded once here and kept as
        # plain Python data, and each query opens (and closes) its own
        # short-lived read-only connection. Opening a SQLite handle costs
        # microseconds, so this is free.
        con = connect_readonly()
        try:
            row = dict(con.execute("SELECT key, value FROM meta").fetchall())
            self.anchor = pd.Timestamp(row["anchor_date"])
            self.min_date = pd.Timestamp(row["min_date"])
            self.values: dict[str, list] = {}
            for dim, meta in DIMENSIONS.items():
                table = ("v_orders" if dim in ("month", "quarter", "year", "city",
                                               "state", "channel", "payment_method",
                                               "gender") else "v_sales")
                try:
                    self.values[dim] = get_distinct_values(con, meta["col"], table)
                except Exception:
                    self.values[dim] = []
        finally:
            con.close()

        self.values["product"] = []          # 420 SKUs - too noisy for substring matching
        self.time_parser = TimeParser(self.anchor, self.min_date)

    # ------------------------------------------------------------- execution
    @staticmethod
    def run_query(sql: str) -> pd.DataFrame:
        """Execute read-only SQL on a connection opened (and closed) here.

        One connection per query keeps the engine safe to share across threads,
        which is exactly what Streamlit requires.
        """
        con = connect_readonly()
        try:
            return pd.read_sql_query(sql, con)
        finally:
            con.close()

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _norm(q: str) -> str:
        q = q.lower().strip()
        q = re.sub(r"[^\w\s%₹\-\.\/]", " ", q)
        q = re.sub(r"\s+", " ", q)
        return q

    def _detect_metric(self, q: str) -> str | None:
        """Pick the most SPECIFIC metric, not just the longest synonym.

        'How much discount did we give?' contains both 'how much' (revenue) and
        'discount'. Specificity (priority) beats string length, otherwise the
        generic fallback metric would swallow every specific one.
        """
        best, best_key = None, (-1, -1)
        for name, meta in list(METRICS.items()) + list(SPECIAL_METRICS.items()):
            prio = meta.get("priority", 4 if name in SPECIAL_METRICS else 1)
            for syn in meta["synonyms"]:
                if syn in q:
                    key = (prio, len(syn))
                    if key > best_key:
                        best, best_key = name, key
        return best

    def _detect_dimension(self, q: str) -> str | None:
        best, best_len = None, 0
        for name, meta in DIMENSIONS.items():
            for syn in meta["synonyms"]:
                if re.search(rf"\b{re.escape(syn)}\b", q) and len(syn) > best_len:
                    best, best_len = name, len(syn)
        return best

    def _detect_filters(self, q: str, group_dim: str | None) -> list:
        """Detect hard filters such as 'in Chennai' or 'for Electronics'.

        Time dimensions are excluded on purpose: 'revenue in 2025' must become a
        WHERE year=2025 (handled by TimeParser), never a category filter, and
        'worst 3 subcategories' must not read '3' as a quarter filter.
        """
        skip = {"product", "subcategory", "month", "quarter", "year"}
        found, used = [], set()
        for dim, vals in self.values.items():
            if dim == group_dim or dim in skip:
                continue
            hits = [v for v in vals if v and re.search(rf"\b{re.escape(str(v).lower())}\b", q)]
            for h in hits[:1]:
                key = str(h).lower()
                # 'Mobile App' is BOTH a sales channel and an acquisition
                # channel. Consume each value token once, at the first (most
                # natural) dimension, otherwise we AND two filters together and
                # silently under-report.
                if key in used:
                    continue
                used.add(key)
                found.append((dim, h))
        return found

    @staticmethod
    def _detect_topn(q: str):
        m = re.search(r"\b(?:top|bottom|best|worst|highest|lowest|largest|smallest|"
                      r"first|last)\s+(\d+)\b", q)
        n = int(m.group(1)) if m else None
        m2 = re.search(r"\b(\d+)\s+(?:top|bottom|best|worst)\b", q)
        if n is None and m2:
            n = int(m2.group(1))
        if re.search(r"\btop\s+(\d+)?\b|\bbest\b|\bhighest\b|\blargest\b|\bmost\b|\bmaximum\b", q):
            direction = "desc"
        elif re.search(r"\bbottom\s+(\d+)?\b|\bworst\b|\blowest\b|\bsmallest\b|\bleast\b|\bminimum\b", q):
            direction = "asc"
        else:
            direction = "desc"
        return n, direction

    @staticmethod
    def _detect_compare(q: str, tp: TimeParser, allow_fuzzy: bool = True):
        """Detect explicit A-vs-B periods.

        allow_fuzzy=False disables the "last year"/"YoY" fallback, which is
        needed when the question is really comparing two DIMENSION VALUES
        ("Instagram vs Website last year"), not two periods.
        """
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", q)]
        has_cw = any(w in q for w in COMPARE_WORDS)
        if has_cw and len(years) >= 2:
            a, b = sorted(set(years))[-2:]
            return [("year", str(a), f"{a}"), ("year", str(b), f"{b}")]
        if allow_fuzzy and has_cw and re.search(r"\blast year\b|\byoy\b|year over year", q):
            return [("year", str(tp.anchor.year - 1), f"{tp.anchor.year - 1}"),
                    ("year", str(tp.anchor.year), f"{tp.anchor.year}")]
        if has_cw:
            qs = re.findall(r"\bq([1-4])\b", q)
            if len(qs) >= 2:
                yr = years[0] if years else tp.anchor.year
                return [("quarter", f"{yr}/{qs[0]}", f"Q{qs[0]} {yr}"),
                        ("quarter", f"{yr}/{qs[1]}", f"Q{qs[1]} {yr}")]
        return None

    # ---------------------------------------------------------------- parse
    def parse(self, question: str) -> Parsed:
        q = self._norm(question)
        p = Parsed(question=question)

        p.time = self.time_parser.parse(q)
        p.compare = None   # resolved below, once value-compare is known
        detected_metric = self._detect_metric(q)
        p.metric_matched = detected_metric is not None
        p.metric = detected_metric or "revenue"
        p.dimension = self._detect_dimension(q)

        # --- Resolve "period as filter" vs "period as grouping".
        # 'revenue last quarter' -> the quarter is a FILTER (scalar answer).
        # 'revenue by quarter'   -> the quarter is a GROUPING (trend answer).
        has_trend_word = any(w in q for w in TREND_WORDS)
        if (p.time and p.dimension == p.time[2] and not has_trend_word
                and not p.compare):
            p.dimension = None

        # --- "A vs B" over DIMENSION VALUES, not periods.
        # "compare roas for instagram vs website" must group by channel and keep
        # both values. Without this it fell through to a single overall number.
        value_compare = False
        if any(w in q for w in COMPARE_WORDS) and not p.compare:
            cand = {}
            for dim, vals in self.values.items():
                if dim in ("product", "subcategory", "month", "quarter", "year"):
                    continue
                hits = [v for v in vals
                        if v and re.search(rf"\b{re.escape(str(v).lower())}\b", q)]
                if len(hits) >= 2:
                    cand[dim] = hits[:4]
            if cand:
                dim = max(cand, key=lambda d: len(cand[d]))
                p.dimension = dim
                p.filters = [(dim, v) for v in cand[dim]]
                value_compare = True

        if not value_compare:
            p.filters = self._detect_filters(q, p.dimension)
        # Explicit "2024 vs 2025" always wins. The fuzzy "last year"/"YoY"
        # fallback only applies when the question is NOT comparing two values.
        p.compare = self._detect_compare(q, self.time_parser,
                                         allow_fuzzy=not value_compare)
        p.n, p.direction = self._detect_topn(q)

        is_mom = bool(re.search(r"\bmonth over month\b|\bmonth-on-month\b|\bmom\b", q))

        # --- REFUSE-TO-GUESS GATE ------------------------------------------
        # If the question matched no slot at all, it is noise. Returning total
        # revenue for 'asdkjhasd' would look like a working answer and quietly
        # mislead a stakeholder - the worst possible failure mode.
        if not (p.metric_matched or p.dimension or p.time or p.filters
                or p.compare or p.n or is_mom):
            p.intent = "fallback"
            p.confidence = 0.0
            return p

        # --- intent resolution
        # "which month had the HIGHEST revenue" is a RANK question, not a trend:
        # a superlative or explicit top-N wins over the time-dimension rule.
        has_superlative = bool(re.search(
            r"\b(highest|lowest|best|worst|top|bottom|largest|smallest|most|least)\b", q))
        has_trend_word = any(w in q for w in TREND_WORDS)

        if p.compare:
            p.intent = "comparison"
        elif any(w in q for w in SHARE_WORDS) and (p.filters or p.dimension):
            p.intent = "share"
        elif is_mom:
            p.intent = "mom"
            p.dimension = None
        elif (has_superlative or p.n) and not has_trend_word:
            p.intent = "rank"
            if p.dimension is None:
                p.dimension = "city"
            if p.n is None:
                p.n = 1
            if p.metric in ("return_rate", "cancel_rate"):
                if re.search(r"\b(best|highest|top|most)\b", q):
                    p.direction = "asc"
                if re.search(r"\b(worst|lowest)\b", q):
                    p.direction = "desc"
        elif p.dimension in ("month", "quarter", "year") or has_trend_word:
            p.intent = "trend"
            if p.dimension is None:
                p.dimension = "month"
        elif re.search(r"\b(highest|lowest|best|worst|top|bottom|largest|smallest)\b", q):
            p.intent = "rank"
            if p.dimension is None and not p.n:
                p.dimension = "city"
            if p.n is None:
                p.n = 1
            # "worst" is inverted for rate metrics (high return rate = bad)
            if p.metric in ("return_rate", "cancel_rate") and re.search(
                    r"\b(best|highest|top|most)\b", q):
                p.direction = "asc"
            if p.metric in ("return_rate", "cancel_rate") and re.search(
                    r"\b(worst|lowest)\b", q):
                p.direction = "desc"
        elif p.dimension:
            p.intent = "breakdown"
        elif p.metric:
            p.intent = "scalar"
        else:
            p.intent = "fallback"

        # crude confidence for telemetry
        p.confidence = 0.55
        if p.metric: p.confidence += 0.15
        if p.dimension or p.intent in ("scalar", "share"): p.confidence += 0.15
        if p.time: p.confidence += 0.08
        if p.intent == "trend" and p.dimension in ("month", "quarter", "year"): p.confidence += 0.07
        p.confidence = round(min(p.confidence, 0.99), 2)
        return p

    # ----------------------------------------------------------------- build
    @staticmethod
    def _esc(v) -> str:
        return str(v).replace("'", "''")

    def _filter_fragments(self, p: Parsed, col_fn=None) -> list[str]:
        """WHERE fragments for value filters only (no time).

        Two values of the SAME dimension become `IN (...)`. Without this,
        "Instagram vs Website" compiled to
        `channel='Instagram' AND channel='Website'` - a predicate that is
        always false, so the query silently returned zero rows.
        """
        by_dim: dict[str, list] = {}
        for dim, val in p.filters:
            by_dim.setdefault(dim, []).append(val)
        out = []
        for dim, vals in by_dim.items():
            col = DIMENSIONS[dim]["col"]
            col = col_fn(col, dim) if col_fn else col
            esc = [self._esc(v) for v in vals]
            if len(esc) == 1:
                out.append(f"{col} = '{esc[0]}'")
            else:
                out.append(f"{col} IN (" + ", ".join(f"'{v}'" for v in esc) + ")")
        return out

    @staticmethod
    def _time_to_marketing(cond: str) -> str:
        """Translate a v_sales time condition into one usable on marketing_spend."""
        c = cond or ""
        m = re.search(r"year\s*=\s*(\d{4})", c)
        q = re.search(r"quarter\s*=\s*(\d)", c)
        mo = re.search(r"month\s*=\s*'(\d{4}-\d{2})'", c)
        if mo:
            return f"month = '{mo.group(1)}'"
        if m and q:
            y, qq = int(m.group(1)), int(q.group(1))
            months = [f"{y}-{(qq - 1) * 3 + i:02d}" for i in (1, 2, 3)]
            return "month IN (" + ", ".join(f"'{x}'" for x in months) + ")"
        if m:
            return f"month LIKE '{m.group(1)}%'"
        m2 = re.search(r"order_date\s*>=\s*'([\d-]{10})'", c)
        if m2:
            return f"month >= '{m2.group(1)[:7]}'"
        return ""

    def build_sql(self, p: Parsed) -> str:
        is_special = p.metric in SPECIAL_METRICS
        time_cond = p.time[0].replace("{p}", "") if p.time else ""
        f_frags = self._filter_fragments(p)

        # ================================================== 1. COMPARISON
        if p.intent == "comparison" and p.compare:
            fwhere = (" AND " + " AND ".join(f_frags)) if f_frags else ""
            if p.metric in ("return_rate", "cancel_rate"):
                status = "Returned" if p.metric == "return_rate" else "Cancelled"
                parts = []
                for (k, val, lab) in p.compare:
                    y = val.split("/")[0] if k == "quarter" else val
                    parts.append(
                        f"SELECT '{lab}' AS period, ROUND(100.0*(SELECT COUNT(*) FROM v_orders "
                        f"WHERE status='{status}' AND year={y})/NULLIF((SELECT COUNT(*) "
                        f"FROM v_orders WHERE year={y}),0),2) AS value")
                return " UNION ALL ".join(parts)
            if p.metric == "roas":
                parts = []
                for (k, val, lab) in p.compare:
                    y = val.split("/")[0] if k == "quarter" else val
                    parts.append(
                        f"SELECT '{lab}' AS period, ROUND((SELECT SUM(net_revenue) FROM v_sales "
                        f"WHERE year={y})/NULLIF((SELECT SUM(spend) FROM marketing_spend "
                        f"WHERE month LIKE '{y}%'),0),2) AS value")
                return " UNION ALL ".join(parts)
            agg = METRICS[p.metric]["agg"]
            clauses = []
            for (k, val, lab) in p.compare:
                if k == "year":
                    cond = f"year = {val}"
                else:
                    yr, qn = val.split("/")
                    cond = f"year = {yr} AND quarter = {qn}"
                clauses.append(f"SELECT '{lab}' AS period, {agg} AS value "
                               f"FROM v_sales WHERE {cond}{fwhere}")
            return " UNION ALL ".join(clauses) + " ORDER BY period"

        # ======================================================= 2. SHARE
        if p.intent == "share":
            conds = list(f_frags)
            if not conds and p.dimension:
                col = DIMENSIONS[p.dimension]["col"]
                return (f"SELECT {col} AS {p.dimension}, ROUND(SUM(net_revenue),2) AS revenue, "
                        f"ROUND(100.0*SUM(net_revenue)/NULLIF((SELECT SUM(net_revenue) "
                        f"FROM v_sales),0),2) AS share_pct FROM v_sales "
                        f"GROUP BY {col} ORDER BY revenue DESC LIMIT 15")
            cond = " AND ".join(conds) if conds else "1=1"
            tf = f" AND {time_cond}" if time_cond else ""
            return (f"SELECT ROUND(100.0*SUM(CASE WHEN {cond} THEN net_revenue ELSE 0 END)"
                    f"/NULLIF(SUM(net_revenue),0),2) AS share_pct, "
                    f"ROUND(SUM(CASE WHEN {cond} THEN net_revenue ELSE 0 END),2) AS segment_revenue, "
                    f"ROUND(SUM(net_revenue),2) AS total_revenue "
                    f"FROM v_sales WHERE 1=1{tf}")

        # ================================= 2b. MONTH-OVER-MONTH (window fn)
        if p.intent == "mom":
            tw = f"WHERE {time_cond}" if time_cond else ""
            return (f"SELECT month, ROUND(net_revenue - LAG(net_revenue) OVER "
                    f"(ORDER BY month),2) AS mom_change "
                    f"FROM (SELECT month, SUM(net_revenue) AS net_revenue "
                    f"FROM v_sales {tw} GROUP BY month) ORDER BY month")

        # ============================================ 3. SPECIAL (RATE) METRICS
        if is_special:
            sm = SPECIAL_METRICS[p.metric]

            # ---- scalar form
            if p.dimension is None or p.intent == "scalar":
                if p.metric in ("return_rate", "cancel_rate"):
                    status = "Returned" if p.metric == "return_rate" else "Cancelled"
                    t1 = f" AND {time_cond}" if time_cond else ""
                    t2 = f" WHERE {time_cond}" if time_cond else ""
                    return (f"SELECT ROUND(100.0*(SELECT COUNT(*) FROM v_orders "
                            f"WHERE status='{status}'{t1})/NULLIF((SELECT COUNT(*) "
                            f"FROM v_orders{t2}),0),2) AS value")
                if p.metric == "roas":
                    mk = self._time_to_marketing(time_cond)
                    tw = f" WHERE {time_cond}" if time_cond else ""
                    mw = f" WHERE {mk}" if mk else ""
                    return (f"SELECT ROUND((SELECT SUM(net_revenue) FROM v_sales{tw})"
                            f"/NULLIF((SELECT SUM(spend) FROM marketing_spend{mw}),0),2) AS value")
                if p.metric == "spend":
                    mk = self._time_to_marketing(time_cond)
                    mw = f" WHERE {mk}" if mk else ""
                    return f"SELECT ROUND(SUM(spend),2) AS value FROM marketing_spend{mw}"

            # ---- grouped form
            dim = p.dimension
            order = f"ORDER BY value {p.direction.upper()}" if p.intent == "rank" else "ORDER BY value DESC"
            limit = f"LIMIT {p.n}" if (p.intent == "rank" and p.n) else ("LIMIT 25" if p.intent != "rank" else "")

            # ROAS / spend only make sense against channels and months
            if p.metric in ("roas", "spend"):
                dim = dim if dim in ("channel", "month") else "channel"
                col = DIMENSIONS[dim]["col"]
                mk = self._time_to_marketing(time_cond)
                if p.metric == "spend":
                    parts = ([mk] if mk else []) + f_frags
                    mw = (" WHERE " + " AND ".join(parts)) if parts else ""
                    return (f"SELECT {col} AS {dim}, ROUND(SUM(spend),2) AS value "
                            f"FROM marketing_spend{mw} GROUP BY {col} {order} {limit}").strip()
                inner = ([time_cond] if time_cond else []) + f_frags
                iw = (" WHERE " + " AND ".join(inner)) if inner else ""
                return (f"SELECT s.{col} AS {dim}, ROUND(SUM(s.rev)/NULLIF(SUM(m.spend),0),2) AS value "
                        f"FROM (SELECT {col}, month, SUM(net_revenue) AS rev FROM v_sales{iw} "
                        f"GROUP BY {col}, month) s "
                        f"JOIN marketing_spend m ON m.month = s.month AND m.channel = s.channel "
                        f"GROUP BY s.{col} {order} {limit}").strip()

            col = DIMENSIONS[dim]["col"]
            join = ""
            if dim in ("category", "subcategory", "product"):
                col = "p." + col
                join = ("JOIN order_items oi ON oi.order_id = o.order_id "
                        "JOIN products p ON p.product_id = oi.product_id")

            def col_fn(c, d):
                if d in ("category", "subcategory", "product"):
                    return "p." + c
                return "o." + c

            parts = []
            if time_cond:
                parts.append("o." + time_cond)
            parts += self._filter_fragments(p, col_fn)
            where = ("WHERE " + " AND ".join(parts)) if parts else ""
            return re.sub(r"\s+", " ", sm["sql"].format(
                dim_col=col, dim_alias=dim, join=join, where=where,
                inner_where=where, order=f"{order} {limit}")).strip()

        # ==================================================== 4. STANDARD PATH
        agg = METRICS[p.metric]["agg"]
        alias = p.metric
        parts = ([time_cond] if time_cond else []) + f_frags
        where = ("WHERE " + " AND ".join(parts)) if parts else ""

        if p.intent == "scalar" or not p.dimension:
            return f"SELECT {agg} AS {alias} FROM v_sales {where}".strip()

        dim = p.dimension
        if dim == "quarter":
            # Grouping by quarter ALONE would silently merge Q1-2024 with
            # Q1-2025. Always keep the year in the key.
            sel, grp, torder = "year || '-Q' || quarter", "year, quarter", "year, quarter"
        else:
            sel = grp = torder = DIMENSIONS[dim]["col"]

        if p.intent == "trend":
            order, limit = f"ORDER BY {torder} ASC", (f"LIMIT {p.n}" if p.n else "")
        elif p.intent == "rank":
            order, limit = f"ORDER BY {alias} {p.direction.upper()}", (f"LIMIT {p.n}" if p.n else "LIMIT 10")
        else:
            order, limit = f"ORDER BY {torder if dim == 'quarter' else alias} DESC", (f"LIMIT {p.n}" if p.n else "LIMIT 25")

        return (f"SELECT {sel} AS {dim}, {agg} AS {alias} "
                f"FROM v_sales {where} GROUP BY {grp} {order} {limit}").strip()


    # ---------------------------------------------------------------- answer
    def _prompt_for(self, question: str) -> tuple[str, str]:
        """(system, user) messages handed to the LLM."""
        sys_msg = ("You are a senior analytics engineer writing SQLite for an "
                   "Indian D2C retail warehouse. Return ONLY the SQL query - no "
                   "markdown fences and no explanation. Never write DDL or DML.")
        return sys_msg, _build_prompt(question, self.anchor)

    def answer(self, question: str, llm_cfg=None, llm_mode: str = "off") -> dict:
        """Parse -> build -> validate -> execute.

        llm_mode:
          "off"        rules engine only (default; works with no API key)
          "fallback"   rules first; ask the LLM only when rules can't parse
          "llm_first"  ask the LLM first; rules cover for it if it fails
          "both"       run both and report whether they agree
        """
        if question and DESTRUCTIVE_RE.search(question):
            return {"ok": False, "question": question, "parsed": Parsed(question=question),
                    "error": "I only answer read-only analytical questions - I can't "
                             "drop, delete or modify anything (and the database "
                             "connection is read-only anyway)."}

        p = self.parse(question)
        rules_sql = None if p.intent == "fallback" else self.build_sql(p)
        llm_sql = llm_error = blocked_reason = None

        wants_llm = bool(llm_cfg and llm_cfg.enabled and llm_mode != "off")

        if wants_llm and llm_mode in ("llm_first", "both"):
            llm_sql, llm_error = generate_sql(question, llm_cfg, self._prompt_for)
        elif wants_llm and llm_mode == "fallback" and rules_sql is None:
            llm_sql, llm_error = generate_sql(question, llm_cfg, self._prompt_for)

        # ---- pick the primary statement
        if llm_mode in ("llm_first", "both") and llm_sql:
            sql, source = llm_sql, "llm"
        else:
            sql, source = rules_sql, "rules"
        if sql is None:                       # fall back to whichever we have
            sql, source = (llm_sql, "llm") if llm_sql else (rules_sql, "rules")

        if sql is None:
            hint = "  ".join(f"'{e}'" for e in self.example_questions()[:3])
            err = ("I could not map that to a metric, dimension or time period, "
                   "so I'm not going to guess. " f"Try something like: {hint}")
            if llm_error and wants_llm:
                err += f" (LLM back-end also unavailable: {llm_error})"
            return {"ok": False, "question": question, "parsed": p, "error": err}

        # ---- validate. If the chosen statement is unsafe and we HAVE the other
        #      one, fall back to it instead of just failing.
        guard = validate_sql(sql)
        if not guard.ok:
            alt, alt_src = (rules_sql, "rules") if source == "llm" else (llm_sql, "llm")
            if alt:
                alt_guard = validate_sql(alt)
                if alt_guard.ok:
                    blocked_reason = f"BLOCKED BY GUARDRAILS - {guard.reason}"
                    guard, sql, source = alt_guard, alt, alt_src
                else:
                    guard = None
            if guard is None or not guard.ok:
                return {"ok": False, "question": question, "parsed": p, "sql": sql,
                        "error": f"BLOCKED BY GUARDRAILS - {guard.reason if guard else 'unsafe'}"}

        try:
            df = self.run_query(guard.sql)
        except Exception as e:
            return {"ok": False, "question": question, "parsed": p, "sql": guard.sql,
                    "error": f"SQL execution failed: {e}"}

        warnings = list(guard.warnings)
        if source == "rules" and llm_sql:
            warnings.append("The LLM statement was blocked by guardrails, so the "
                            "rules-engine statement was used instead.")
        out = {"ok": True, "question": question, "parsed": p, "sql": guard.sql,
               "raw_sql": sql, "df": df, "source": source, "warnings": warnings,
               "confidence": p.confidence}
        if llm_error:
            out["llm_error"] = llm_error

        # ---- side-by-side comparison mode
        if llm_mode == "both" and wants_llm:
            other, other_src = (rules_sql, "rules") if source == "llm" else (llm_sql, "llm")
            cmp = {"rules_sql": rules_sql, "llm_sql": llm_sql,
                   "llm_error": llm_error, "agrees": None, "other_sql": None,
                   "n_rows_chosen": len(df), "n_rows_other": None}
            if other:
                g2 = validate_sql(other)
                if g2.ok:
                    try:
                        df2 = self.run_query(g2.sql)
                        cmp.update(other_sql=g2.sql, n_rows_other=len(df2),
                                   agrees=_same_result(df, df2))
                    except Exception as e:
                        cmp["other_error"] = str(e)
                else:
                    cmp["other_blocked"] = g2.reason
            out["compare"] = cmp
        return out

    # -------------------------------------------------------------- metadata
    # -------------------------------------------------------------- metadata
    def example_questions(self) -> list[str]:
        return [
            "What was total revenue last quarter?",
            "Top 5 cities by revenue",
            "Monthly revenue trend",
            "Revenue by category in 2025",
            "Which category has the highest margin percentage?",
            "Average order value by channel",
            "Return rate by category",
            "ROAS by channel last year",
            "Compare revenue in 2025 vs 2024",
            "Worst 3 subcategories by margin",
            "How many customers did we have last month?",
            "What share of revenue comes from Chennai?",
            "Units sold by payment method",
            "Cancellation rate by city",
            "Revenue from Electronics in Bengaluru",
        ]


# --------------------------------------------------------------------------
# Optional LLM back-end
# --------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    return text.strip().rstrip(";").strip()


def _build_prompt(question: str, anchor: pd.Timestamp) -> str:
    shots = "\n\n".join(f"Q: {q}\nSQL: {s}" for q, s in FEW_SHOTS)
    return (f"{FULL_SCHEMA_PROMPT}\n"
            f"The latest date in the warehouse is {anchor:%Y-%m-%d}. "
            f"Resolve relative phrases against THAT date, not today.\n\n"
            f"{shots}\n\n"
            f"Q: {question}\nSQL:")


def _same_result(a, b, tol: float = 0.01) -> bool:
    """Do two result sets contain the same data? (order insensitive)"""
    def norm(d):
        if d is None or d.empty:
            return []
        d = d.copy()
        for c in d.columns:
            if pd.api.types.is_numeric_dtype(d[c]):
                d[c] = d[c].astype(float).round(2)
            else:
                d[c] = d[c].astype(str).str.strip()
        return sorted([tuple(r) for r in d.values.tolist()],
                      key=lambda r: tuple(str(x) for x in r))

    ra, rb = norm(a), norm(b)
    if len(ra) != len(rb) or len(ra) == 0:
        return False
    for x, y in zip(ra, rb):
        for u, v in zip(x, y):
            if isinstance(u, float) and isinstance(v, float):
                if abs(u - v) > tol:
                    return False
            elif str(u) != str(v):
                return False
    return True


def llm_generate_sql(question: str, anchor: pd.Timestamp) -> str | None:
    """Backwards-compatible wrapper: use whatever provider the environment has.

    Prefer engine.answer(question, llm_cfg=..., llm_mode=...) for full control.
    """
    cfg = LlmConfig.from_env()
    if not cfg.enabled:
        return None
    sql, err = generate_sql(question, cfg, lambda q: (
        "You write correct, efficient SQLite for an analytics warehouse. "
        "Return only SQL. Never write DDL or DML.", _build_prompt(q, anchor)))
    if err:
        print(f"[llm] {err}")
    return sql
