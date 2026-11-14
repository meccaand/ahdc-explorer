---
name: ahdc-analysis-standards
description: AHDC data team's standards for answering questions from the AHDC health database. Covers aggregating rates across countries, region definitions, provisional and missing data, coverage sources, currencies, charts, and the required answer format with its confidence checklist. Load before answering any data question.
---

# AHDC analysis standards

These are the data team's house rules. Follow them for every answer. When a rule forces a choice the user didn't specify, **state the choice as an assumption and name the alternative.** Don't stop to ask unless the question is truly unanswerable without it.

## 1. Numbers come only from queries
- Every number in the answer must come from a `run_sql` result in this session, or be computed directly from one (show the arithmetic in Method).
- Never use outside knowledge for values. If the data can't answer the question, say so in the headline.

## 2. Aggregating across countries
- **Rates:** sum the counts and divide by summed population: `1e5 * SUM(count) / SUM(population)`. Never average country `rate_per_100k` values. When it matters, say the simple average would differ, and by how much.
- **Uncertainty for an aggregate:** sum the country `lower` and `upper` counts, divide by the same population, and report it as a 95% uncertainty interval.
- **Vaccine coverage across countries:** weight by `under5_population`. For ITN use, weight by `population`.
- **Coverage:** say how many countries contributed, e.g. "46 of 48 countries", and name any that are missing.
- **Comparisons over time:** use the same set of countries in both years, so the change isn't an artifact of which countries reported.

## 3. Region definitions
- Always resolve a region with `get_region_members`, and state the scheme and the country count.
- "Sub-Saharan Africa": default to the World Bank region (48 countries). The alternative is the WHO African Region (47 countries: it adds Algeria and leaves out Sudan and Somalia).
- "Southeast Asia": default to the 10 ASEAN members as of the data year (Timor-Leste joined in 2025). The alternatives are the UN 'South-eastern Asia' subregion and the WHO South-East Asia Region, which includes India and Bangladesh and is a different grouping.
- "South Asia": World Bank region (8 countries).
- Other names: pick the closest scheme, state it, and name the alternative.
- **Robustness check (required):** when a region has a common alternative definition (e.g. Sub-Saharan Africa → WHO African Region), run the same calculation for the alternative as well, in the same query or right after it, and report the result in Assumptions. In a follow-up, a check already done earlier in the conversation counts; say so.
- For the confidence `definition` check: "Southeast Asia" and other names that map to materially different country sets are `-` unless the user named the grouping. "Sub-Saharan Africa" is `+` if you checked the WHO African Region and the result is similar.

## 4. Data quality
- **Provisional:** 2025 values are provisional. Flag this in Caveats whenever 2025 data is used.
- **Latest year:** if the user asks for "latest" or "now", use the latest year with data, and say which year that is. Health spending ends in 2023.
- **Data notes:** always check `get_data_notes` for the table, indicator and countries used, and surface anything relevant as a caveat.
- **Coverage source:** use `source = 'modeled'` for trends and comparisons. Admin figures can exceed 100%, so mention them only to explain a discrepancy.
- **Indicator choice:** "child vaccination coverage" means DTP3, the standard proxy. Mention MCV1 as a secondary indicator where useful.
- **"Last decade":** the 10 years up to the latest year, e.g. 2015–2025.
- **Spending:** state USD or PPP. For cross-country comparison, report both; PPP is the fairer comparison of purchasing power.
- **Facilities:** normalize counts by population (per 100,000) and use survey years only.

## 5. Charts
- Add a chart with `render_chart` when it helps: a line chart for trends over years, a bar chart to compare countries or regions.
- For a single-year rate question, chart the regional trend over time from a query that returns year and rate, so the reader sees the number in context.
- The plotted query must return exactly the columns plotted, in tidy form: one row per (x, series).
- At most 4 lines and at most 25 bars.

## 6. Answer format (`submit_answer`)
- **headline:** one plain sentence with the key number and unit, under 90 characters, no trailing period. Spell out region names ("Sub-Saharan Africa", not "SSA"). Example: "Malaria killed 52.1 per 100,000 people in Sub-Saharan Africa in 2025".
- **caveats:** 1–4 short sentences: provisional data, missing countries, admin vs modeled, estimation changes.
- **assumptions:** 1–4 short "X = Y" style statements, e.g. "\"Sub-Saharan Africa\" = World Bank region (48 countries)", plus any default choice (indicator, years, currency).
- **method:** 2–5 plain-language steps a non-technical reader can follow (don't number them; the UI does). Include the aggregation rule.
- **confidence_factors:** exactly four, one per check below, in this order. Each gets `+` or `-` and one short sentence of specifics. The UI score is 5 minus the number of `-` checks.

### Confidence checklist (apply literally; don't round up)
| check | `+` when | `-` when |
|---|---|---|
| `completeness` | Every country and year in scope has data | Any country or year in scope is missing (name them), even if excluded consistently |
| `finality` | All values used are final, and any uncertainty interval is within ±25% of the estimate | Provisional (2025) values are used, or an interval is wider than ±25% of the estimate |
| `definition` | The question maps to one standard definition, or you checked the obvious alternative and the conclusion holds | A plausible alternative (region, indicator, years, currency) would change the answer materially, or you didn't check it |
| `consistency` | No data note reports a problem affecting the values used, or the problem is resolved (e.g. back-cast series) and noted in Caveats | A data note reports an unresolved methodology break or data-quality problem in the values used |

After `submit_answer` is accepted, reply with the headline only.
