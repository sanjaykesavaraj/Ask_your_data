"""
STEP 5: Turn a result table into a plain-English insight.

A dashboard shows numbers; an analyst explains them. This module writes the
one-paragraph memo a business stakeholder would actually read - with
concentration risk, growth rates and an explicit caveat where it applies.
"""
from __future__ import annotations

import re
import pandas as pd

from schema import METRICS, SPECIAL_METRICS


# ------------------------------------------------------------------ formatting
def fmt_inr(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e7:
        return f"{sign}Rs.{a/1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{sign}Rs.{a/1e5:,.2f} L"
    return f"{sign}Rs.{a:,.0f}"


def fmt_value(v, fmt: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    if fmt == "currency":
        return fmt_inr(v)
    if fmt == "pct":
        return f"{v:,.2f}%"
    if fmt == "ratio":
        return f"{v:,.2f}x"
    if fmt == "int":
        return f"{int(v):,}"
    return f"{v:,.2f}"


def metric_fmt(name: str) -> str:
    if name in METRICS:
        return METRICS[name]["fmt"]
    if name in SPECIAL_METRICS:
        return SPECIAL_METRICS[name]["fmt"]
    return "number"


def pretty_col(c: str) -> str:
    return c.replace("_", " ").title()


# ------------------------------------------------------------------- narrative
def narrate(question: str, df: pd.DataFrame, parsed, anchor) -> str:
    if df is None or df.empty:
        return "No rows returned for that question - the filters may be too narrow."

    intent = parsed.intent
    metric = parsed.metric
    label = parsed.metric_label
    fmt = metric_fmt(metric)
    period = parsed.time[1] if parsed.time else None
    suffix = f" in {period}" if period else ""

    # ------------------------------------------------------------ scalar
    if intent == "scalar" and df.shape == (1, 1):
        col = df.columns[0]
        val = df.iloc[0, 0]
        return (f"**{pretty_col(col)}**{suffix}: **{fmt_value(val, fmt)}**. "
                f"(Metric definition: {label}. Data anchored to {anchor:%d %b %Y}.)")

    # ------------------------------------------------------------ share
    if intent == "share" and "share_pct" in df.columns and df.shape[0] == 1:
        r = df.iloc[0]
        return (f"That segment accounts for **{r['share_pct']:.2f}%** of net revenue - "
                f"{fmt_inr(r['segment_revenue'])} of {fmt_inr(r['total_revenue'])}"
                f"{suffix}.")

    # ------------------------------------------------------------ comparison
    if intent == "comparison" and {"period", "value"} <= set(df.columns):
        df2 = df.dropna()
        if len(df2) >= 2:
            a, b = df2.iloc[0], df2.iloc[-1]
            try:
                delta = (float(b["value"]) - float(a["value"])) / abs(float(a["value"])) * 100
                dstr = f"{delta:+.1f}%"
            except ZeroDivisionError:
                dstr = "n/a"
            word = "up" if str(dstr).startswith("+") else "down"
            out = (f"{label} went **{word} {dstr}**: {a['period']} = "
                   f"{fmt_value(a['value'], fmt)} vs {b['period']} = "
                   f"{fmt_value(b['value'], fmt)}. "
                   f"Absolute change: {fmt_value(float(b['value']) - float(a['value']), fmt)}.")

            # Like-for-like guard: the newest calendar year is only complete up
            # to the warehouse anchor date. Comparing a stub year against a
            # full year is the single easiest way to publish a wrong number.
            latest = str(b["period"])
            if latest.isdigit() and int(latest) == anchor.year:
                out += (f" ⚠️ **Like-for-like caveat:** {latest} only covers "
                        f"Jan–{anchor:%b} (data ends {anchor:%d %b %Y}), while "
                        f"{a['period']} is a full 12 months. This is "
                        f"like-for-*unlike* — use a year-to-date comparison "
                        f"(Jan–{anchor:%b} {int(latest) - 1} vs Jan–{anchor:%b} "
                        f"{latest}) before drawing a conclusion.")
            return out

    # ---------------------------------------------------------------- MoM
    if intent == "mom" and "mom_change" in df.columns:
        s = df.dropna()
        if s.empty:
            return "Not enough periods to compute a month-over-month change."
        avg = float(s["mom_change"].mean())
        best = s.loc[s["mom_change"].idxmax()]
        worst = s.loc[s["mom_change"].idxmin()]
        ups = int((s["mom_change"] > 0).sum())
        return (f"Month-over-month {label.lower()} change: average "
                f"{fmt_inr(avg)} per month across {len(s)} months{(' (' + period + ')') if period else ''}. "
                f"Best month: {best['month']} ({fmt_inr(best['mom_change'])}), "
                f"worst: {worst['month']} ({fmt_inr(worst['mom_change'])}). "
                f"{ups} of {len(s)} months grew. The first row is NULL by "
                f"definition - there is no prior month to difference against.")

    # ------------------------------------------------------------ trend
    if intent == "trend" and df.shape[0] > 1:
        dcol, vcol = df.columns[0], df.columns[1]
        s = df.dropna()
        first, last = s.iloc[0], s.iloc[-1]
        try:
            growth = (float(last[vcol]) - float(first[vcol])) / abs(float(first[vcol])) * 100
            gstr = f"{growth:+.1f}%"
        except ZeroDivisionError:
            gstr = "n/a"
        best = s.loc[s[vcol].idxmax()]
        worst = s.loc[s[vcol].idxmin()]
        avg = float(s[vcol].mean())
        return (f"{label} across {len(s)} periods{(' (' + period + ')') if period else ''}: "
                f"from {fmt_value(first[vcol], fmt)} in {first[dcol]} to "
                f"{fmt_value(last[vcol], fmt)} in {last[dcol]} "
                f"({gstr} first-to-last). Peak: {best[dcol]} at "
                f"{fmt_value(best[vcol], fmt)}; trough: {worst[dcol]} at "
                f"{fmt_value(worst[vcol], fmt)}; period average {fmt_value(avg, fmt)}. "
                f"Volatility (std/mean): {float(s[vcol].std())/avg*100:.1f}%.")

    # ------------------------------------------------------------ rank / breakdown
    if df.shape[1] >= 2:
        dcol, vcol = df.columns[0], df.columns[1]
        s = df.dropna().copy()
        if s.empty:
            return "No comparable rows returned."
        s[vcol] = pd.to_numeric(s[vcol], errors="coerce")
        s = s.dropna(subset=[vcol])
        total = float(s[vcol].sum())
        top = s.iloc[0]
        ascending = (parsed.intent == "rank" and parsed.direction == "asc")
        share = (float(top[vcol]) / total * 100) if total else 0

        if len(s) == 1:
            verb = "ranks lowest on" if ascending else "is the top performer on"
            return (f"**{top[dcol]}** {verb} {label.lower()}: "
                    f"{fmt_value(top[vcol], fmt)}{suffix}. "
                    f"Only one row matched, so there is no spread to compare.")

        verb = "ranks lowest on" if ascending else "leads on"
        parts = [f"**{top[dcol]}** {verb} {label.lower()} with "
                 f"{fmt_value(top[vcol], fmt)} ({share:.1f}% of the "
                 f"{len(s)} rows shown)."]
        # share-of-total breakdowns carry a share_pct column - call it out
        if "share_pct" in df.columns:
            parts.append(f"That is **{float(top['share_pct']):.1f}% of total "
                         f"revenue** for {top[dcol]}.")
        if len(s) >= 3:
            top3 = float(s.head(3)[vcol].sum()) / total * 100 if total else 0
            parts.append(f"The top 3 concentrate {top3:.1f}% of the "
                         f"{'rows shown' if len(s) > 3 else 'total'}.")
        if len(s) >= 2:
            bot = s.iloc[-1]
            parts.append(f"At the other end, {bot[dcol]} is at "
                         f"{fmt_value(bot[vcol], fmt)}")
            try:
                ratio = float(bot[vcol]) / float(top[vcol]) if ascending else float(top[vcol]) / float(bot[vcol])
                if abs(ratio) > 1.0001:
                    parts.append(f"- a {ratio:.1f}x spread between best and worst.")
                else:
                    parts.append(".")
            except ZeroDivisionError:
                parts.append(".")
        if fmt == "pct":
            parts.append(" Rates below ~2% are within normal noise for a business this size.")
        return " ".join(parts)

    return f"{df.shape[0]} rows returned."


# ------------------------------------------------------------------ chart type
def pick_chart(df: pd.DataFrame, parsed) -> str:
    if df is None or df.empty:
        return "table"
    if parsed.intent == "scalar":
        return "metric"
    if df.shape[0] == 1:
        return "metric"
    if parsed.intent == "mom":
        return "line"
    if parsed.intent in ("trend", "comparison"):
        return "line" if parsed.intent == "trend" else "bar"
    if df.shape[0] > 8 or df.shape[1] > 2:
        return "bar_h"
    return "bar"
