"""Offline tests for the eval grader and the golden set (no API calls)."""

from pathlib import Path

import pytest
import yaml

from evals.grading import expected_values, grade, numbers

GOLDEN = yaml.safe_load((Path(__file__).resolve().parents[1] / "evals" / "golden.yaml").read_text())["items"]


def test_numbers_parsing():
    assert numbers("52.1 per 100,000 (95% UI 38.4–69.0)") == [52.1, 100000, 95, 38.4, 69.0]
    assert numbers("about 1.2 million deaths, or 680k") == [1.2e6, 680e3]
    assert numbers("fell by −7.9 points to $6,161") == [-7.9, 6161]


def answer(headline, **kw):
    return {"headline": headline, "caveats": kw.get("caveats", []), "assumptions": kw.get("assumptions", []),
            "method": kw.get("method", []), "confidence": {"factors": kw.get("factors", [])}}


def test_grade_number_mentions_absent():
    checks = [{"number": {"where": "headline", "value": 52.1, "tol": 0.05}},
              {"mentions": {"pattern": "World Bank"}},
              {"absent": {"where": "headline", "pattern": "40\\.6"}}]
    good = answer("Malaria killed 52.1 per 100,000", assumptions=['"SSA" = World Bank region'])
    assert all(r["ok"] for r in grade(good, checks))
    bad = answer("Malaria killed 40.6 per 100,000")
    assert [r["ok"] for r in grade(bad, checks)] == [False, False, False]
    assert not grade(None, checks)[0]["ok"]


def test_no_value_in_headline_ignores_years():
    chk = [{"no_value_in_headline": True}]
    assert grade(answer("Dengue is not in the AHDC data for 2024"), chk)[0]["ok"]
    assert not grade(answer("Dengue killed 3.1 per 100,000 in 2024"), chk)[0]["ok"]


@pytest.mark.parametrize("item", GOLDEN, ids=[i["id"] for i in GOLDEN])
def test_golden_items_are_well_formed(item):
    assert item["turns"] and item["checks"]
    for chk in item["checks"]:
        kind, spec = next(iter(chk.items()))
        assert kind in {"number", "mentions", "absent", "no_value_in_headline"}
        if kind == "number":
            vals = expected_values(spec)  # every ground-truth SQL must run and return a number
            assert vals and all(v == v for v in vals)


def test_expected_demo_values():
    item = next(i for i in GOLDEN if i["id"] == "malaria_ssa_2025")
    assert expected_values(item["checks"][0]["number"]) == [52.1]
