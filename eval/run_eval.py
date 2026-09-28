"""
STEP 6: EVALUATION HARNESS - the part almost no portfolio project has.

46 hand-labelled questions, each with GOLD SQL written by a human. The harness
runs the engine and the gold query and compares the actual RESULT SETS
(not the SQL text - different but equivalent SQL should still pass).

Why this matters more than the app itself:
  * it proves the thing actually works (most demos are one happy-path screenshot)
  * it gives you a number to put on your CV: "46-question eval suite, X% pass"
  * it lets you find and FIX bugs you would never have found by clicking around
  * publishing the FAILURES is a credibility signal, not a weakness

Run:  python eval/run_eval.py
Out:  reports/eval_scorecard.md
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from guardrails import validate_sql, connect_readonly   # noqa: E402
from nl2sql import Nl2SqlEngine                          # noqa: E402
from llm import LlmConfig                                # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QFILE = os.path.join(BASE, "eval", "questions.json")

# Optional: score the LLM path on the SAME questions for an honest comparison.
#   python eval/run_eval.py --llm                 (LLM first, rules cover)
#   python eval/run_eval.py --llm --mode fallback
ARGS = sys.argv[1:]
USE_LLM = "--llm" in ARGS
LLM_MODE = ARGS[ARGS.index("--mode") + 1] if "--mode" in ARGS else "llm_first"
LLM_CFG = LlmConfig.from_env() if USE_LLM else None
OUT = os.path.join(BASE, "reports",
                   f"eval_scorecard_{LLM_MODE}.md" if USE_LLM else "eval_scorecard.md")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

TOL = 0.01          # absolute tolerance for float comparison


def normalise(df: pd.DataFrame) -> list[tuple]:
    """Order-independent, dtype-tolerant representation of a result set."""
    if df is None or df.empty:
        return []
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].astype(float).round(2)
        else:
            d[c] = d[c].astype(str).str.strip()
    rows = [tuple(r) for r in d.values.tolist()]
    return sorted(rows, key=lambda r: tuple(str(x) for x in r))


def same_result(a: pd.DataFrame, b: pd.DataFrame):
    if a.shape != b.shape:
        return False, f"shape mismatch: engine {a.shape} vs gold {b.shape}"
    ra, rb = normalise(a), normalise(b)
    if len(ra) != len(rb):
        return False, "row count differs after normalisation"
    for x, y in zip(ra, rb):
        for u, v in zip(x, y):
            if isinstance(u, float) and isinstance(v, float):
                if abs(u - v) > TOL:
                    return False, f"value mismatch: {u} vs {v}"
            elif str(u) != str(v):
                return False, f"value mismatch: {u!r} vs {v!r}"
    return True, ""


def run_gold(sql: str, con) -> pd.DataFrame:
    g = validate_sql(sql)
    if not g.ok:
        raise RuntimeError(f"gold SQL rejected by guardrails: {g.reason}")
    return pd.read_sql_query(g.sql, con)


def main():
    if USE_LLM and not LLM_CFG.enabled:
        print("ERROR: --llm needs a key. Set one of: OPENAI_API_KEY, "
              "ANTHROPIC_API_KEY, GEMINI_API_KEY (or run Ollama locally).")
        sys.exit(2)
    engine = Nl2SqlEngine()
    con = connect_readonly()
    questions = json.load(open(QFILE))

    rows = []
    for q in questions:
        res = engine.answer(q["question"], llm_cfg=LLM_CFG,
                              llm_mode=(LLM_MODE if USE_LLM else "off"))
        rec = {
            "id": q["id"], "category": q["category"], "question": q["question"],
            "note": q.get("note", ""),
        }
        # A 'refusal' test PASSES when the engine declines to answer.
        if q["category"] == "refusal" or q.get("expect_refusal"):
            refused = not res.get("ok")
            rec.update(status="PASS" if refused else "FAIL",
                       reason="" if refused else "should have refused, but answered",
                       intent=res["parsed"].intent if res.get("parsed") else "-",
                       sql="" if refused else " ".join(res["sql"].split()),
                       gold="(refusal expected)")
            rows.append(rec)
            continue

        if not res.get("ok"):
            rec.update(status="ERROR", reason=res.get("error", "")[:160],
                       intent="-", sql=res.get("sql", ""), gold=q["gold"])
            rows.append(rec)
            continue

        try:
            gold_df = run_gold(q["gold"], con)
        except Exception as e:
            rec.update(status="ERROR", reason=f"gold SQL failed: {e}"[:160],
                       intent=res["parsed"].intent, sql=res["sql"], gold=q["gold"])
            rows.append(rec)
            continue

        ok, why = same_result(res["df"], gold_df)
        rec["source"] = res.get("source", "-")
        rec.update(status="PASS" if ok else "FAIL",
                   reason="" if ok else why,
                   intent=res["parsed"].intent,
                   metric=res["parsed"].metric,
                   dim=res["parsed"].dimension or "-",
                   sql=" ".join(res["sql"].split()),
                   gold=" ".join(q["gold"].split()))
        rows.append(rec)

    df = pd.DataFrame(rows)

    # ------------------------------------------------------------ scorecard
    total = len(df)
    passed = int((df.status == "PASS").sum())
    failed = int((df.status == "FAIL").sum())
    errored = int((df.status == "ERROR").sum())

    by_cat = (df.groupby("category")
                .agg(total=("id", "count"), passed=("status", lambda s: (s == "PASS").sum()))
                .reset_index())
    by_cat["accuracy"] = (by_cat["passed"] / by_cat["total"] * 100).round(1)
    src_counts = df["source"].value_counts().to_dict() if "source" in df else {}

    answered = int(df[df.status != "PASS"].shape[0])
    honest_refusals = int(df[(df.status == "PASS") &
                             (df.category.isin(["refusal"])) |
                             (df.status == "PASS") & (df.note.astype(str).str.contains("OUT OF SCOPE"))].shape[0])
    lines = [
        "# Evaluation Scorecard - Ask Your Data (Text-to-SQL)",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}  |  Engine: "
        f"**{'LLM (' + LLM_MODE + ')' if USE_LLM else 'rules (offline, deterministic)'}**",
        "",
        (f"Back-end mix: {src_counts}" if USE_LLM else ""),
        "",
        f"## Headline: **{passed}/{total} ({passed/total*100:.1f}%)** with "
        f"**{failed} wrong answers**",
        "",
        "| Outcome | Count |",
        "|---|---|",
        f"| Labelled questions | {total} |",
        f"| Correct result set | {passed} |",
        f"| **Silently wrong (the only real failure mode)** | **{failed}** |",
        f"| Engine error / unparsed | {errored} |",
        "",
        f"Of the {passed} passes, {honest_refusals} are cases where the correct "
        f"behaviour was to **decline to answer** (garbage input, destructive "
        f"requests, or a question type that is out of scope). A copilot that "
        f"refuses is safe; one that answers confidently and wrongly is not.",
        "",
        "### Accuracy by question type",
        "",
        by_cat.to_markdown(index=False),
        "",
        "## Full results",
        "",
        df[["id", "category", "question", "status", "intent", "metric", "dim", "reason"]]
          .to_markdown(index=False),
        "",
        "## Known failures and limitations (published on purpose)",
        "",
    ]

    bad = df[df.status != "PASS"]
    if bad.empty:
        lines.append("None - all questions pass.")
    else:
        for _, r in bad.iterrows():
            lines.append(f"- **#{r['id']} ({r['category']})** _{r['question']}_")
            lines.append(f"  - Status: `{r['status']}` - {r['reason'] or 'see note'}")
            if r["note"]:
                lines.append(f"  - Note: {r['note']}")
            lines.append(f"  - Engine SQL: `{r.get('sql','')}`")
            lines.append(f"  - Gold SQL:   `{r.get('gold','')}`")

    lines += [
        "",
        "## How to read this",
        "",
        "- Comparison is done on the **result set**, not the SQL string, so an "
        "equivalent-but-different query still counts as correct.",
        "- Floats are compared with a tolerance of 0.01 after rounding to 2 dp.",
        "- `degraded` = the engine refuses to fabricate an answer at an invalid "
        "grain and falls back to the finest valid grain.",
        "- `known_gap` = a question type the rules engine genuinely cannot build "
        "yet. Publishing it is the point: it shows what you know you don't know.",
        "",
        "Reproduce with: `python eval/run_eval.py`",
    ]

    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(df[["id", "category", "question", "status", "reason"]].to_string(index=False))
    print(f"\nACCURACY: {passed}/{total} = {passed/total*100:.1f}%  "
          f"(fail={failed}, error={errored})")
    print(by_cat.to_string(index=False))
    if USE_LLM:
        print(f"\nBack-end mix: {src_counts}")
        print("Compare against the rules engine: python eval/run_eval.py")
    print(f"\nScorecard written to {OUT}")


if __name__ == "__main__":
    main()
