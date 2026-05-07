---
name: figma-validation
description: How the harness validates a Figma source against the running implementation. Token extraction, frame mapping, screenshot-vs-frame deltas, and the rule that all deviations must be measured (not "looks close"). Loaded by all three agents on Figma-driven runs.
---

# Figma Validation

> Extension beyond the original article. Goal: when the work is driven by a Figma source, every UI surface in the implementation can be traced back to a Figma frame and any deviation has a measured delta.

---

## Detection — is a Figma source available?

At init, `harness-init` checks for any of:

1. **Figma MCP server connected** — look for `mcp__figma__*` tools in the available tool list, or check the user's MCP config (`~/.claude.json` or project `.mcp.json`). If present, prefer the MCP — it lets you read frames and tokens directly from the file.
2. **`--figma <url>` argument** with a Figma file URL. Without an MCP, the harness records the URL but cannot read the file directly; the user must export assets to fall back on.
3. **`--figma <dir>` argument** with a local directory of exports. Expected layout:
   ```
   <dir>/
   ├── tokens.json          # Style Dictionary or raw token export
   ├── frames/
   │   ├── 12-34-board-default.png
   │   ├── 12-50-card-hover.png
   │   └── ...
   └── components/
       └── (optional component-level exports)
   ```

If both MCP and a local dir are available, prefer MCP for reads; use the local dir for screenshot-diff anchors.

If no Figma source is available, the Design Fidelity criterion is not appended — but the regular Visual Design criterion still applies.

---

## Planner phase — extracting the design language

The Planner does:

1. Read all in-scope frames (via MCP, or list the local export dir).
2. Build a **token table** in the spec under "Design Language":
   - Color tokens: `semantic name → hex`.
   - Typography: `font family, scale stops, weights`.
   - Spacing: `base unit, scale`.
   - Radii, shadows, motion durations.
3. Build a **frame inventory** in the spec under "Page / Screen List":
   - For each in-scope page/component: Figma frame id, name, brief description.
4. Note any **Figma-defined component states** (hover, focus, disabled, loading, empty) per surface.

The spec is the source of truth for the Generator — Figma is referenced by frame id from there on.

---

## Generator phase — implementing against tokens & frames

- Reference tokens by name in code (e.g., `var(--color-bg-canvas)`, not raw hex). The Evaluator will check that no raw hex from the design appears inline in source files where a token would do.
- Each contract must include, per surface in scope, a criterion of the shape:
  > *"Implementation of `<frame name>` (Figma frame `<id>`) matches the frame at the pixel level."*
- The Generator should annotate which file(s) implement which frame, in the sprint handoff (`.harness/handoffs/sprint-NN-handoff.md`), so the Evaluator can compare specific URLs to specific frames.

---

## Evaluator phase — measuring fidelity

For each in-scope frame:

1. **Navigate** Playwright to the implementing surface (URL from the handoff).
2. **Resize** the viewport to match the frame's design width (e.g., 1440 for desktop frames).
3. **Screenshot** at full surface scale (`browser_take_screenshot`).
4. **Open** the Figma frame: via MCP (`mcp__figma__get_screenshot` or equivalent) or read the local PNG.
5. **Compare** by inspection. Log specific deviations in the Design Fidelity table of the evaluation report:

   | Surface | Figma frame | Deviation | Measured delta | Severity |
   |---|---|---|---|---|

6. **Probe states** — for each Figma-defined state (hover, focus, disabled, loading, empty), reproduce the state in the running app and verify it matches the corresponding frame.

---

## What counts as a deviation worth flagging

The Evaluator MUST log a delta when:

- **Spacing** between visible elements differs by **>4px**.
- **Color hex** differs from the Figma token, even if "visually similar." `#0F62FE` vs `#1F6FEB` is a delta — log it.
- **Typography scale** or weight differs (e.g., implemented `1.25rem/500` vs Figma `1.5rem/600`).
- **A defined state is missing** (e.g., Figma has a hover state but the implementation has no `:hover` rule).
- **Layout structure** differs (column count, grid gap, sidebar width).

### Severity

- **High:** affects the perceived correctness of the surface (missing state, large spacing delta, wrong hex on primary brand color).
- **Medium:** noticeable but not jarring (small spacing delta, secondary color hex slightly off).
- **Low:** minor (1-2px deltas inside the threshold; font rendering differences inherent to browsers).

---

## What "looks close" is NOT allowed to mean

You may not write:

- "The implementation looks close to the Figma frame."
- "Spacing is approximately right."
- "Colors are visually similar."

You must write:

- "Header padding implemented at 16px; Figma frame defines 24px (delta: 8px, high severity)."
- "Primary button color implemented as `#1F6FEB`; Figma token defines `#0F62FE` (delta: hex mismatch, high severity)."
- "Card corner radius implemented at 6px; Figma frame defines 8px (delta: 2px, low severity — within tolerance)."

Specific, measured, defended.

---

## Pixel-level comparison tooling notes

Visual diff tools (`pixelmatch`, `odiff`, `playwright`'s built-in `toMatchSnapshot`) can produce overlay diffs but they tend to flag font-rendering differences as deltas. Use them as a hint, not a verdict. The Evaluator's judgment — backed by measured numbers — is what scores the criterion.

If the user provides a baseline screenshot in the export dir, the Evaluator can run a simple comparison via Bash (e.g., `magick compare -metric AE old.png new.png diff.png`) and log the pixel difference in the table.

---

## Token-leak check

A separate sanity sweep the Evaluator should run:

```bash
grep -rE "#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b" src/ --include="*.tsx" --include="*.ts" --include="*.css" \
  | grep -v "// allow-raw-hex"
```

Any inline hex in source files is a code-quality issue when tokens exist. Log it as a `Code Quality` deduction, not as `Design Fidelity` (those are separate criteria).
