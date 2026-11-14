"""Terminal client for the AHDC agent (also the demo fallback if the web UI fails).

  uv run python cli.py                      interactive; /new starts a new session, /quit exits
  uv run python cli.py "question" ["follow-up" ...]   run questions in one session, then exit
  options: --json  print raw events · --trace  save each turn's raw SDK messages to logs/
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

from ahdc_agent.agent import AgentSession
from ahdc_agent.db import ROOT

ACCENT, GREEN, GREY, BOLD, RED, RESET = "\033[38;2;217;119;87m", "\033[38;2;127;183;126m", "\033[38;2;155;153;143m", "\033[1m", "\033[31m", "\033[0m"


def wrap(text: str, indent: str) -> str:
    return textwrap.fill(text, 100, initial_indent=indent, subsequent_indent=indent + "  ")


def print_answer(ev: dict) -> None:
    c = ev["confidence"]
    meter = "■" * c["score"] + "□" * (5 - c["score"])
    print(f"\n{BOLD}● {ev['headline']}{RESET}")
    print(f"  {GREY}CONFIDENCE{RESET} {meter} {BOLD}{c['level']} · {c['score']}/5{RESET}")
    if ev.get("chart"):
        ch = ev["chart"]
        print(f"  {GREY}[chart: {ch['type']} · {ch['title']} · {len(ch['series'])} series from {ch['query_id']}]{RESET}")
    sections = [("Confidence", [f"{f['sign']} {f['text']}" for f in c["factors"]]),
                ("Caveats", [f"- {x}" for x in ev["caveats"]]),
                ("Assumptions", [f"- {x}" for x in ev["assumptions"]]),
                ("Method", [f"{i}. {x}" for i, x in enumerate(ev["method"], 1)])]
    for name, items in sections:
        print(f"  {GREY}▸ {name}{RESET}")
        for it in items:
            print(wrap(it, "      "))
    print(f"  {GREY}▸ SQL · {len(ev['sql'])} {'query' if len(ev['sql']) == 1 else 'queries'}{RESET}")
    for q in ev["sql"]:
        print(f"      {GREY}{q['id']} · {q['purpose']} · {q['rows']} row{'' if q['rows'] == 1 else 's'}{RESET}")
    print(f"  {GREY}▸ Source data{RESET}")
    for s in ev["sources"]:
        print(f"      {BOLD}{s['table']}{RESET} {GREY}{s['label']}{' · ' + ', '.join(s['filters']) if s['filters'] else ''} · {s['rows']} rows{RESET}")


async def run_turn(session: AgentSession, question: str, as_json: bool, save_trace: bool) -> None:
    print(f"\n{GREY}>{RESET} {question}")
    async for ev in session.ask(question):
        if as_json:
            print(json.dumps(ev, ensure_ascii=False, default=str))
            continue
        if ev["type"] == "step":
            if ev["status"] == "running":
                if ev["out"] == "running…":  # skip the earlier "writing…" event; print once the input is known
                    print(f"  {GREEN}●{RESET} {BOLD}{ev['tool']}{RESET}{GREY}{ev['args']}{RESET}", flush=True)
            else:
                color = RED if ev["status"] == "error" else GREY
                if ev["tool"] == "plan":
                    print(f"  {GREEN}●{RESET} {BOLD}plan{RESET}")
                print(f"    {color}⎿ {ev['out']}{RESET}", flush=True)
        elif ev["type"] == "answer":
            print_answer(ev)
        elif ev["type"] == "error":
            print(f"\n{RED}● {ev['message']}{RESET}")
        elif ev["type"] == "done":
            s = ev["stats"]
            cost = f"${s['cost_usd']:.3f}" if s["cost_usd"] is not None else "?"
            print(f"\n  {GREY}{s['steps']} steps · {s['tool_calls']} tool calls · {s['seconds']}s · "
                  f"{s['tokens_in'] / 1000:.1f}k in / {s['tokens_out']} out · {cost} · ctx {s['ctx_tokens']}{RESET}")
    if save_trace:
        turn = session.state.turn
        path = ROOT / "logs" / f"trace-{session.session_id}-turn{turn.index}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(turn.raw_messages, indent=1, ensure_ascii=False, default=str))
        print(f"  {GREY}raw trace: {path.relative_to(ROOT)}{RESET}")


async def main(argv: list[str]) -> None:
    as_json, save_trace = "--json" in argv, "--trace" in argv
    questions = [a for a in argv if not a.startswith("--")]
    print(f"{ACCENT}*{RESET} {BOLD}AHDC Data Explorer{RESET} {GREY}v0.1 · synthetic data{RESET}")
    while True:
        async with AgentSession() as session:
            if questions:
                for q in questions:
                    await run_turn(session, q, as_json, save_trace)
                return
            while True:
                try:
                    q = input(f"\n{GREY}>{RESET} ").strip()
                except (EOFError, KeyboardInterrupt):
                    return
                if q in ("/quit", "/exit"):
                    return
                if q == "/new":
                    print(f"{GREY}new session{RESET}")
                    break
                if q:
                    await run_turn(session, q, as_json, save_trace)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
