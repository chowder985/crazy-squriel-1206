# Quickstart

One page. Three setup paths. Five minutes each.

---

## 0. Prerequisites (all paths)

```bash
# Required: Playwright MCP — Evaluator drives a real browser through this.
claude mcp add playwright npx @playwright/mcp@latest

# Restart Claude Code after adding any MCP.
```

You'll need Node 20+ and Python 3.11+ for the default React + Vite + FastAPI + SQLite stack. The Generator will install per-project deps as it scaffolds.

---

## A. New project — greenfield

```bash
mkdir my-new-app && cd my-new-app
cp -r /path/to/optisigns-assessment/{.claude,templates,examples,.gitignore} .
git init && git commit --allow-empty -m "init"

# kick off:
/harness-init --prompt "A small-team kanban board with realtime drag-drop and a thoughtful design language"

# Planner writes .harness/plans/spec.md — review it.
# When you're happy:
/harness-sprint
```

The Planner picks `per-sprint` mode by default for ambitious greenfield prompts. To force end-to-end, pass `--mode end-to-end`.

---

## B. Existing project — add a feature

```bash
cd my-existing-app
cp -r /path/to/optisigns-assessment/{.claude,templates,examples} .
echo ".harness/" >> .gitignore
git add .claude templates examples .gitignore && git commit -m "add three-agent harness"

# narrow scope, end-to-end:
/harness-init --prompt "Add card archiving with a 30-day grace period and a search-archive page" --mode end-to-end

# review the spec at .harness/plans/spec.md, then:
/harness-sprint
```

The Planner runs a detection pass first — reads `package.json`, `pyproject.toml`, top-level dirs, lint configs — and constrains the Generator to match your existing conventions. The Evaluator's Code Quality criterion explicitly checks for convention conformance.

---

## C. Figma-driven run

### C1. With a Figma MCP installed

```bash
# follow Figma's docs to install the Figma MCP, then:
/harness-init --prompt "Implement the marketing site" --figma https://figma.com/file/ABC123/My-Design
```

The Planner reads tokens, components, and frames directly from the Figma file via MCP and bakes them into the spec. The Evaluator gets a Design Fidelity criterion appended, requiring measured pixel-level deltas.

### C2. Without a Figma MCP — static export fallback

```bash
# Export from Figma:
#   - design tokens to tokens.json (Style Dictionary or raw)
#   - per-screen frames to frames/ as PNGs (filename: <frame-id>-<slug>.png)
mkdir -p .harness/figma/frames .harness/figma/components
# move your exports under .harness/figma/

/harness-init --prompt "Implement the marketing site" --figma .harness/figma
```

When using static fallback, the Evaluator's screenshot diff anchors on the PNGs you provided.

---

## During a run

```bash
# inspect anytime — read-only
/harness-status

# resume after interruption (auto-detects where you stopped)
/harness-resume

# if the harness halted at the iteration cap, read the escalation:
cat .harness/escalations/sprint-NN-escalation.md
# then either:
/harness-resume                    # try again with current contract
/harness-resume --reset-iteration  # start iteration count over (after you intervened)
/harness-resume --skip-sprint      # mark the sprint skipped and move on
```

---

## When the Evaluator misjudges

It will, especially in the first few sprints of a new product domain. That's expected — Anthropic's article calls calibration the practical work that makes the harness produce high-quality output.

1. Read the evaluation in `.harness/evaluations/`.
2. Find a criterion where the Evaluator's score doesn't match yours.
3. Edit `.claude/agents/evaluator.md` — add a few-shot example to the calibration section that nails the case it got wrong.
4. Re-run with `/harness-resume --reset-iteration`.
5. Repeat over 2–4 sprints. The Evaluator gets noticeably better as it accumulates calibration examples.

---

## Worked example

`examples/kanban-sprint-3/` shows a full Sprint 3 cycle for a kanban board's drag-drop + websocket sync feature:

- `spec-excerpt.md` — the Planner's relevant slice
- `sprint-03-contract.md` — Generator proposed 14 criteria; Evaluator pushed back; final 22-criterion contract
- `sprint-03-implementation-summary.md` — Generator's handoff with file paths and self-evaluation
- `sprint-03-evaluation.md` — Evaluator's scored report with four `must` failures, file:line bug reports (`boardStore.ts:171`, `useBoardSocket.ts`, `test_cards.py:48`), and a strategic refine note

Worth reading end-to-end before your first run — it shows what good back-and-forth between the agents actually looks like.

---

## Anti-checklist (don't do these)

- Don't combine the Generator and Evaluator into one invocation. Always separate.
- Don't relax the per-criterion threshold to "make it pass." Failing scores point at real issues.
- Don't push to remote inside a sprint. The Generator commits locally; you control remote state.
- Don't reset the harness state mid-sprint to "start fresh." Use `/harness-resume --reset-iteration` instead — it preserves the contract.
