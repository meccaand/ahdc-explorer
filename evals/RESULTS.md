# Eval results (2026-11-14)

Golden set: 15 questions (`evals/golden.yaml`). Expected values are computed from the database at grading time. Grading is deterministic: numbers within tolerance, required mentions (region definition, provisional status, data year…), forbidden values (e.g. the unweighted mean in the headline), and "no invented numbers" for a question the data can't answer. It runs through the same agent code path as the web UI.

## Model comparison (same skill, prompt and tools; effort `medium`)

| Model | Passed | Median s / question | Max s | Cost / question |
|---|---|---|---|---|
| **claude-sonnet-5-5** (default) | **30 / 30** (2 runs) | **13.3** | 21.4 | **$0.033** |
| claude-opus-5-5 | 15 / 15 (1 run) | 20.8 | 39.0 | $0.097 |
| claude-haiku-5-5 | 27 / 30 (2 runs) | 10.9 | 23.0 | $0.002 |

Haiku's misses were wrong numbers, not formatting: the WHO African Region malaria rate as 27.1 instead of 54.2, and the 2015 Sub-Saharan Africa rate as 76.2 instead of 78.2. It also rounded 54.2 to "about 54". **Decision:** Sonnet 5.5 for the main agent. It is as accurate as Opus on this set, about 35% faster, at a third of the cost. Haiku is a candidate for the reviewer subagent, where its output is checked anyway.

## Demo beats, repeated

| Beat | Before the skill fixes | After |
|---|---|---|
| Malaria, Sub-Saharan Africa 2025 | 5/5 | 5/5 |
| Follow-up: vs 2015, drivers | 5/5 (Opus 0/1: didn't name Nigeria) | 5/5 |
| India DTP3, last decade | 5/5 | 5/5 |
| Southeast Asia spending | **3/5** (used today's ASEAN incl. Timor-Leste for 2023 data) | **5/5** |

## What the evals caught and how we fixed it
1. **Region membership vs data year:** the skill now says to resolve ASEAN `as_of_year` = the data year and to mention Timor-Leste in Caveats.
2. **Answering "which":** drivers have to be named in the text, not only shown in a chart.
3. Earlier (M2/M3): confidence drift. Fixed by a 4-check rubric and a required alternative-region robustness check.

Raw results: `evals/results/*.jsonl`. Re-run: `uv run python evals/run_evals.py [--only demo] [--repeat N] [--model …]`.
