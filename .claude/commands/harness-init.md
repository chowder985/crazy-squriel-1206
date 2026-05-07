---
description: Initialize a harness run. Accepts --prompt, --figma (URL or dir), --mode per-sprint|end-to-end. Detects new vs existing codebase and Figma MCP availability, scaffolds .harness/, and invokes the Planner agent.
argument-hint: --prompt "<description>" [--figma <url-or-dir>] [--mode per-sprint|end-to-end]
---

# /harness-init — initialize a three-agent harness run

Argument string: `$ARGUMENTS`

## What this command does

1. **Parse arguments** from `$ARGUMENTS`:
   - `--prompt "<text>"` — short product description (1–4 sentences). Required unless `--figma` alone is sufficient.
   - `--figma <url-or-dir>` — Figma file URL or local export directory. Optional.
   - `--mode per-sprint | end-to-end` — explicit mode override. Optional.
   - `--target-dir <path>` — target project directory. Optional, default cwd.

2. **Detect mode** if not specified:
   - List the working directory; ignore harness scaffolding (`.harness`, `.git`, `.claude`, `templates`, `examples`, `.gitignore`, `README.md`, `QUICKSTART.md`).
   - If non-trivial files remain → existing-codebase mode.
   - Otherwise → new-project mode.

3. **Pick rubric & per-sprint vs end-to-end default:**
   - Existing-codebase + narrow ask → end-to-end (1 contract, up to 5 build/QA rounds).
   - Greenfield + ambitious ask → per-sprint (one contract per sprint, up to 15 iterations per sprint).
   - User's `--mode` always wins.

4. **Detect Figma source availability** (if `--figma` was passed):
   - Check for `mcp__figma__*` or `mcp__plugin_figma_figma__*` tools.
   - If a URL was passed but no Figma MCP is connected, ask the user to either install one (`claude mcp add figma ...`) or export frames + tokens to a directory and re-pass `--figma <dir>`.
   - If a directory was passed, list it and verify it has `tokens.json` and a `frames/` subdir.

5. **Scaffold `.harness/`:**

   ```
   mkdir -p .harness/plans .harness/contracts .harness/evaluations .harness/handoffs .harness/escalations .harness/figma
   ```

6. **Verify Playwright MCP is installed** (the Evaluator needs it):
   - If absent, instruct the user: `claude mcp add playwright npx @playwright/mcp@latest` and restart Claude Code, then re-run.

7. **Invoke the Planner agent** via the Task tool with `subagent_type: planner`. Pass the parsed args in the prompt:
   - The user's `--prompt` text (verbatim).
   - The Figma source path / URL (if any).
   - The detected mode.
   - The recommended rubric.
   - The target directory.

8. After the Planner finishes (writes `.harness/plans/spec.md` + `.harness/state.json`), tell the user:
   - The spec is at `.harness/plans/spec.md` — they should review it.
   - To start the first sprint: `/harness-sprint`.
   - To check status anytime: `/harness-status`.

## Errors & guardrails

- If `--prompt` is missing AND `--figma` is missing: ask the user for at least one.
- If `--target-dir` doesn't exist: ask whether to create it.
- If `.harness/state.json` already exists with `phase != "spec-complete"`: warn that a run is already in progress; suggest `/harness-resume` or explicit confirmation to overwrite.
- If the working dir has uncommitted changes in existing-codebase mode: warn the user; recommend they commit or stash first so the Generator's per-sprint commits stay clean.
