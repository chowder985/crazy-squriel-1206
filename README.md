# Three-Agent Full-Stack Web Harness

A Claude Code framework that produces high-quality full-stack web applications through a **Planner → Generator → Evaluator** loop, based on Anthropic's [harness design for long-running coding agents](https://www.anthropic.com/engineering/harness-design-long-running-apps).

Extends the original architecture with a **Figma design fidelity** validation step.

---

## What this is

Three Opus agents that talk through files in `.harness/`:

- **Planner** — turns a 1–4 sentence prompt (and/or a Figma source) into a full product spec. Ambitious about scope, deliberately high-level on technical implementation.
- **Generator** — negotiates a sprint contract with the Evaluator, then implements one feature/sprint at a time. Self-evaluates before handoff. Decides refine-vs-pivot after each evaluation.
- **Evaluator** — a *separate* agent invocation. Skeptical and strict. Drives Playwright to actually exercise the running app — clicks, types, drags, intercepts network, queries the database. Scores per-criterion against hard thresholds. Files file:line-specific bug reports.

Two modes:

- **Per-sprint** (default for ambitious builds) — contract negotiation + evaluation per sprint, up to 15 iterations.
- **End-to-end** (default for narrow tasks) — one contract for the whole spec, up to 5 build/QA rounds.

Plus an extension beyond the article: when a Figma source is provided, an additional **Design Fidelity** criterion is appended to the rubric, requiring measured pixel-level deltas — not "looks close."

---

## Architecture at a glance

```
                ┌─────────────┐
   prompt + ──→ │   Planner   │ ──→  .harness/plans/spec.md
   --figma     │   (Opus)    │
                └─────────────┘
                       │
                       ▼
   ┌──────────────────────────────────────────────────┐
   │                                                   │
   │  loop per sprint (or once, end-to-end mode):      │
   │                                                   │
   │   ┌────────────┐  contract  ┌────────────┐         │
   │   │ Generator  │ ◀────────▶ │ Evaluator  │         │
   │   │  (Opus)    │            │  (Opus)    │         │
   │   └────────────┘            └────────────┘         │
   │         │                          ▲              │
   │         ▼                          │              │
   │   implement → start dev server → handoff          │
   │                                    │              │
   │                                    ▼              │
   │                        Playwright + curl + DB     │
   │                          ↓                        │
   │                  per-criterion scores             │
   │                          ↓                        │
   │              pass → next sprint                   │
   │              iterate → refine or pivot            │
   │              cap hit → escalation file, halt      │
   │                                                   │
   └──────────────────────────────────────────────────┘
```

All file communication lives in `.harness/`:

```
.harness/
├── plans/            spec.md
├── contracts/        sprint-NN-contract.md
├── handoffs/         sprint-NN-handoff.md
├── evaluations/      sprint-NN-evaluation.md
├── escalations/      sprint-NN-escalation.md
├── figma/            (assets when MCP unavailable)
└── state.json
```

---

## Install

This framework is a copy-in `.claude/` directory plus templates and examples.

### New project

```bash
mkdir my-app && cd my-app
# copy this framework's files in:
cp -r /path/to/optisigns-assessment/{.claude,templates,examples,.gitignore,README.md,QUICKSTART.md} .
git init
```

### Existing project

```bash
cd my-existing-app
cp -r /path/to/optisigns-assessment/{.claude,templates,examples} .
# add to your existing .gitignore:
echo ".harness/" >> .gitignore
```

### MCP prerequisites (both modes)

```bash
# Required — Evaluator drives Playwright via this MCP:
claude mcp add playwright npx @playwright/mcp@latest

# Optional — for Figma-driven runs, install a Figma MCP server (see Figma's docs)
```

Restart Claude Code after MCP changes.

---

## Run

```bash
# greenfield, ambitious app:
/harness-init --prompt "A small-team kanban board with realtime drag-drop and a thoughtful design language" --mode per-sprint

# narrow add to existing app:
/harness-init --prompt "Add card archiving with a 30-day grace period and a search-archive page" --mode end-to-end

# Figma-driven:
/harness-init --prompt "Implement the marketing site" --figma https://figma.com/file/ABC123/My-Design
# (or, with no Figma MCP installed, export frames + tokens and pass --figma <dir>)

# kick off the first sprint after spec is ready:
/harness-sprint

# inspect anytime (read-only):
/harness-status

# resume after interruption:
/harness-resume
```

---

## Configuration

### Model

All three agents declare `model: opus` in their frontmatter — they resolve to whatever Opus model your Claude Code install is configured to use. To pin a specific version, edit each agent file:

```yaml
# .claude/agents/{planner,generator,evaluator}.md
model: claude-opus-4-7   # or whatever the current latest is
```

### Per-criterion threshold

Default: 7/10. Override per sprint by editing Section 6 of the contract before agreement, or change the global default in `.claude/skills/grading-rubric/SKILL.md`.

### Iteration caps

- Per-sprint: 15 iterations (article ran 5–15 for frontend; cap at the upper end for full-stack).
- End-to-end: 5 build/QA rounds (article's DAW example used 3).

Override per run via `/harness-sprint --max-iterations N`.

### Hard caps & escalation

Caps are hard. When hit, the Generator writes `.harness/escalations/sprint-NN-escalation.md` and the run halts. The user decides whether to relax the contract, intervene manually, or skip the sprint.

---

## The evaluator tuning loop

> The single most important operator practice. Calibration was the lever the original author used to keep the Evaluator's judgment matching theirs. Expect multiple rounds.

After a few sprints (or after the first end-to-end run):

1. **Read** the evaluator outputs in `.harness/evaluations/`.
2. **Find divergence.** For each scored criterion, ask: would I have scored it the same? When the Evaluator passed something you'd fail, or failed something you'd pass, that's drift.
3. **Update the prompt.** Edit `.claude/agents/evaluator.md` — usually by:
   - Adding a new few-shot scoring example to the calibration section that nails the case the Evaluator got wrong.
   - Strengthening the wording on a specific criterion in `.claude/skills/grading-rubric/SKILL.md` (remember: criterion wording shapes Generator output too).
   - Tightening the "talking yourself out of issues" warning if the Evaluator is rounding up.
4. **Re-run** the same sprint (`/harness-resume --reset-iteration`) and check whether the Evaluator now scores closer to your judgment.
5. **Repeat.** Several rounds of this loop are normal before the Evaluator is well-calibrated to a given product domain.

The article called this out as the practical work that makes the harness produce high-quality output, not the architecture itself.

---

## Worked example

See `examples/kanban-sprint-3/` for a full Sprint 3 cycle: spec excerpt, contract negotiation (with real Evaluator pushback), Generator implementation summary with file paths, and Evaluator scored report with file:line bug findings (`boardStore.ts:171`, `useBoardSocket.ts`, `test_cards.py:48`).

---

## Files

```
.
├── .claude/
│   ├── agents/
│   │   ├── planner.md
│   │   ├── generator.md
│   │   └── evaluator.md
│   ├── commands/
│   │   ├── harness-init.md
│   │   ├── harness-sprint.md
│   │   ├── harness-resume.md
│   │   └── harness-status.md
│   └── skills/
│       ├── grading-rubric/SKILL.md
│       ├── sprint-contracts/SKILL.md
│       ├── playwright-qa/SKILL.md
│       └── figma-validation/SKILL.md
├── templates/
│   ├── spec-template.md
│   ├── contract-template.md
│   └── evaluation-template.md
├── examples/
│   └── kanban-sprint-3/
│       ├── spec-excerpt.md
│       ├── sprint-03-contract.md
│       ├── sprint-03-implementation-summary.md
│       └── sprint-03-evaluation.md
├── README.md
├── QUICKSTART.md
└── .gitignore
```

---

## Things this framework deliberately does NOT do

- **No context-reset machinery.** Opus removed enough of the "context anxiety" that compaction handles the long session. Don't rebuild what was removed.
- **No pass/fail aggregate.** Per-criterion thresholds are independent — strong scores in one criterion never compensate for a sub-threshold score in another.
- **No same-agent self-grading.** The Generator and Evaluator are separate Task invocations. Always.
- **No "looks close" Figma evaluation.** Every deviation is logged with a measured delta in the Design Fidelity table.
- **No infinite iteration.** Hard caps with escalation, every time.
