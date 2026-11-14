"""SDK hooks: a PreToolUse SQL guard and a PostToolUse audit log.

Hooks run in this process for every matching tool call, whatever the model decides; they are how the data team
enforces policy without relying on the prompt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookContext, HookMatcher

from .db import ROOT
from .sql_guard import check_sql
from .tools import full_name

AUDIT_LOG = ROOT / "logs" / "audit.jsonl"


def _audit(record: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _first_line(tool_response: Any) -> str:
    """Pull the one-line summary out of an MCP tool response, whatever its exact shape."""
    try:
        content = tool_response.get("content") if isinstance(tool_response, dict) else tool_response
        if isinstance(content, list) and content and isinstance(content[0], dict):
            return str(content[0].get("text", "")).split("\n", 1)[0]
        return str(content).split("\n", 1)[0][:200]
    except Exception:  # never let auditing break a turn
        return ""


async def sql_guard_hook(input_data: dict[str, Any], tool_use_id: str | None, context: HookContext) -> dict[str, Any]:
    sql = (input_data.get("tool_input") or {}).get("sql", "")
    result = check_sql(sql)
    if result.ok:
        return {}
    _audit({"event": "denied", "session_id": input_data.get("session_id"), "tool": input_data.get("tool_name"),
            "sql": sql, "purpose": (input_data.get("tool_input") or {}).get("purpose"), "reason": result.reason})
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Blocked by the AHDC SQL guard: {result.reason}",
    }}


async def audit_hook(input_data: dict[str, Any], tool_use_id: str | None, context: HookContext) -> dict[str, Any]:
    tool_input = input_data.get("tool_input") or {}
    _audit({"event": "tool_call", "session_id": input_data.get("session_id"), "tool": input_data.get("tool_name"),
            "tool_use_id": tool_use_id, "input": tool_input, "summary": _first_line(input_data.get("tool_response")),
            "duration_ms": input_data.get("duration_ms"), "subagent": input_data.get("agent_id")})
    return {}


def build_hooks() -> dict[str, list[HookMatcher]]:
    return {
        "PreToolUse": [HookMatcher(matcher=full_name("run_sql"), hooks=[sql_guard_hook])],
        "PostToolUse": [HookMatcher(matcher="mcp__ahdc__.*", hooks=[audit_hook])],
    }
