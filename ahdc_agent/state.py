"""Per-session state shared between the custom tools and the turn runner.

Provenance lives here: every query the agent actually ran is recorded, and the answer card's SQL and Source data
rows are filled from these records, not from anything the model writes about them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryRecord:
    id: str
    turn: int
    sql: str
    purpose: str
    tables: list[str]
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    duration_ms: int

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class TurnState:
    index: int
    question: str
    query_ids: list[str] = field(default_factory=list)
    chart: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None      # validated submit_answer input (the latest draft)
    review: str | None = None                  # methods-reviewer verdict line, e.g. "PASS — 6/6 checks passed"
    revised: bool = False                      # submit_answer was called again after the review
    review_report: str = ""                    # the reviewer's full report (✓/✗ lines)
    raw_messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SessionState:
    queries: dict[str, QueryRecord] = field(default_factory=dict)
    lookups: list[tuple[int, str, str]] = field(default_factory=list)  # (turn, label, text): region/notes lookups
    turns: list[TurnState] = field(default_factory=list)

    @property
    def turn(self) -> TurnState:
        if not self.turns:
            raise RuntimeError("No turn in progress")
        return self.turns[-1]

    def begin_turn(self, question: str) -> TurnState:
        t = TurnState(index=len(self.turns) + 1, question=question)
        self.turns.append(t)
        return t

    def next_query_id(self) -> str:
        return f"q{len(self.queries) + 1}"


def confidence(factors: list[dict[str, str]]) -> dict[str, Any]:
    """Four fixed checks, each '+' or '-'. Score = 5 minus the number of '-' checks (so 5 to 1).
    Level is spelled out, never colour-coded."""
    minus = sum(1 for f in factors if f.get("sign") == "-")
    score = max(1, 5 - minus)
    level = "High" if score >= 4 else "Medium" if score == 3 else "Low"
    return {"level": level, "score": score, "factors": factors}
