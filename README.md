# AHDC Data Explorer (prototype)

Natural-language exploration of public-health data, built on the **Claude Agent SDK** (Python).
Prototype for the Anthropic Health Data Collaborative take-home. **All data are synthetic.**

## Setup

```bash
uv sync                          # Python 3.13 + dependencies
uv run python data/generate.py   # builds data/ahdc.db (seeded, deterministic, < 1 s)
uv run pytest                    # checks the dataset and its planted "traps"
cp .env.example .env             # then add ANTHROPIC_API_KEY
```

## Data

`data/ahdc.db` (SQLite, standing in for AHDC's PostgreSQL) has 179 countries from 2000 to 2025:

- `countries`
- `demographics`
- `disease_burden`
- `intervention_coverage`
- `health_expenditure` (to 2023)
- `health_facilities`
- `data_notes`

Definitions, units and caveats are in `data/data_dictionary.yaml`.

The generator deliberately plants realistic analytical pitfalls:
- region definitions that disagree between schemes
- rates that must be population-weighted
- provisional 2025 estimates
- missing country-years
- admin coverage above 100%
- USD vs PPP spending

`tests/test_data_traps.py` documents and checks each one.

## Run the web UI

```bash
uv run uvicorn server.app:app --port 8000      # then open http://127.0.0.1:8000
```

- Type a question and press Enter. On an empty prompt, **Tab** fills the next demo question, and **/new** starts a new session.
- Each turn shows the agent's steps live. The answer has a confidence meter (4-check rubric), a chart, and collapsible Confidence, Caveats, Assumptions, Method, SQL and Source data rows. **raw trace** opens that turn's raw Agent SDK messages.
- **Offline fallback:** `/?replay=demo` replays a recorded run of the four demo questions with no API calls; Tab then Enter plays each turn. Add `&autoplay=1` to play all of them, and `&speed=fast` or `&speed=instant`. To re-record: `uv run python scripts/record_replay.py demo`.

The design spec is in `../design/DESIGN.md` (locked).

## Model and speed

The default is `claude-sonnet-5-5` at effort `medium`; `AHDC_MODEL`, `AHDC_EFFORT` and `AHDC_FAST=1` (fast mode, via the SDK's `settings` opt-in) override it. Turns take about 10–20 s. Each step appears as soon as the model starts writing it (`include_partial_messages`).

## Run the agent (CLI)

```bash
uv run python cli.py                                   # interactive; /new = new session, /quit = exit
uv run python cli.py "question" "follow-up" --trace    # scripted; --trace saves raw SDK messages to logs/
```

## How it uses the Claude Agent SDK

| Piece | SDK feature | File |
|---|---|---|
| Agent loop, sessions, context management | `ClaudeSDKClient` (one per conversation) | `ahdc_agent/agent.py` |
| Database access | Custom tools on an in-process MCP server (`create_sdk_mcp_server`, `@tool`, `readOnlyHint`) | `ahdc_agent/tools.py` |
| Read-only enforcement | `PreToolUse` hook (sqlglot SQL guard) + read-only SQLite connection | `ahdc_agent/hooks.py`, `sql_guard.py`, `db.py` |
| Audit trail | `PostToolUse` hook → `logs/audit.jsonl` | `ahdc_agent/hooks.py` |
| The data team's analysis standards | Agent Skill, loaded on demand | `.claude/skills/ahdc-analysis-standards/SKILL.md` |
| Tool lockdown | `tools=["Skill"]` (no Bash/files/web), `allowed_tools`, `permission_mode="dontAsk"`, `strict_mcp_config` | `ahdc_agent/agent.py` |
| Isolation from the developer's own Claude setup | `setting_sources=["project"]`, auto-memory off | `ahdc_agent/agent.py` |
| Answer contract | `submit_answer` tool; SQL and sources filled from the queries actually run, and the confidence score computed from a fixed 4-check rubric | `ahdc_agent/tools.py`, `state.py` |
| Cost and usage | `ResultMessage` (cost, usage, duration), `get_context_usage()` | `ahdc_agent/agent.py` |
