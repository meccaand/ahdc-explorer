# Demo-day checklist (Mon 2026-11-16)

## The night before
- [ ] `git pull`, then `uv run python scripts/preflight.py --live`. Every line should be ✓ (it costs ~$0.03).
- [ ] Check the API credit balance in the Claude Console (keep at least $5).
- [ ] Run the demo beats once: `uv run python evals/run_evals.py --only demo --repeat 2`. Expect 8/8.
- [ ] Charge the laptop. Have a phone hotspot ready as backup Wi-Fi.

## 60 minutes before
- [ ] Quit Slack, mail, Messages and anything that pops up. Turn on **Do Not Disturb** (Focus).
- [ ] Display: 1440×900 or 1920×1080. Browser zoom 100% (110% if the room's screen is small).
- [ ] `./run.sh` (it starts the server and opens http://127.0.0.1:8000).
- [ ] `uv run python scripts/preflight.py`. All ✓, including "web server running".
- [ ] **Warm-up:** ask one throwaway question in the app (e.g. "How many countries are in South Asia?") to warm the prompt cache, then type `/new` for a clean session.

## Tabs and windows, in this order
1. **App:** http://127.0.0.1:8000 (fresh session, empty prompt, cursor in the input)
2. **Fallback:** http://127.0.0.1:8000/?replay=demo (loaded, untouched)
3. **Editor:** `ahdc_agent/agent.py` at `build_options` (line ~54), plus `.claude/skills/ahdc-analysis-standards/SKILL.md`
4. **Evals:** `evals/RESULTS.md` (rendered)
5. **Slides**

## The demo (about 9 minutes)
On an empty prompt, **Tab** fills the next demo question and **Enter** sends it, so there's no typing on stage.

1. **Malaria, Sub-Saharan Africa 2025** (~20 s to the answer). Narrate the steps as they stream:
   - The skill loads (the data team's rules).
   - It resolves *two* region definitions (World Bank and WHO).
   - It reads the data notes, then writes a population-weighted query.
   - *Point:* 52.1 per 100,000. A naive average of country rates gives 40.6; the skill encodes the house standard. Medium 3/5: provisional, and 2 countries missing.
   - Open **Confidence**, **Assumptions** and **SQL**.
2. **Follow-up: compared with 2015, which countries drove it?** Session memory: same region and same 46 countries.
   - The `methods_review` step: *a second model independently recomputes the number.*
   - If it flags something ("drove most" → "drove 28%"), that's the best moment of the demo. Show the revised answer and the review line in **Method**.
3. **India vaccination, last decade.** It picks DTP3, shows the 2020–21 COVID dip, and uses modeled estimates because India's admin figures exceed 100% (**Caveats**).
4. **Southeast Asia spending.** It uses ASEAN *as of 2023* (Timor-Leste joined in 2025), reports PPP and USD, and says why: a 24× gap vs a 75× gap.
5. **For the Director:** click **raw trace** (the real SDK messages: `AssistantMessage`, `ToolUseBlock`, `ResultMessage`, the subagent's own turns). Then go to the editor, `build_options` (~30 lines): model, tools, hooks, skill, subagent, permissions.

## If something goes wrong
| Symptom | Do this |
|---|---|
| A turn errors, or takes over 60 s | "Let me switch to a recorded run of the same questions." Go to tab 2 and press Tab, Enter for each question. It plays the real recorded steps at real speed. |
| No network | Tab 2 works offline (only the font falls back to Menlo). |
| Server down | `./run.sh` in a terminal (takes about 3 s). |
| The answer differs from the rehearsal | Expected: it's a live model. Point to the Method, SQL and review lines; the numbers trace to queries. |
| Asked "is this real data?" | "Synthetic: generated to mirror AHDC's tables, with real-world pitfalls planted on purpose, so the evals have ground truth." |
