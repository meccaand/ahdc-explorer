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
