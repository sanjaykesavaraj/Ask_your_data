"""
STEP 7: Streamlit front-end for "Ask Your Data".

Tabs:
  1. Ask          - plain-English question -> SQL -> chart -> written insight
  2. Schema       - the warehouse contract and business metric definitions
  3. Data quality - the cleaning audit trail from build_db.py
  4. Guardrails   - interactive proof that destructive SQL cannot run
  5. Evaluation   - the 47-question accuracy scorecard

Run:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from guardrails import validate_sql, connect_readonly, ALLOWED_TABLES  # noqa: E402
from nl2sql import Nl2SqlEngine                                          # noqa: E402
from narrate import narrate, pick_chart, fmt_value, metric_fmt, pretty_col  # noqa: E402
from schema import TABLES_DDL, BUSINESS_RULES                            # noqa: E402
from llm import LlmConfig, generate_sql, PRESETS                      # noqa: E402

# ------------------------------------------------------------------ page setup
st.set_page_config(page_title="Ask Your Data - Text-to-SQL Analytics Copilot",
                   page_icon="📊", layout="wide", initial_sidebar_state="expanded")

# --------------------------------------------------------------- compat shim
def _width_kwargs(full: bool = True) -> dict:
    """Streamlit renamed `use_container_width` to `width="stretch"` and scheduled
    the old argument for removal after 2025-12-31. Emit whichever keyword this
    runtime supports, so the app runs on old AND new Streamlit releases.
    """
    import inspect
    try:
        if "width" in inspect.signature(st.button).parameters:
            return {"width": "stretch" if full else "content"}
    except Exception:
        pass
    return {"use_container_width": full}

W = _width_kwargs()

def ensure_warehouse() -> bool:
    """Self-heal on a fresh checkout.

    data/warehouse.db is GENERATED, not committed. On a brand-new clone - or on
    Streamlit Cloud, whose filesystem starts empty - it does not exist yet, and
    the app used to die with FileNotFoundError before rendering anything.
    So build it on first run instead.
    """
    import subprocess

    db = os.path.join(BASE, "data", "warehouse.db")
    raw_dir = os.path.join(BASE, "data", "raw")
    if os.path.exists(db):
        return False

    with st.spinner("First run on this machine: generating data and building the "
                    "warehouse (about 15 seconds)..."):
        steps = []
        if not (os.path.isdir(raw_dir) and os.listdir(raw_dir)):
            steps.append("src/generate_data.py")
        steps.append("src/build_db.py")
        for script in steps:
            r = subprocess.run([sys.executable, script], cwd=BASE,
                               capture_output=True, text=True)
            if r.returncode != 0:
                st.error(f"`{script}` failed (exit {r.returncode}):\n\n"
                         f"{r.stderr[-2000:]}")
                st.stop()
    return True

@st.cache_resource
def get_engine():
    ensure_warehouse()
    return Nl2SqlEngine()

@st.cache_data(ttl=600)
def table_preview(name: str, limit: int = 8):
    con = connect_readonly()
    try:
        df = pd.read_sql_query(f"SELECT * FROM {name} LIMIT {limit}", con)
    finally:
        con.close()
    return df

@st.cache_data(ttl=600)
def table_counts():
    con = connect_readonly()
    out = {}
    for t in ["customers", "products", "orders", "order_items", "returns",
              "marketing_spend", "v_sales"]:
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            pass
    con.close()
    return out

@st.cache_data(ttl=600)
def eval_summary():
    path = os.path.join(BASE, "reports", "eval_scorecard.md")
    if not os.path.exists(path):
        return None
    txt = open(path).read()
    line = [l for l in txt.splitlines() if l.startswith("## Headline")]
    return line[0].replace("## Headline:", "").strip() if line else None

engine = get_engine()

# -------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## 📊 Ask Your Data")
    st.caption("Text-to-SQL analytics copilot over an Indian D2C retail warehouse.")
    st.markdown("---")

    st.markdown("**SQL engine**")
    provider = st.selectbox(
        "LLM provider (optional)",
        ["Off (rules only)", "OpenAI", "Anthropic", "Groq", "Google Gemini",
         "Ollama (local)", "OpenAI-compatible"],
        index=0,
        help="The app runs fully offline on 'Off (rules only)'. Adding a provider "
             "enables the LLM path - but every statement, from either engine, "
             "still goes through the same read-only guardrails.")

    llm_cfg, llm_mode = LlmConfig("Off (rules only)"), "off"
    if provider != "Off (rules only)":
        needs_key = not provider.startswith("Ollama")
        if needs_key:
            key = st.text_input(
                "API key", type="password",
                help="Held in this browser session only - never written to disk. On "
                     "Streamlit Cloud use Settings -> Secrets instead "
                     "(OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY).")
        else:
            # Ollama authenticates by being on the same machine - no key exists.
            key = ""
            st.caption("Ollama needs no API key. It must be running on the same "
                       "machine as this app - see the warning below.")
        base_default, model_default = PRESETS.get(provider, ("", ""))
        if provider == "Anthropic":
            model_default = "claude-sonnet-4-6"
        elif provider == "Google Gemini":
            model_default = "gemini-2.0-flash"
        model = st.text_input("Model", value=model_default)
        base_url = ""
        if provider.startswith("Ollama"):
            base_url = st.text_input("Ollama endpoint",
                                     value="http://localhost:11434/v1")
            st.warning(
                "**localhost means the machine running this app**, not the "
                "browser you are reading it in. If this app is hosted (Streamlit "
                "Cloud, Docker, a remote box), Ollama must run on that same host "
                "- your laptop's Ollama is unreachable from here. To test Ollama "
                "properly, run the app locally: `streamlit run "
                "app/streamlit_app.py` on the machine running Ollama.")
        elif provider == "OpenAI-compatible":
            base_url = st.text_input("Base URL",
                                     value="https://api.openai.com/v1")
        llm_cfg = LlmConfig(provider, key, model, base_url)

        label_to_mode = {"Rules + LLM fallback": "fallback",
                         "LLM first, rules fallback": "llm_first",
                         "Run both and compare": "both"}
        label = st.radio("Mode", list(label_to_mode), index=0,
                         help="Fallback = rules answer first and only ask the LLM "
                              "when the question can't be parsed. Compare = run "
                              "both and show whether they agree.")
        llm_mode = label_to_mode[label]

        if not llm_cfg.enabled:
            st.caption("Enter an API key to enable.")
            with st.expander("Where do I get a key?"):
                st.markdown(
                    "- **OpenAI** - platform.openai.com/api-keys\n"
                    "- **Groq** - console.groq.com/keys (free tier)\n"
                    "- **Google Gemini** - aistudio.google.com/apikey (free tier)\n"
                    "- **Anthropic** - console.anthropic.com/settings/keys\n"
                    "- **Ollama** - none needed, just run it locally")
        elif provider.startswith("Ollama"):
            st.caption("Needs `ollama serve` running on this host plus a pulled "
                       "model, e.g. `ollama pull qwen2.5-coder:7b`.")
        elif st.button("Test connection", **W):
            with st.spinner("Asking the model for one query..."):
                sql, err = generate_sql(
                    "Top 5 cities by revenue", llm_cfg,
                    lambda q: ("You write SQLite. Return only SQL.",
                               "Schema: v_sales(city, net_revenue). "
                               f"Question: {q}"))
            if err:
                st.error(f"Connection failed: {err}")
            else:
                st.success("Connected.")
                st.code(sql, language="sql")
    else:
        st.caption("Offline rules engine - deterministic, free, reproducible. "
                   "Every answer comes from a template you can read in src/.")

    st.markdown("---")
    st.markdown("**Warehouse**")
    counts = table_counts()
    st.write(f"Anchor date: **{engine.anchor:%d %b %Y}**")
    st.write(f"Revenue lines: **{counts.get('v_sales', 0):,}**")
    st.write(f"Orders: **{counts.get('orders', 0):,}**")

    score = eval_summary()
    if score:
        st.markdown("---")
        st.markdown("**Evaluation suite**")
        st.success(score)

    st.markdown("---")
    st.caption("Portfolio project by a data analytics fresher · Streamlit + SQLite")

# ------------------------------------------------------------------ main title
st.title("Ask Your Data")
st.caption("Type a business question in plain English. The app writes the SQL, validates "
           "it against read-only guardrails, runs it, charts it, and explains the answer.")

tab_ask, tab_schema, tab_dq, tab_guard, tab_eval = st.tabs(
    ["💬 Ask", "🗂️ Schema", "🧹 Data quality", "🛡️ Guardrails", "🎯 Evaluation"])

# ================================================================ ASK TAB
with tab_ask:
    examples = engine.example_questions()
    cols = st.columns(4)
    picked = None
    for i, ex in enumerate(examples[:8]):
        if cols[i % 4].button(ex, key=f"ex{i}", **W):
            picked = ex

    with st.form("ask_form", clear_on_submit=False):
        q = st.text_input("Your question",
                          value=picked or "Top 5 cities by revenue last quarter",
                          placeholder="e.g. Which category has the highest margin percentage?")
        submitted = st.form_submit_button("Run query", type="primary", **W)

    if submitted and q.strip():
        with st.spinner("Parsing → generating SQL → validating → executing"):
            res = engine.answer(q.strip(), llm_cfg=llm_cfg, llm_mode=llm_mode)

        if not res.get("ok"):
            st.error(res.get("error", "Something went wrong."))
            if res.get("sql"):
                st.code(res["sql"], language="sql")
        else:
            p = res["parsed"]
            df = res["df"]

            # ---- interpretation chips
            chips = [f"intent: {p.intent}", f"metric: {p.metric_label}",
                     f"engine: {res['source']}", f"confidence: {p.confidence:.0%}"]
            if p.dimension:
                chips.append(f"group by: {p.dimension}")
            if p.time:
                chips.append(f"period: {p.time[1]}")
            for d, v in p.filters:
                chips.append(f"filter: {d} = {v}")
            chips.append("read-only")
            st.caption(" · ".join(chips))

            # ---- insight first (analysts lead with the answer)
            st.info(narrate(q, df, p, engine.anchor))

            # ---- chart + table
            chart = pick_chart(df, p)
            left, right = st.columns([1.35, 1])
            with left:
                if chart == "metric":
                    col = df.columns[-1]
                    st.metric(label=pretty_col(col),
                              value=fmt_value(df.iloc[0, -1], metric_fmt(p.metric)))
                elif df.shape[1] >= 2:
                    xcol, ycol = df.columns[0], df.columns[1]
                    if chart == "line":
                        fig = px.line(df, x=xcol, y=ycol, markers=True)
                    elif chart == "bar_h":
                        fig = px.bar(df.sort_values(ycol), x=ycol, y=xcol,
                                     orientation="h")
                    else:
                        fig = px.bar(df, x=xcol, y=ycol)
                    fig.update_layout(height=380, margin=dict(l=8, r=8, t=24, b=8),
                                      plot_bgcolor="rgba(0,0,0,0)",
                                      paper_bgcolor="rgba(0,0,0,0)",
                                      xaxis_title=pretty_col(xcol),
                                      yaxis_title=pretty_col(ycol))
                    st.plotly_chart(fig, **W)
            with right:
                st.dataframe(df, **W, height=340,
                             hide_index=True)

            if res.get("llm_error"):
                st.warning(f"LLM back-end unavailable ({res['llm_error']}) - "
                           f"this answer came from the rules engine.")

            cmp = res.get("compare")
            if cmp:
                with st.expander("Rules vs LLM - side by side", expanded=False):
                    st.write(f"Answer above came from: **{res['source']}**")
                    if cmp["agrees"] is True:
                        st.success("Both engines returned identical result sets.")
                    elif cmp["agrees"] is False:
                        st.warning("The two engines returned DIFFERENT results - "
                                   "worth investigating before trusting either.")
                    else:
                        st.info("No comparison: the other engine produced no "
                                "runnable SQL for this question.")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Rules engine**")
                        st.code(cmp.get("rules_sql") or "(could not parse)",
                                language="sql")
                    with c2:
                        st.markdown("**LLM**")
                        st.code(cmp.get("llm_sql") or cmp.get("llm_error")
                                or "(no SQL returned)", language="sql")
                    if cmp.get("other_blocked"):
                        st.error(f"Other statement blocked by guardrails: "
                                 f"{cmp['other_blocked']}")
                    if cmp.get("n_rows_other") is not None:
                        st.caption(f"Rows returned - chosen: "
                                   f"{cmp['n_rows_chosen']}, other: "
                                   f"{cmp['n_rows_other']}")

            # ---- SQL + provenance
            with st.expander("Generated SQL", expanded=True):
                st.code(res["sql"], language="sql")
                st.caption(f"Generated by the **{res['source']}** back-end · "
                           f"validated by `guardrails.validate_sql()` before execution")
                if res.get("warnings"):
                    for w in res["warnings"]:
                        st.warning(w)
                st.download_button("Download result CSV",
                                   df.to_csv(index=False).encode(),
                                   file_name="result.csv", mime="text/csv")

            st.caption(f"Business definition in force: revenue is recognised on "
                       f"delivered orders only; net_revenue = "
                       f"(quantity × unit_price) − discount. "
                       f"Data anchored to {engine.anchor:%d %b %Y}.")

# ============================================================== SCHEMA TAB
with tab_schema:
    st.markdown("### Warehouse contract")
    st.markdown("Business logic lives in SQL **views**, so every query and every "
                "dashboard agrees on what \"revenue\" means.")
    st.code(TABLES_DDL.strip(), language="sql")
    st.markdown("### Business definitions")
    st.code(BUSINESS_RULES.strip(), language="sql")
    st.markdown("### Row counts")
    st.dataframe(pd.DataFrame({"table": list(counts), "rows": list(counts.values())}),
                 **W, hide_index=True)
    st.markdown("### Sample data")
    tname = st.selectbox("Preview table", list(counts))
    st.dataframe(table_preview(tname), **W, hide_index=True)

# ========================================================= DATA QUALITY TAB
with tab_dq:
    st.markdown("### Data quality audit trail")
    st.markdown("Every transformation `src/build_db.py` applied to the raw files, "
                "recorded row-by-row. This is the evidence that the pipeline "
                "handles messy data on purpose.")
    con = connect_readonly()
    try:
        log = pd.read_sql_query("SELECT * FROM data_quality_log", con)
    finally:
        con.close()
    if not log.empty:
        st.dataframe(log[["table", "issue", "action", "rows_before",
                          "rows_after", "rows_affected", "note"]],
                     **W, hide_index=True)
        total_fixed = int(log["rows_affected"].sum())
        st.metric("Rows affected by cleaning", f"{total_fixed:,}")
    st.markdown("---")
    st.markdown("### Why the raw data is dirty")
    st.markdown("""
The raw CSVs in `data/raw/` were generated with deliberate defects, mirroring a
real ERP/Excel export:

| Defect | Example |
|---|---|
| Mixed-case + padded city names | `chennai`, `CHENNAI `, `  Chennai  ` |
| Two date formats in one column | `31-08-2026` and `2026-08-31` |
| Currency stored as text | `Rs.1,299.00`, `₹1,299`, `INR 1,299.00` |
| Duplicate rows | 200 duplicated order lines, 120 duplicated customers |
| Orphan foreign keys | 40 line items pointing at a non-existent order |
| Negative / zero quantities | −1 and 0 from data-entry errors |
| Missing values | null emails, null cities, 8 products with no cost price |
| Inconsistent status casing | `DELIVERED`, `Delivered `, `delivered` |
""")

# ============================================================ GUARDRAILS TAB
with tab_guard:
    st.markdown("### 🛡️ Read-only by construction")
    st.markdown("""
Three independent layers stop an LLM (or a user) from touching the data:

1. **A validator** - `validate_sql()` allows only `SELECT`/`WITH`, blocks 20
   destructive keywords, checks every table against an allowlist, rejects stacked
   statements, and injects a `LIMIT` if one is missing.
2. **A read-only connection** - the app opens SQLite with `mode=ro`, so even a
   bug in layer 1 cannot mutate anything.
3. **An allowlisted schema** - only 10 curated tables/views are reachable.

Try it yourself:""")

    presets = {
        "DROP TABLE orders": "DROP TABLE orders",
        "DELETE FROM orders WHERE city = 'Chennai'": "DELETE FROM orders WHERE city = 'Chennai'",
        "UPDATE products SET mrp = 1": "UPDATE products SET mrp = 1",
        "SELECT * FROM sqlite_master (not allowlisted)": "SELECT * FROM sqlite_master",
        "SELECT * FROM users (unknown table)": "SELECT * FROM users",
        "Stacked statement": "SELECT 1; DROP TABLE orders",
        "Valid query, no LIMIT": "SELECT city, ROUND(SUM(net_revenue),2) AS revenue FROM v_sales GROUP BY city",
    }
    choice = st.selectbox("Try a statement", list(presets))
    custom = st.text_input("...or write your own", value=presets[choice])
    if st.button("Validate", type="primary"):
        g = validate_sql(custom)
        if g.ok:
            st.success(f"✅ ALLOWED - {g.reason}")
            st.code(g.sql, language="sql")
            for w in g.warnings:
                st.warning(w)
            try:
                con = connect_readonly()
                out = pd.read_sql_query(g.sql, con)
                con.close()
                st.dataframe(out.head(20), **W, hide_index=True)
            except Exception as e:
                st.error(f"Execution error: {e}")
        else:
            st.error(f"⛔ BLOCKED - {g.reason}")

    st.markdown("---")
    st.markdown("#### Proof the connection is read-only")
    if st.button("Attempt a write at the connection level"):
        try:
            con = connect_readonly()
            con.execute("DELETE FROM orders WHERE 1=1")
            st.error("Write succeeded - the guardrail is broken!")
        except Exception as e:
            st.success(f"Write refused by SQLite itself: `{type(e).__name__}: {e}`")
        finally:
            try:
                con.close()
            except Exception:
                pass

    st.markdown("---")
    st.markdown("#### Allowlisted tables")
    st.code(", ".join(sorted(ALLOWED_TABLES)))

# =========================================================== EVALUATION TAB
with tab_eval:
    st.markdown("### 🎯 Does it actually work?")
    path = os.path.join(BASE, "reports", "eval_scorecard.md")
    if os.path.exists(path):
        txt = open(path).read()
        head = txt.split("### Accuracy by question type")[0]
        st.markdown(head)
        st.markdown("---")
        st.markdown("### Accuracy by question type")
        st.markdown(txt.split("### Accuracy by question type")[1]
                       .split("## Full results")[0])
        st.markdown("---")
        st.markdown("### Known failures and limitations")
        st.markdown("## Known failures".join(
            txt.split("## Known failures")[1:]).split("## How to read this")[0])
        st.markdown("---")
        st.markdown(txt.split("## How to read this")[1] if "## How to read this" in txt else "")
    else:
        st.info("Run `python eval/run_eval.py` to generate the scorecard.")

st.markdown("---")
st.caption(f"Built {datetime.now():%b %Y} · Streamlit {st.__version__} · "
           f"Python + SQLite · no data leaves your machine")
