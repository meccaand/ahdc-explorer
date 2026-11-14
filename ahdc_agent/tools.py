"""Custom tools exposed to the agent through an in-process SDK MCP server named "ahdc".

Every tool's text result starts with a one-line summary (shown in the UI as "⎿ summary"), then a blank line,
then the details the model reads.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

from . import db
from .sql_guard import check_sql
from .state import QueryRecord, SessionState, confidence

SERVER = "ahdc"
SHOW_ROWS = 200  # rows of a result shown to the model (all rows up to db.MAX_ROWS are kept for charts)
READ_ONLY = ToolAnnotations(readOnlyHint=True)
CHECKS = ("completeness", "finality", "definition", "consistency")  # confidence rubric, defined in the skill

REGION_SCHEMES = {
    "wb_region": "World Bank region",
    "who_region": "WHO region",
    "un_subregion": "UN M49 subregion",
    "income_group": "World Bank income group",
    "asean": "ASEAN membership",
}


def full_name(tool_name: str) -> str:
    return f"mcp__{SERVER}__{tool_name}"


def ok(summary: str, body: str = "") -> dict[str, Any]:
    text = summary if not body else f"{summary}\n\n{body}"
    return {"content": [{"type": "text", "text": text}]}


def err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def fmt_value(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:.4g}" if abs(v) < 1e4 else f"{v:.0f}"
    return str(v)


def table_text(columns: list[str], rows: list[tuple], limit: int = SHOW_ROWS) -> str:
    lines = [" | ".join(columns)]
    lines += [" | ".join(fmt_value(v) for v in r) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows not shown (all rows are kept for render_chart)")
    return "\n".join(lines)


def build_server(state: SessionState, review: bool = False):
    """Create the in-process MCP server for one session. Returns (server config, full tool names)."""
    tools = build_tools(state, review)
    return create_sdk_mcp_server(SERVER, "1.0.0", tools=tools), [full_name(t.name) for t in tools]


def build_tools(state: SessionState, review: bool = False) -> list:
    """The tool objects. They are closures over this session's state."""

    @tool("list_tables", "List the tables in the AHDC database with a one-line description of each. "
          "Start here if you don't know which table holds an indicator.", {}, annotations=READ_ONLY)
    async def list_tables(args: dict[str, Any]) -> dict[str, Any]:
        dd = db.dictionary()
        lines = [f"- {name}: {t['description']} (grain: {t['grain']})" for name, t in dd["tables"].items()]
        notes = "\n".join(f"- {n}" for n in dd["dataset"]["notes"])
        return ok(f"{len(lines)} tables", "\n".join(lines) + f"\n\nDataset notes:\n{notes}")

    @tool("describe_table", "Describe one table: columns, types, units, allowed values, caveats, row count, "
          "year range and sample rows. Always describe a table before querying it.",
          {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
          annotations=READ_ONLY)
    async def describe_table(args: dict[str, Any]) -> dict[str, Any]:
        name = args["table"].strip().lower()
        tables = db.dictionary()["tables"]
        if name not in tables:
            return err(f"Unknown table '{name}'. Tables: {', '.join(tables)}")
        t = tables[name]
        con = db.connect()
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            years = con.execute(f"SELECT MIN(year), MAX(year) FROM {name}").fetchone() if "year" in t["columns"] else None
            sample = con.execute(f"SELECT * FROM {name} LIMIT 3")
            cols = [d[0] for d in sample.description]
            sample_rows = sample.fetchall()
        finally:
            con.close()
        col_lines = []
        for c, spec in t["columns"].items():
            spec = spec or {}
            bits = [spec.get("type", "")]
            for k in ("unit", "description"):
                if spec.get(k):
                    bits.append(str(spec[k]))
            if spec.get("values"):
                bits.append(f"values: {spec['values']}")
            if spec.get("value_labels"):
                bits.append(f"labels: {spec['value_labels']}")
            col_lines.append(f"- {c}: " + " · ".join(b for b in bits if b))
        caveats = "\n".join(f"- {c}" for c in t.get("caveats", []))
        year_text = f" · {years[0]}–{years[1]}" if years else ""
        body = (f"{t['description']}\nGrain: {t['grain']}\n\nColumns:\n" + "\n".join(col_lines)
                + (f"\n\nCaveats:\n{caveats}" if caveats else "")
                + f"\n\nSample rows:\n{table_text(cols, sample_rows)}")
        return ok(f"{len(t['columns'])} columns · {n:,} rows{year_text}", body)

    @tool("get_region_members", "List the countries in a region under a given scheme. Region names differ "
          "between schemes (e.g. World Bank 'Sub-Saharan Africa' vs WHO 'African Region'), so resolve the "
          "region explicitly before aggregating. Schemes: wb_region, who_region, un_subregion, income_group, "
          "asean. For asean, region is ignored and as_of_year (optional) filters by joining year.",
          {"type": "object", "properties": {
              "scheme": {"type": "string", "enum": list(REGION_SCHEMES)},
              "region": {"type": "string"},
              "as_of_year": {"type": "integer"}},
           "required": ["scheme"]}, annotations=READ_ONLY)
    async def get_region_members(args: dict[str, Any]) -> dict[str, Any]:
        scheme, region = args["scheme"], (args.get("region") or "").strip()
        con = db.connect()
        try:
            if scheme == "asean":
                year = args.get("as_of_year") or 9999
                rows = con.execute("SELECT iso3, name, asean_join_year FROM countries WHERE asean_join_year <= ? "
                                   "ORDER BY name", (year,)).fetchall()
                label = "ASEAN members" + (f" as of {args['as_of_year']}" if args.get("as_of_year") else "")
            else:
                valid = [r[0] for r in con.execute(f"SELECT DISTINCT {scheme} FROM countries ORDER BY 1")]
                match = next((v for v in valid if v.lower() == region.lower()), None)
                if not match:
                    return err(f"No {REGION_SCHEMES[scheme]} named '{region}'. Valid values: {', '.join(valid)}")
                rows = con.execute(f"SELECT iso3, name FROM countries WHERE {scheme} = ? ORDER BY name",
                                   (match,)).fetchall()
                label = f"{REGION_SCHEMES[scheme]} '{match}'"
        finally:
            con.close()
        body = f"{label}: {len(rows)} countries\n" + "\n".join(" · ".join(map(str, r)) for r in rows)
        state.lookups.append((state.turn.index, f"get_region_members({scheme}, {region or args.get('as_of_year', '')})",
                              f"{label}: {len(rows)} countries"))
        return ok(f"{len(rows)} countries · {label}", body)

    @tool("get_data_notes", "Get known caveats, data gaps and methodology changes for a table, optionally "
          "narrowed to an indicator (cause or intervention), a country (iso3) or a year. Check this before "
          "answering.",
          {"type": "object", "properties": {
              "table": {"type": "string"}, "indicator": {"type": "string"},
              "iso3": {"type": "string"}, "year": {"type": "integer"}},
           "required": ["table"]}, annotations=READ_ONLY)
    async def get_data_notes(args: dict[str, Any]) -> dict[str, Any]:
        sql = ("SELECT table_name, indicator, iso3, year_from, year_to, note FROM data_notes "
               "WHERE (table_name = ? OR table_name = '*')")
        params: list[Any] = [args["table"].strip().lower()]
        if args.get("indicator"):
            sql += " AND (indicator IS NULL OR indicator = ?)"
            params.append(args["indicator"])
        if args.get("iso3"):
            sql += " AND (iso3 IS NULL OR iso3 = ?)"
            params.append(args["iso3"].upper())
        if args.get("year"):
            sql += " AND (year_from IS NULL OR ? BETWEEN year_from AND year_to)"
            params.append(args["year"])
        res = db.run_query(sql, tuple(params))
        lines = []
        for table, ind, iso, y0, y1, note in res.rows:
            scope = ", ".join(x for x in (table, ind, iso, (f"{y0}" if y0 == y1 else f"{y0}-{y1}") if y0 else None) if x)
            lines.append(f"- [{scope}] {note}")
        state.lookups.append((state.turn.index, f"get_data_notes({', '.join(str(v) for v in args.values())})",
                              "\n".join(lines) or "No notes."))
        return ok(f"{len(lines)} notes", "\n".join(lines) or "No notes.")

    @tool("run_sql", "Run one read-only SQLite SELECT against the AHDC database. Returns a query_id, the "
          "columns and up to 200 rows (results are capped at 1000 rows). State the query's purpose in plain "
          "language; it is logged and shown to the user.",
          {"type": "object", "properties": {
              "sql": {"type": "string", "description": "A single SELECT statement (CTEs allowed)."},
              "purpose": {"type": "string", "description": "What this query is for, in a few words."}},
           "required": ["sql", "purpose"]}, annotations=READ_ONLY)
    async def run_sql(args: dict[str, Any]) -> dict[str, Any]:
        sql, purpose = args["sql"].strip(), args.get("purpose", "").strip()
        guard = check_sql(sql)  # the PreToolUse hook already checked; checked again here as defense in depth
        if not guard.ok:
            return err(f"Query rejected: {guard.reason}")
        try:
            res = db.run_query(sql)
        except sqlite3.Error as e:
            return err(f"SQLite error: {e}")
        qid = state.next_query_id()
        rec = QueryRecord(qid, state.turn.index, sql, purpose, guard.tables, res.columns, res.rows,
                          res.truncated, res.duration_ms)
        state.queries[qid] = rec
        state.turn.query_ids.append(qid)
        n = rec.row_count
        summary = f"{n:,} row{'s' if n != 1 else ''}{'+ (capped)' if res.truncated else ''} · {res.duration_ms} ms"
        if n == 1 and len(res.columns) <= 6:
            summary += " · " + " · ".join(f"{c}={fmt_value(v)}" for c, v in zip(res.columns, res.rows[0]))
        return ok(summary, f"query_id: {qid}\n{table_text(res.columns, res.rows)}")

    @tool("get_draft", "Methods reviewer only: the question, the current draft answer, and the queries the analyst "
          "actually ran this turn, with their results.", {}, annotations=READ_ONLY)
    async def get_draft(args: dict[str, Any]) -> dict[str, Any]:
        turn = state.turn
        if not turn.answer:
            return err("No draft has been submitted yet.")
        a = turn.answer
        parts = [f"Question: {turn.question}", f"Headline: {a['headline']}",
                 "Confidence factors:\n" + "\n".join(f"  {f['check']} {f['sign']} {f['text']}" for f in a["confidence"]["factors"]),
                 "Caveats:\n" + "\n".join(f"  - {x}" for x in a["caveats"]),
                 "Assumptions:\n" + "\n".join(f"  - {x}" for x in a["assumptions"]),
                 "Method:\n" + "\n".join(f"  {i}. {x}" for i, x in enumerate(a["method"], 1))]
        parts.append("Lookups in this conversation (region definitions and data notes):\n" + "\n".join(
            f"  [turn {t}] {label}: {text}" for t, label, text in state.lookups) if state.lookups else "Lookups: none")
        earlier = [q for q in state.queries.values() if q.turn < turn.index]
        if earlier:
            parts.append("Queries from earlier turns (facts established there may be reused):\n" + "\n".join(
                f"  {q.id} (turn {q.turn}): {q.purpose} · {q.row_count} rows" for q in earlier))
        for qid in turn.query_ids:
            q = state.queries[qid]
            parts.append(f"Query {qid}: {q.purpose}\nSQL:\n{q.sql}\nResult ({q.row_count} rows):\n"
                         f"{table_text(q.columns, q.rows, limit=30)}")
        return ok(f"draft · {len(turn.query_ids)} queries", "\n\n".join(parts))

    @tool("recheck_sql", "Methods reviewer only: run one read-only SELECT to independently recompute a number. "
          "Not recorded as part of the answer's sources. Returns up to 50 rows.",
          {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}, annotations=READ_ONLY)
    async def recheck_sql(args: dict[str, Any]) -> dict[str, Any]:
        guard = check_sql(args["sql"])
        if not guard.ok:
            return err(f"Query rejected: {guard.reason}")
        try:
            res = db.run_query(args["sql"].strip(), max_rows=50)
        except sqlite3.Error as e:
            return err(f"SQLite error: {e}")
        n = len(res.rows)
        summary = f"{n} row{'s' if n != 1 else ''}"
        if n == 1 and len(res.columns) <= 6:
            summary += " · " + " · ".join(f"{c}={fmt_value(v)}" for c, v in zip(res.columns, res.rows[0]))
        return ok(summary, table_text(res.columns, res.rows))

    @tool("render_chart", "Attach a chart to the answer, plotted from the rows a previous run_sql call "
          "returned (by query_id), so plotted values always come from the database. Use a line chart for "
          "trends over years and a bar chart to compare categories. One chart per answer; calling again "
          "replaces it.",
          {"type": "object", "properties": {
              "query_id": {"type": "string"},
              "type": {"type": "string", "enum": ["line", "bar"]},
              "x": {"type": "string", "description": "Column for the x axis (years) or the bar categories."},
              "y": {"type": "string", "description": "Numeric column to plot."},
              "series": {"type": "string", "description": "Optional column that splits rows into series (line only, at most 4)."},
              "title": {"type": "string", "description": "Caption, e.g. 'malaria deaths per 100k · Sub-Saharan Africa'."},
              "unit": {"type": "string"}},
           "required": ["query_id", "type", "x", "y", "title"]})
    async def render_chart(args: dict[str, Any]) -> dict[str, Any]:
        rec = state.queries.get(args["query_id"])
        if rec is None:
            return err(f"Unknown query_id '{args['query_id']}'. Known: {', '.join(state.queries) or 'none'}")
        cols = {c.lower(): i for i, c in enumerate(rec.columns)}
        for key in ("x", "y", "series"):
            if args.get(key) and args[key].lower() not in cols:
                return err(f"Column '{args[key]}' is not in {args['query_id']} (columns: {', '.join(rec.columns)})")
        xi, yi = cols[args["x"].lower()], cols[args["y"].lower()]
        si = cols[args["series"].lower()] if args.get("series") else None
        groups: dict[str, list] = {}
        for r in rec.rows:
            if r[yi] is None:
                continue
            groups.setdefault(str(r[si]) if si is not None else args["y"], []).append([r[xi], r[yi]])
        if args["type"] == "line" and len(groups) > 4:
            return err(f"{len(groups)} series is too many for a readable line chart; filter to at most 4.")
        if args["type"] == "bar" and sum(len(v) for v in groups.values()) > 25:
            return err("Too many bars (max 25); show the top categories instead.")
        state.turn.chart = {"type": args["type"], "title": args["title"], "unit": args.get("unit", ""),
                            "x": args["x"], "y": args["y"], "query_id": rec.id,
                            "series": [{"name": k, "points": v} for k, v in groups.items()]}
        n_series = len(groups)
        return ok(f"1 chart · {args['type']}{f', {n_series} series' if n_series > 1 else ''}")

    @tool("submit_answer", "Submit the final answer for this turn. Call exactly once, as the last step, "
          "after all queries. The UI shows: the headline; a confidence meter computed from your factors "
          "(5 minus the number of '-' factors); then collapsible Confidence, Caveats, Assumptions and Method "
          "rows. SQL and source tables are added automatically from the queries you ran. Follow the "
          "answer standards in the ahdc-analysis-standards skill.",
          {"type": "object", "properties": {
              "headline": {"type": "string", "description": "The answer in one plain sentence with the key number(s) and unit; region names spelled out (no abbreviations like SSA); no trailing period; under 90 characters."},
              "confidence_factors": {"type": "array", "minItems": 4, "maxItems": 4,
                  "description": "Exactly one factor per check: completeness, finality, definition, consistency (see the skill's confidence checklist).",
                  "items": {"type": "object", "properties": {
                      "check": {"type": "string", "enum": list(CHECKS)},
                      "sign": {"type": "string", "enum": ["+", "-"]},
                      "text": {"type": "string", "description": "One short sentence with the specifics."}},
                  "required": ["check", "sign", "text"]}},
              "caveats": {"type": "array", "items": {"type": "string"}},
              "assumptions": {"type": "array", "items": {"type": "string"}},
              "method": {"type": "array", "minItems": 1, "items": {"type": "string"}, "description": "Plain-language steps, without numbers (the UI numbers them)."},
              "primary_query_id": {"type": "string", "description": "The query_id whose result gives the headline number (shown first in the SQL section)."}},
           "required": ["headline", "confidence_factors", "caveats", "assumptions", "method"]})
    async def submit_answer(args: dict[str, Any]) -> dict[str, Any]:
        headline = " ".join(args["headline"].split()).rstrip(".")
        problems = []
        if len(headline) > 110:
            problems.append(f"headline is {len(headline)} characters; keep it under 90")
        if not args.get("method"):
            problems.append("method needs at least one step")
        checks = [f.get("check") for f in args["confidence_factors"]]
        if sorted(checks) != sorted(CHECKS):
            problems.append(f"confidence_factors must cover each check exactly once ({', '.join(CHECKS)}); got {checks}")
        if problems:
            return err("Answer not accepted: " + "; ".join(problems) + ". Fix and call submit_answer again.")
        if state.turn.review:
            state.turn.revised = True
        conf = confidence(sorted(args["confidence_factors"], key=lambda f: CHECKS.index(f["check"])))
        unnumber = lambda items: [re.sub(r"^\s*(\d+[.)]|[-•*])\s*", "", x).strip() for x in items]
        state.turn.answer = {"headline": headline, "confidence": conf, "caveats": unnumber(args["caveats"]),
                             "assumptions": unnumber(args["assumptions"]), "method": unnumber(args["method"]),
                             "primary_query_id": args.get("primary_query_id")}
        nxt = ("Draft saved. Now call the methods-reviewer subagent." if review and not state.turn.review
               else "Accepted. Now reply with the headline only, nothing else.")
        return ok(f"answer submitted · confidence {conf['level']} {conf['score']}/5", nxt)

    return [list_tables, describe_table, get_region_members, get_data_notes, run_sql, get_draft, recheck_sql,
            render_chart, submit_answer]
