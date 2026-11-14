"""Deterministic grading of agent answers against evals/golden.yaml (no model-graded checks)."""

from __future__ import annotations

import re
from typing import Any

from ahdc_agent import db

NUM = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|thousand|million|m|billion|bn)\b)?", re.I)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "billion": 1e9, "bn": 1e9}


def numbers(text: str) -> list[float]:
    """Every number in the text; handles 1,234 · 52.1 · −7.9 · 93% · 1.2 million · 680k."""
    out = []
    for m in NUM.finditer(text):
        tok = m.group(0).replace("−", "-").replace(",", "")
        mult = 1.0
        unit = re.search(r"[a-z]+$", tok, re.I)
        if unit:
            mult = SCALE[unit.group(0).lower()]
            tok = tok[: unit.start()].strip()
        try:
            out.append(float(tok) * mult)
        except ValueError:
            pass
    return out


def answer_text(answer: dict[str, Any], where: str) -> str:
    if where == "headline":
        return answer["headline"]
    parts = [answer["headline"], *answer["caveats"], *answer["assumptions"], *answer["method"],
             *(f["text"] for f in answer["confidence"]["factors"])]
    return "\n".join(parts)


def expected_values(spec: dict[str, Any]) -> list[float]:
    if "value" in spec:
        return [float(spec["value"])]
    sqls = spec.get("any_of") or [spec["sql"]]
    con = db.connect()
    try:
        return [float(con.execute(s).fetchone()[0]) for s in sqls]
    finally:
        con.close()


def matches(found: float, want: float, spec: dict[str, Any]) -> bool:
    if "rel" in spec:
        return abs(found - want) <= abs(want) * float(spec["rel"])
    return abs(found - want) <= float(spec.get("tol", 0.05))


def grade(answer: dict[str, Any] | None, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One result per check: {check, ok, detail}."""
    results = []
    for chk in checks:
        kind, spec = next(iter(chk.items()))
        label = f"{kind}:{spec.get('pattern', '') if isinstance(spec, dict) else ''}".rstrip(":")
        if answer is None:
            results.append({"check": label, "ok": False, "detail": "no answer"})
            continue
        if kind == "number":
            text = answer_text(answer, spec.get("where", "any"))
            wants = expected_values(spec)
            found = numbers(text)
            ok = any(matches(f, w, spec) for f in found for w in wants)
            label = f"number({spec.get('where', 'any')})"
            detail = f"want {' or '.join(f'{w:g}' for w in wants)}; found {[f'{f:g}' for f in found[:12]]}"
        elif kind in ("mentions", "absent"):
            text = answer_text(answer, spec.get("where", "any"))
            hit = re.search(spec["pattern"], text, re.I) is not None
            ok = hit if kind == "mentions" else not hit
            detail = f"/{spec['pattern']}/ in {spec.get('where', 'any')}: {'found' if hit else 'not found'}"
        elif kind == "no_value_in_headline":
            vals = [v for v in numbers(answer["headline"]) if not (1990 <= v <= 2035 and v == int(v))]
            ok, detail = not vals, f"non-year numbers in headline: {vals}"
        else:
            ok, detail = False, f"unknown check type {kind}"
        results.append({"check": label, "ok": ok, "detail": detail})
    return results
