"""
STEP 3: SQL GUARDRAILS - the piece that turns this from a toy into a
production-minded project.

Rules enforced:
  1. Only SELECT / WITH ... SELECT statements are allowed.
  2. Destructive / DDL keywords are blocked (INSERT, UPDATE, DELETE, DROP, ...).
  3. Only whitelisted tables/views may be referenced.
  4. Only one statement may run (no stacked queries via ';').
  5. A LIMIT is injected if missing (no accidental 50M-row pulls).
  6. The database is opened READ-ONLY at the SQLite level (defence in depth),
     so even a bug in 1-5 cannot mutate data.

Interview line: "The model writes the SQL, but a validator decides whether it
runs - and the DB connection is literally read-only."
"""
from __future__ import annotations

import os
import re
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "warehouse.db")

ALLOWED_TABLES = {
    "v_sales", "v_orders", "v_returns", "orders", "order_items",
    "products", "customers", "marketing_spend", "meta", "data_quality_log",
}

# Keywords that must never appear anywhere in the statement
FORBIDDEN = [
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "pragma", "vacuum", "reindex",
    "begin", "commit", "rollback", "grant", "revoke", "exec", "trigger",
    "load_extension", "writable_schema",
]

MAX_LIMIT = 5000


class GuardResult:
    def __init__(self, ok: bool, sql: str = "", reason: str = "", warnings=None):
        self.ok = ok
        self.sql = sql
        self.reason = reason
        self.warnings = warnings or []

    def __repr__(self):
        return f"<GuardResult ok={self.ok} reason={self.reason!r}>"


def _strip_sql(sql: str) -> str:
    """Remove comments and trailing semicolons."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip().rstrip(";").strip()


def _tables_used(sql: str) -> set[str]:
    return {t.lower() for t in re.findall(
        r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", sql, flags=re.I)}


def _cte_names(sql: str) -> set[str]:
    """Names introduced by a WITH clause are NOT tables.

    Without this, `WITH x AS (SELECT ...) SELECT * FROM x` was rejected for
    referencing an unknown table 'x' - which would break every CTE an LLM
    (or a human) writes.
    """
    return {m.group(1).lower() for m in re.finditer(
        r"(?:\bwith\b|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", sql, flags=re.I)}


def validate_sql(raw_sql: str) -> GuardResult:
    """Validate (and lightly rewrite) a SQL string. Never raises."""
    if not raw_sql or not str(raw_sql).strip():
        return GuardResult(False, "", "Empty SQL statement.")

    sql = _strip_sql(raw_sql)

    # Rule 4 - stacked statements
    if ";" in sql:
        return GuardResult(False, sql, "Blocked: multiple statements detected (';').")

    low = sql.lower().lstrip()

    # Rule 1 - must start with SELECT or WITH
    if not (low.startswith("select") or low.startswith("with")):
        return GuardResult(False, sql,
                           f"Blocked: statement must start with SELECT or WITH (got "
                           f"{sql.split()[0]!r}).")

    # Rule 2 - forbidden keywords (word-boundary, so 'created_at' is fine
    #          but 'create table' is not)
    for kw in FORBIDDEN:
        if re.search(rf"\b{kw}\b", low):
            return GuardResult(False, sql,
                               f"Blocked: forbidden keyword '{kw.upper()}'. "
                               f"This tool is read-only.")

    # Rule 3 - table allowlist
    used = _tables_used(sql)
    if not used:
        return GuardResult(False, sql, "Blocked: no recognisable table reference.")
    unknown = used - ALLOWED_TABLES - _cte_names(sql)
    if unknown:
        return GuardResult(False, sql,
                           f"Blocked: unknown/forbidden table(s) {sorted(unknown)}. "
                           f"Allowed: {sorted(ALLOWED_TABLES)}")

    # Rule 5 - inject LIMIT
    warnings = []
    if not re.search(r"\blimit\b", low):
        sql = f"{sql}\nLIMIT {MAX_LIMIT}"
        warnings.append(f"No LIMIT supplied - injected LIMIT {MAX_LIMIT}.")

    return GuardResult(True, sql, "OK", warnings)


# ------------------------------------------------------------------ execution
def connect_readonly() -> sqlite3.Connection:
    """Open the warehouse READ-ONLY (SQLite-level enforcement)."""
    if not os.path.exists(DB):
        raise FileNotFoundError(f"Database not found: {DB}. Run: python src/build_db.py")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def explain(sql: str) -> str:
    """Return the query plan - lets the app show 'this query is cheap/safe'."""
    try:
        con = connect_readonly()
        rows = con.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        con.close()
        return "\n".join(r[3] for r in rows)
    except Exception as e:  # pragma: no cover
        return f"(could not explain: {e})"
