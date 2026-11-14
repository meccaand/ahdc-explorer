"""Static checks on agent-written SQL: one read-only SELECT over allow-listed tables.

Used twice, as defense in depth: by the PreToolUse hook (which denies the call before it runs, and the denial
reason goes back to the model) and again inside the run_sql tool itself. The database connection is also
opened read-only, so a write would fail even if both checks were bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from .db import allowed_tables

FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command,
             exp.Merge, exp.TruncateTable, exp.Pragma, exp.Attach, exp.Detach)


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    tables: list[str] = field(default_factory=list)


def check_sql(sql: str) -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, "Empty query.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return GuardResult(False, f"Could not parse the SQL: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return GuardResult(False, "Only one statement per call is allowed.")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        return GuardResult(False, f"Only read-only SELECT queries are allowed (got {stmt.key.upper()}).")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN):
            return GuardResult(False, f"Only read-only SELECT queries are allowed ({node.key.upper()} found).")

    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    tables = sorted({t.name.lower() for t in stmt.find_all(exp.Table) if t.name.lower() not in cte_names})
    unknown = [t for t in tables if t not in allowed_tables()]
    if unknown:
        return GuardResult(False, f"Unknown or disallowed table(s): {', '.join(unknown)}. "
                                  f"Allowed: {', '.join(sorted(allowed_tables()))}.")
    return GuardResult(True, tables=tables)


FILTER_COLUMNS = {"cause": "disease_burden", "measure": "disease_burden", "intervention": "intervention_coverage",
                  "source": "intervention_coverage", "facility_type": "health_facilities"}


def filter_values(sql: str) -> dict[str, list[str]]:
    """Literal values a query filters on for key category columns (e.g. cause = 'malaria'), keyed by the table
    that owns the column. Used for the Source data labels."""
    try:
        stmt = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.ParseError:
        return {}
    found: dict[str, list[str]] = {}
    for node in stmt.find_all(exp.EQ, exp.In):
        col = node.this if isinstance(node.this, exp.Column) else None
        if col is None or col.name.lower() not in FILTER_COLUMNS:
            continue
        lits = [node.expression] if isinstance(node, exp.EQ) else node.expressions
        for lit in lits:
            vals = found.setdefault(FILTER_COLUMNS[col.name.lower()], [])
            if isinstance(lit, exp.Literal) and lit.is_string and lit.this not in vals:
                vals.append(lit.this)
    return found
