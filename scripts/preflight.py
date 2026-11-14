"""Demo-day preflight: checks everything the live demo depends on and says how to fix what's wrong.

  uv run python scripts/preflight.py          # offline checks (free, ~5 s)
  uv run python scripts/preflight.py --live   # also runs one real question through the agent (~$0.05, ~20 s)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GREEN, RED, YELLOW, GREY, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"
failures = 0


def report(ok: bool | None, name: str, detail: str = "", fix: str = "") -> None:
    global failures
    mark = f"{GREEN}✓{RESET}" if ok else (f"{YELLOW}!{RESET}" if ok is None else f"{RED}✗{RESET}")
    print(f"  {mark} {name}{f'  {GREY}{detail}{RESET}' if detail else ''}")
    if ok is False:
        failures += 1
        if fix:
            print(f"      {GREY}fix: {fix}{RESET}")


def check_env() -> None:
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / ".env").get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    report(key.startswith("sk-ant-"), "API key present", "ANTHROPIC_API_KEY in .env" if key else "",
           "add ANTHROPIC_API_KEY=sk-ant-... to ahdc-explorer/.env")
    import claude_agent_sdk
    report(True, "claude-agent-sdk installed", claude_agent_sdk.__version__)


def check_data() -> None:
    db = ROOT / "data" / "ahdc.db"
    report(db.exists(), "database built", str(db.relative_to(ROOT)), "uv run python data/generate.py")
    skill = ROOT / ".claude" / "skills" / "ahdc-analysis-standards" / "SKILL.md"
    report(skill.exists() and "name: ahdc-analysis-standards" in skill.read_text(), "analysis-standards skill present")
    replay = ROOT / "web" / "replays" / "demo.json"
    try:
        turns = json.loads(replay.read_text())["turns"]
        report(len(turns) == 4, "offline replay ready", f"{len(turns)} turns · /?replay=demo",
               "uv run python scripts/record_replay.py demo")
    except Exception as e:
        report(False, "offline replay ready", str(e), "uv run python scripts/record_replay.py demo")
    t0 = time.monotonic()
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"], cwd=ROOT, capture_output=True, text=True)
    last = (res.stdout.strip().splitlines() or ["no output"])[-1]
    report(res.returncode == 0, "offline tests (data traps, tools, hooks, grader)", f"{last} · {time.monotonic() - t0:.1f}s",
           "uv run pytest -q   (and read the failure)")


def check_network() -> None:
    for name, url in [("Anthropic API reachable", "https://api.anthropic.com"),
                      ("Google Fonts reachable (JetBrains Mono)", "https://fonts.googleapis.com/css2?family=JetBrains+Mono")]:
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=5)
            report(True, name)
        except urllib.error.HTTPError:  # any HTTP answer means the host is reachable
            report(True, name)
        except Exception as e:
            fallback = "the UI falls back to Menlo" if "Fonts" in name else "use the replay fallback: /?replay=demo"
            report(None if "Fonts" in name else False, name, type(e).__name__, fallback)


def check_server(port: int = 8000) -> None:
    try:
        code = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).status
        report(code == 200, f"web server running on :{port}", "http://127.0.0.1:%d" % port)
    except Exception:
        with socket.socket() as s:
            free = s.connect_ex(("127.0.0.1", port)) != 0
        report(None, f"web server not running on :{port}", "port is free" if free else "port busy with something else",
               "./run.sh")


async def live_check() -> None:
    from ahdc_agent.agent import MODEL, REVIEW, REVIEWER_MODEL, AgentSession
    q = "How many countries are in the World Bank South Asia region?"
    t0 = time.monotonic()
    answer, stats, err = None, {}, None
    try:
        async with AgentSession() as s:
            async for ev in s.ask(q):
                if ev["type"] == "answer":
                    answer = ev
                elif ev["type"] == "error":
                    err = ev["message"]
                elif ev["type"] == "done":
                    stats = ev["stats"]
            info = s.init_info
    except Exception as e:
        err, info = f"{type(e).__name__}: {e}", {}
    ok = bool(answer) and "8" in answer["headline"]
    report(ok, "live agent run", f"{(answer or {}).get('headline', err)!r} · {time.monotonic() - t0:.0f}s · "
           f"${stats.get('cost_usd') or 0:.3f}", "check the key, credits and network; else use /?replay=demo")
    if info:
        report(info.get("apiKeySource") == "ANTHROPIC_API_KEY", "authenticated with the API key", info.get("apiKeySource", ""))
        report(info.get("model") == MODEL, "main model", info.get("model", ""))
    if answer:
        review = answer.get("reviewed")
        report(bool(review) if REVIEW else None, "methods-reviewer subagent ran", f"{REVIEWER_MODEL}: {review}")


def main() -> None:
    live = "--live" in sys.argv
    print("\nAHDC Data Explorer · preflight\n")
    check_env()
    check_data()
    check_network()
    check_server()
    if live:
        asyncio.run(live_check())
    else:
        print(f"  {GREY}(add --live to run one real question through the agent){RESET}")
    print(f"\n{GREEN + 'All clear.' if not failures else RED + f'{failures} problem(s) to fix.'}{RESET}\n")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
