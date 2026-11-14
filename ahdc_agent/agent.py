"""The AHDC agent: Claude Agent SDK options, and a session wrapper that turns the SDK message stream into simple
UI events (steps, answer, stats) for the CLI and the web server.

The SDK provides the agent loop, tool execution, hooks, skills, sessions and context management; this module only
configures it and translates its messages.
"""

from __future__ import annotations

import dataclasses
import os
import time
from typing import Any, AsyncIterator

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, SystemMessage,
                              TextBlock, ToolResultBlock, ToolUseBlock, UserMessage)
from dotenv import load_dotenv

from . import db
from .hooks import build_hooks
from .prompts import SYSTEM_PROMPT
from .sql_guard import filter_values
from .state import SessionState
from .tools import SERVER, build_server

load_dotenv(db.ROOT / ".env")

MODEL = os.getenv("AHDC_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("AHDC_EFFORT", "medium")
SKILL = "ahdc-analysis-standards"
PREFIX = f"mcp__{SERVER}__"


def build_options(state: SessionState) -> ClaudeAgentOptions:
    server, tool_names = build_server(state)
    return ClaudeAgentOptions(
        model=MODEL,
        effort=EFFORT,
        system_prompt=SYSTEM_PROMPT,
        # Tools: our in-process MCP server, plus the built-in Skill tool. No Bash, files or web.
        mcp_servers={SERVER: server},
        strict_mcp_config=True,
        tools=["Skill"],
        allowed_tools=[*tool_names, "Skill"],
        permission_mode="dontAsk",          # anything not allowed is denied, never prompted
        hooks=build_hooks(),
        # Load only this repo's .claude/ (the skill), never the developer's personal ~/.claude settings or memory.
        setting_sources=["project"],
        skills=[SKILL],
        cwd=str(db.ROOT),
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
        max_turns=40,
        max_budget_usd=float(os.getenv("AHDC_MAX_BUDGET_USD", "5")),
        stderr=_log_stderr,
    )


def _log_stderr(line: str) -> None:
    """Keep the Claude Code subprocess's stderr out of the terminal UI; it goes to logs/claude-stderr.log."""
    path = db.ROOT / "logs" / "claude-stderr.log"
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


# --- turning SDK messages into UI events -----------------------------------------------------------------------
def short_tool(name: str) -> str:
    if name.startswith(PREFIX):
        return name[len(PREFIX):]
    return {"Skill": "skill", "Agent": "methods_review", "Task": "methods_review"}.get(name, name)


def tool_args(name: str, inp: dict[str, Any]) -> str:
    n = short_tool(name)
    if n == "run_sql":
        return f'("{inp.get("purpose", "")}")'
    if n == "skill":
        return f"({inp.get('skill', inp.get('command', ''))})"
    if n == "describe_table":
        return f"({inp.get('table', '')})"
    if n == "get_region_members":
        return "(" + ", ".join(str(inp[k]) if k != "region" else f'"{inp[k]}"'
                               for k in ("scheme", "region", "as_of_year") if inp.get(k)) + ")"
    if n == "get_data_notes":
        return "(" + ", ".join(str(inp[k]) for k in ("table", "indicator", "iso3", "year") if inp.get(k)) + ")"
    if n == "render_chart":
        return f"({inp.get('type', '')}, {inp.get('query_id', '')})"
    if n in ("list_tables", "submit_answer"):
        return ""
    return "(" + ", ".join(f"{k}={v}" for k, v in list(inp.items())[:3]) + ")"


def result_text(block: ToolResultBlock) -> str:
    c = block.content
    if isinstance(c, list):
        return "\n".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return str(c or "")


def jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {"_type": type(obj).__name__, **{k: jsonable(v) for k, v in dataclasses.asdict(obj).items()}}
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def tokens_in(usage: dict[str, Any] | None) -> int:
    u = usage or {}
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


class AgentSession:
    """One conversation: one ClaudeSDKClient (one Claude Code subprocess) plus our session state."""

    def __init__(self) -> None:
        self.state = SessionState()
        self.client = ClaudeSDKClient(build_options(self.state))
        self.session_id: str | None = None
        self.init_info: dict[str, Any] = {}
        self._cost_so_far = 0.0  # ResultMessage.total_cost_usd is cumulative for the session

    async def __aenter__(self) -> "AgentSession":
        await self.client.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.client.disconnect()

    async def ask(self, question: str) -> AsyncIterator[dict[str, Any]]:
        turn = self.state.begin_turn(question)
        t0 = time.monotonic()
        steps: dict[str, dict[str, Any]] = {}
        n_steps = n_tools = 0
        seen_tool = answered = False
        result: ResultMessage | None = None

        await self.client.query(question)
        async for msg in self.client.receive_response():
            turn.raw_messages.append(jsonable(msg))
            if isinstance(msg, SystemMessage):
                if msg.subtype == "init":
                    self.session_id = msg.data.get("session_id", self.session_id)
                    self.init_info = msg.data
                continue
            if isinstance(msg, AssistantMessage):
                sub = msg.parent_tool_use_id is not None
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip() and not sub:
                        if not seen_tool and n_steps == 0:
                            n_steps += 1
                            yield {"type": "step", "id": "plan", "tool": "plan", "args": "",
                                   "status": "done", "out": " ".join(block.text.split())[:160]}
                        elif not answered:
                            yield {"type": "note", "text": block.text.strip()}
                    elif isinstance(block, ToolUseBlock) and not sub:
                        seen_tool = True
                        n_steps += 1
                        n_tools += 1
                        step = {"type": "step", "id": block.id, "tool": short_tool(block.name),
                                "args": tool_args(block.name, block.input), "status": "running", "out": ""}
                        steps[block.id] = step
                        yield dict(step)
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, ToolResultBlock) and block.tool_use_id in steps:
                        step = steps[block.tool_use_id]
                        text = result_text(block)
                        step.update(status="error" if block.is_error else "done", out=text.split("\n", 1)[0][:200])
                        if step["tool"] == "submit_answer" and not block.is_error:
                            answered = True
                        yield dict(step)
            elif isinstance(msg, ResultMessage):
                result = msg

        if turn.answer:
            yield {"type": "answer", "turn": turn.index, **self.assemble_answer()}
        else:
            reason = (result.errors or [result.subtype]) if result else ["no result"]
            yield {"type": "error", "turn": turn.index,
                   "message": f"The agent stopped without submitting an answer ({'; '.join(map(str, reason))})."}

        ctx = None
        try:
            ctx = (await self.client.get_context_usage()).get("totalTokens")
        except Exception:
            pass
        yield {"type": "done", "turn": turn.index, "stats": {
            "steps": n_steps, "tool_calls": n_tools,
            "seconds": round((result.duration_ms if result else (time.monotonic() - t0) * 1000) / 1000, 1),
            "tokens_in": tokens_in(result.usage if result else None),
            "tokens_out": int((result.usage or {}).get("output_tokens") or 0) if result else 0,
            "cost_usd": self._turn_cost(result),
            "num_turns": result.num_turns if result else None,
            "ctx_tokens": ctx, "session_id": self.session_id}}

    def _turn_cost(self, result: ResultMessage | None) -> float | None:
        if not result or result.total_cost_usd is None:
            return None
        cost = max(0.0, result.total_cost_usd - self._cost_so_far)
        self._cost_so_far = result.total_cost_usd
        return round(cost, 4)

    def assemble_answer(self) -> dict[str, Any]:
        """The answer card: the model's submit_answer content plus provenance taken from the queries actually run."""
        turn = self.state.turn
        queries = [self.state.queries[q] for q in turn.query_ids]
        dd = db.dictionary()["tables"]
        sources: dict[str, dict[str, Any]] = {}
        for q in queries:
            filters = filter_values(q.sql)
            for t in q.tables:
                s = sources.setdefault(t, {"table": t, "label": dd[t].get("label", ""), "filters": [], "rows": 0})
                s["rows"] += q.row_count
                s["filters"] += [f for f in filters.get(t, []) if f not in s["filters"]]
        return {**turn.answer,
                "sql": [{"id": q.id, "purpose": q.purpose, "sql": q.sql, "rows": q.row_count} for q in queries],
                "sources": list(sources.values()),
                "chart": turn.chart}
