# AHDC Data Explorer v0.1: locked UI design

**Status: LOCKED 2026-11-14.** Build the front end to match this. No redesigns, new sections, or layout, color or type changes unless Andrew asks.

**Source of truth:** `reference-Main.dc.html` (in this folder; the original export with its viewer runtime is in the project folder outside the repo, `design/reference/`) (exported from the Design canvas at https://claude.ai/artifact/8gg7DQjxxgrUkK8CcNzP7P; identical apart from script tags) and the rendered `design/locked-design.pdf`. Port its styles and structure into `web/`. Do not embed the design-tool runtime (`support.js`, `vendor/`): it is only there for viewing. To view it, run `python3 -m http.server` in `design/reference/` and open `Main.dc.html`.

The earlier exploration in `mockup/` (v1 plus shells A, B, B2 and C) is **superseded**. Keep it for history only.

---

## 1. Spec (from the design session's handoff)

### Look and feel
- Minimal, in the style of the Claude Code CLI. Dark background, monospace everywhere, one accent color. No shadows, and no gradients except the step-list fade.
- Font: JetBrains Mono (Google Fonts), falling back to ui-monospace or Menlo. Base size 14px, line-height 1.6.
- Colors:

  | Token | Hex |
  |---|---|
  | background | `#191918` |
  | text | `#e5e3da` |
  | one-line answer | `#f4f2ea` |
  | muted | `#9b998f` |
  | section text | `#c9c7bd` |
  | border | `#3a3936` |
  | row divider (inside block) | `#2c2b28` |
  | question row bg | `#262624` |
  | code bg | `#121211` |
  | accent | `#d97757` |
  | step dot | `#7fb77e` |
  | step rail | `#4a4945` |
  | connector line | `#6a685f` |
  | axis line | `#5a5852` |
  | secondary series | `#7a786f` (dashed 4 3) |
  | input border | `#5a5852` |

- Glyphs: `●` before each answer, `>` before prompts, `⎿` before results, `▸` for collapsed sections (it rotates 90° when open). No emoji.

### Layout
- **Top bar:** an orange `*`, then **AHDC Data Explorer** in bold, then `v0.1` in grey. Nothing else, and a 1px bottom border.
- **One pane, no vertical divider.** A small uppercase, letter-spaced `> CONVERSATION` label at the top. There is no label above the steps column.
- **Each Q&A turn is a row:**
  - The question is a single line on a `#262624` background with a `>` prefix.
  - The answer sits on the left. That turn's agent steps sit in a 360px column on the right, with a 48px gap.
  - Turns are separated by about 64px of whitespace, never by lines. A horizontal line only means "this answer goes with these steps".
- **Connector:** the answer row reads `● <one-line answer>` in 17px bold, cut off with an ellipsis. A solid 1px line runs from the end of that text to the steps header: `● N steps` on the left with an accent-colored dot, and `Xs` on the right, in 12px grey.
- **Input:** fixed at the bottom. It is a rounded box (8px radius) with a `>` prompt. Under it is a hint row with `↵ send · ⇧↵ newline · / for commands` on the left and the context token count on the right.

### Answer format, top to bottom (indented under the answer text)
1. **The one-line answer** (in the connector row).
2. **Confidence row:** `CONFIDENCE` as a small uppercase label, then a 5-block meter (14×6px blocks, filled `#e5e3da`, empty `#3a3936`), then the level and score in bold, for example **High · 4/5**. The level is spelled out, not shown by color, and there are no reasons on this row.
3. **One bordered block** (1px `#3a3936` border, 4px radius, max-width 820px, every border in it 1px):
   - The chart sits on top: a line chart with the series in the accent color, a dashed grid, grey axis labels and a caption row. A divider separates it from the rows below.
   - Collapsible rows follow, in this order:
     - **Confidence:** factors marked `+` or `−`.
     - **Caveats.**
     - **Assumptions.**
     - **Method:** numbered steps.
     - **SQL:** a dark code block, plus a note naming any other queries.
     - **Source data:** the table name in bold, then the source and indicator, then the row count on the right.
   - Each row header is 40px high and shows a count or summary on the right ("4 factors", "3", "4 steps", "3 queries", "3 tables").
   - **All rows are collapsed by default.**

### Agent steps column (per turn)
- Each step has a green 8px dot, the tool name in bold with its arguments in grey, then `⎿ result` in grey on the next line, at 13px.
- A 1px vertical rail joins the dots from the first step to the last.
- The box is at most 460px tall (at least 220px) and scrolls on its own, so it never spills into the next turn.
- When steps are hidden below the fold, the list fades to the background color at the bottom and shows a small rounded `+N more ↓` button that scrolls it. N is the live count of hidden steps, updated on scroll and resize. At the bottom of the list, the fade and the button disappear.
- A footer sits under the list with a 1px top border: `N tool calls · Xk in / Y out` on the left and a `raw trace` link on the right.

### Rejected ideas (do not bring back)
- A "big number" stat under the answer
- A border around the whole answer
- A separate agent activity panel with a vertical divider, or click-to-select turns
- An "Agent steps" column label, or source text in the top bar
- Dashed or dotted connector lines
- (From earlier rounds) the "SDK concepts" and "Methods review" toggles, the left icon rail, and the light theme

---

## 2. Wiring the design to our app (build notes)

The mockup's content is placeholder: an under-5 mortality example, WDI/GHO table names, invented tool names, SQL, token counts and timings. The table below shows what replaces each part.

| UI element | Comes from | Notes |
|---|---|---|
| One-line answer | `submit_answer.headline` | One sentence, no trailing period, aiming for ≤ 70 chars. The skill enforces this. |
| Confidence level, score and factors | `submit_answer.confidence_factors` (each `+` or `−`) | **The server computes the score:** 5 minus the number of `−` factors, with a floor of 1. 5–4 = High, 3 = Medium, 2–1 = Low. This matches both mockup turns (one `−` gives 4/5; two give 3/5). The skill lists which factors count, so the score follows a rubric and isn't left to the model's own sense of certainty. |
| Caveats, Assumptions, Method | `submit_answer.caveats`, `.assumptions`, `.method` (lists of strings) | Wording rules live in the skill. Method steps are plain language. |
| SQL rows | **The `run_sql` calls this turn actually made**, captured by the PostToolUse hook | Not written by the model, so it can't drift from what really ran. The first query is shown in full; the note names the others by their `purpose` (for example "+2 more: missing countries, data notes"). |
| Source data rows | Tables parsed from each query's SQL (`sqlglot`) plus the row counts returned | The description comes from the data dictionary. Also not written by the model. |
| Chart | `render_chart(query_ref, type, x, y, series?, title, unit)` | It plots **the rows a referenced `run_sql` call returned**, so the model never types the plotted numbers. Types are `line` (the design as given) and `bar`; see gaps below. Caption: indicator · unit · scope on the left, `[synthetic data]` on the right. |
| Steps list | SDK `AssistantMessage` content in order | `ToolUseBlock` gives the tool name with `mcp__ahdc__` removed and compact args (`run_sql` shows its `purpose`, not the SQL). The `⎿` line is a one-line `summary` that every tool returns. The model's first text block becomes the `plan` step. The skill load appears as `skill(ahdc-analysis-standards)`. The reviewer subagent (`Agent` tool) appears as `methods_review` with `⎿ 4/4 checks passed`. `submit_answer` is the last step. |
| Steps header `N steps · Xs` | Step count; `ResultMessage.duration_ms` | |
| Steps footer `N tool calls · Xk in / Y out` | Tool-use count; `ResultMessage.usage` input (including cache) and output tokens | |
| `raw trace` link | That turn's raw SDK message log as JSON | **This is the "it really is the SDK" moment for the Director**, replacing the dropped SDK-concepts toggle: it shows the real `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock` and `ResultMessage` objects. |
| `ctx N tokens` | Context size of the last turn (input + cache read + cache creation) | |
| `/ for commands` | `/new` (new session) and `/help` | Kept minimal. |

**Answer contract:** the agent ends every turn by calling a custom `submit_answer` tool, whose input schema is `{headline, confidence_factors[{sign, text}], caveats[], assumptions[], method[]}`. The server validates the input; if it's invalid, the tool returns an error and the agent fixes it. The SDK's structured-output option is an alternative to check in M2, but a tool keeps the final step visible in the steps column, just as the mockup's `write_summary` is.

**Guardrails in this design:** PreToolUse/PostToolUse hooks still run on every query. There is no dedicated UI for them. A denied query would appear as an ordinary step whose `⎿` line gives the denial reason.

---

## 3. Not covered by the mockup (defaults derived from the design; review at M3)

These states don't appear in the locked artboard. The defaults below use only the tokens and patterns above; nothing new is added.

1. **In-progress turn:** steps stream into the column as they happen, and the header reads `● N steps` with the live elapsed time. The answer row reads `● working…` in muted text until `submit_answer` arrives, then the confidence row and block appear.
2. **Empty state (no turns yet):** only the `> CONVERSATION` label and the input. The input placeholder cycles through the demo questions; there are no suggestion cards, which keeps the design minimal.
3. **Bar charts** (Southeast Asia spending; the 2015 drivers follow-up): horizontal bars in the accent color with category labels in muted grey, the same dashed grid, axis color and caption row as the line chart, and values in `#e5e3da`. A second series or an "other" group uses `#7a786f`.
4. **Two-series line** (India DTP3 vs MCV1): the pattern from mockup turn 2. The primary series is solid accent; the secondary is dashed `#7a786f`; the legend sits in the caption row.
5. **Answers with no natural chart:** the agent charts the context, for example a single-year rate shown on its 2000–2025 trend with the latest point marked. If it can't, the block starts with the Confidence row.
6. **Errors** (tool failure, budget hit): the answer row shows `● ` plus a one-line message in muted text, and the steps column shows the failing step's `⎿` reason.

### Implemented in M3 (2026-11-14). Review with Andrew.
- (1) In progress: as specified. While a turn is running, the steps column is 300px tall (220px minimum otherwise), so more steps are visible.
- (2) Empty state: just the label and the input. Hidden helpers: Tab on an empty prompt fills the next demo question; ↑ recalls history.
- (3)/(4) Bar and two-series line charts: as specified. Line charts keep the 0 baseline unless the values sit in a narrow band far from zero (e.g. 85–93% coverage), where a zero baseline would flatten the trend.
- (6) Errors: as specified.
- SQL row: the headline's query (`primary_query_id`) is shown first; clicking an "other queries" name shows that query instead.
- Cost is shown at the end of the steps footer: `N tool calls · Xk in / Y out · $0.14` (Andrew, 2026-11-14).

### Changes Andrew requested after M3 (2026-11-14). These supersede the spec above where they differ.
- ~~The steps column width is `clamp(360px, 33vw, 520px)`~~ → **The answer and steps columns split 60/40** (Andrew, 2026-11-14). The connector row and the turn body share one grid (`34px | 3fr | 48px | 2fr`) so they line up; about 780px / 520px at 1440 wide. The answer block's 820px cap is removed. Headlines stay on one line with an ellipsis (wrapping was tried and rejected). Below 980px the steps stack under the answer.
- The `[synthetic data]` caption label is removed.
- While a turn is running, the steps list flows at its natural height (every step visible, no scroll box, newest step kept in view). When the answer arrives it condenses to the 220–460px scroll box with the fade, the "+N more ↓" button and the footer.
- The "> CONVERSATION" label is removed.
- While a turn is running, the steps footer (rule, usage and raw-trace link) is hidden. Once condensed, the steps column is exactly as tall as the answer column (no 460px cap; at least 220px).
- The steps footer shows cost: `N tool calls · Xk in / Y out · $0.06`.

### Methods review (M5, 2026-11-14)
- The step order ends `submit_answer ⎿ answer submitted` → `methods_review(methods-reviewer) ⎿ PASS — 6/6 checks passed` (or `ISSUES — K/6`) → possibly a second `submit_answer`.
- The answer (headline, confidence, block) appears as soon as the draft is submitted. The steps column stays in its live, natural-height mode until the review finishes, then condenses. If the draft is revised, the answer re-renders in place and keeps the rows the reader had open.
- The last Method item is written by the server from the actual verdict: "Independent methods review (Haiku 5.5): PASS — 6/6 checks passed." or "… flagged 1 issue; the answer was revised to address it."

