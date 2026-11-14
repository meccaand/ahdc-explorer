"""Offline tests for the custom tools, SQL guard and hooks (no API calls)."""

import asyncio
import json

import pytest

from ahdc_agent import hooks
from ahdc_agent.sql_guard import check_sql, filter_values
from ahdc_agent.state import SessionState, confidence
from ahdc_agent.tools import build_tools


def call(tools, name, args):
    return asyncio.run(tools[name].handler(args))


def text(res):
    return res["content"][0]["text"]


@pytest.fixture
def env():
    state = SessionState()
    state.begin_turn("test question")
    return state, {t.name: t for t in build_tools(state)}


@pytest.mark.parametrize("sql", ["DELETE FROM disease_burden", "SELECT 1; SELECT 2", "SELECT * FROM sqlite_master",
                                 "UPDATE countries SET name = 'x'", "DROP TABLE countries"])
def test_guard_denies(sql):
    assert not check_sql(sql).ok


def test_guard_allows_cte_and_reports_tables():
    r = check_sql("WITH s AS (SELECT iso3 FROM countries WHERE wb_region = 'South Asia') "
                  "SELECT * FROM demographics JOIN s USING (iso3)")
    assert r.ok and r.tables == ["countries", "demographics"]


def test_filter_values_by_table():
    f = filter_values("SELECT * FROM intervention_coverage WHERE intervention IN ('DTP3','MCV1') AND source = 'modeled'")
    assert f == {"intervention_coverage": ["DTP3", "MCV1", "modeled"]}


def test_run_sql_records_provenance(env):
    state, tools = env
    res = call(tools, "run_sql", {"sql": "SELECT COUNT(*) AS n FROM countries", "purpose": "count countries"})
    assert text(res).startswith("1 row") and "n=179" in text(res)
    q = state.queries["q1"]
    assert q.purpose == "count countries" and q.tables == ["countries"] and state.turn.query_ids == ["q1"]


def test_run_sql_rejects_write(env):
    state, tools = env
    res = call(tools, "run_sql", {"sql": "DELETE FROM countries", "purpose": "x"})
    assert res.get("is_error") and not state.queries


def test_render_chart_uses_query_rows(env):
    state, tools = env
    call(tools, "run_sql", {"sql": "SELECT year, coverage_pct FROM intervention_coverage WHERE iso3 = 'IND' "
                                   "AND intervention = 'DTP3' AND source = 'modeled' ORDER BY year", "purpose": "p"})
    assert call(tools, "render_chart", {"query_id": "q1", "type": "line", "x": "year", "y": "nope", "title": "t"}).get("is_error")
    call(tools, "render_chart", {"query_id": "q1", "type": "line", "x": "year", "y": "coverage_pct", "title": "t"})
    pts = dict(state.turn.chart["series"][0]["points"])
    assert pts[2021] == 85 and pts[2025] == 93


FACTORS = [{"check": "completeness", "sign": "-", "text": "a"}, {"check": "finality", "sign": "-", "text": "b"},
           {"check": "definition", "sign": "+", "text": "c"}, {"check": "consistency", "sign": "+", "text": "d"}]


def test_submit_answer_validates_and_scores(env):
    state, tools = env
    base = {"headline": "X is 1.", "caveats": ["1. c"], "assumptions": [], "method": ["1. step one", "2) step two"]}
    assert call(tools, "submit_answer", {**base, "confidence_factors": FACTORS[:3]}).get("is_error")
    res = call(tools, "submit_answer", {**base, "confidence_factors": list(reversed(FACTORS))})
    assert "Medium 3/5" in text(res)
    a = state.turn.answer
    assert a["headline"] == "X is 1" and a["method"] == ["step one", "step two"] and a["caveats"] == ["c"]
    assert [f["check"] for f in a["confidence"]["factors"]] == ["completeness", "finality", "definition", "consistency"]


def test_confidence_levels():
    signs = lambda s: [{"sign": x} for x in s]
    assert confidence(signs("++++"))["score"] == 5 and confidence(signs("++++"))["level"] == "High"
    assert confidence(signs("+++-"))["level"] == "High"
    assert confidence(signs("++--"))["level"] == "Medium"
    assert confidence(signs("----"))["score"] == 1 and confidence(signs("----"))["level"] == "Low"


def test_sql_guard_hook_denies_and_audits(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "AUDIT_LOG", tmp_path / "audit.jsonl")
    out = asyncio.run(hooks.sql_guard_hook({"tool_name": "mcp__ahdc__run_sql", "session_id": "s",
                                            "tool_input": {"sql": "DELETE FROM countries", "purpose": "p"}}, "t1", {}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert json.loads((tmp_path / "audit.jsonl").read_text())["event"] == "denied"
    ok = asyncio.run(hooks.sql_guard_hook({"tool_input": {"sql": "SELECT 1 FROM countries"}}, "t2", {}))
    assert ok == {}


def test_get_draft_shows_real_queries_and_lookups():
    state = SessionState()
    state.begin_turn("q")
    tools = {t.name: t for t in build_tools(state, review=True)}
    assert call(tools, "get_draft", {}).get("is_error")  # nothing submitted yet
    call(tools, "get_region_members", {"scheme": "wb_region", "region": "South Asia"})
    call(tools, "run_sql", {"sql": "SELECT COUNT(*) AS n FROM countries WHERE wb_region = 'South Asia'", "purpose": "count"})
    res = call(tools, "submit_answer", {"headline": "8 countries", "caveats": [], "assumptions": [], "method": ["m"],
                                        "confidence_factors": FACTORS})
    assert "methods-reviewer" in text(res)            # review mode asks for the review next
    draft = text(call(tools, "get_draft", {}))
    assert "SELECT COUNT(*) AS n FROM countries" in draft and "South Asia" in draft and "8 countries" in draft


def test_resubmit_after_review_marks_revised():
    state = SessionState()
    state.begin_turn("q")
    tools = {t.name: t for t in build_tools(state, review=True)}
    args = {"headline": "h", "caveats": [], "assumptions": [], "method": ["m"], "confidence_factors": FACTORS}
    call(tools, "submit_answer", args)
    state.turn.review = "ISSUES — 1/6 checks failed"
    res = call(tools, "submit_answer", {**args, "headline": "h2"})
    assert state.turn.revised and state.turn.answer["headline"] == "h2" and "headline only" in text(res)


def test_recheck_sql_is_not_recorded_as_a_source():
    state = SessionState()
    state.begin_turn("q")
    tools = {t.name: t for t in build_tools(state, review=True)}
    assert "n=179" in text(call(tools, "recheck_sql", {"sql": "SELECT COUNT(*) AS n FROM countries"}))
    assert not state.queries and not state.turn.query_ids
    assert call(tools, "recheck_sql", {"sql": "DELETE FROM countries"}).get("is_error")
