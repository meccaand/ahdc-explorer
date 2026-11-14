"""Record a live run of questions (one session) as a replay file for the web UI.

The UI plays it back with /?replay=<name> (add &speed=instant to skip timing). Useful as an offline demo
fallback and for screenshots. Each event keeps its time offset so playback has realistic pacing.

  uv run python scripts/record_replay.py demo "question 1" "question 2" ...
  (with no questions, records the four demo questions)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ahdc_agent.agent import AgentSession  # noqa: E402
from ahdc_agent.db import ROOT  # noqa: E402

DEMO = [
    "What was the malaria mortality rate in Sub-Saharan Africa in 2025?",
    "How does that compare to 2015, and which countries drove the change?",
    "How has child vaccination coverage changed in India over the last decade?",
    "Compare health spending per capita across Southeast Asian countries.",
]


async def main(name: str, questions: list[str]) -> None:
    turns = []
    async with AgentSession() as session:
        for q in questions:
            t0 = time.monotonic()
            events = []
            async for ev in session.ask(q):
                events.append({"t": round(time.monotonic() - t0, 2), **ev})
                if ev["type"] == "answer":
                    print(f"  ● {ev['headline']}  [{ev['confidence']['level']} {ev['confidence']['score']}/5]")
            turns.append({"question": q, "events": events, "raw_trace": session.state.turn.raw_messages})
            print(f"recorded: {q} ({events[-1]['t']}s)")
    out = ROOT / "web" / "replays" / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"recorded": time.strftime("%Y-%m-%d %H:%M"), "turns": turns}, ensure_ascii=False, default=str))
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "demo", sys.argv[2:] or DEMO))
