# MRR Dashboard — Sprint 1: Stripe Test Data Seeding

A comprehensive tool to seed realistic test data into Stripe for the MRR (Monthly Recurring Revenue) Dashboard project. This script creates 50–100 test customers with 6 months of billing history using Stripe Test Clocks, enabling accurate testing of dashboard calculations and visualizations.

---

## Sprint 1: Stripe Data Seeding

This sprint focuses on data preparation for the MRR Dashboard. No UI or application logic is built; the focus is solely on populating a test Stripe account with realistic subscription data.

### Quick Start

```bash
# Install dependencies
pip install -r scripts/requirements.txt

# Copy the example environment file to the PROJECT ROOT (not scripts/)
cp scripts/.env.example .env

# Edit .env and add your Stripe test API key
# STRIPE_API_KEY=sk_test_...

# Run the seeding script
python scripts/seed_stripe_data.py

# Or with explicit API key
python scripts/seed_stripe_data.py --api-key sk_test_your_key_here

# Dry-run mode (no API calls)
python scripts/seed_stripe_data.py --dry-run --num-customers 100

# Clean up test clocks afterward
python scripts/seed_stripe_data.py --cleanup
```

### Prerequisites

- Python 3.9+
- Stripe test account (free at https://stripe.com)
- Stripe test API key (from https://dashboard.stripe.com/apikeys, in test mode)

### Installation

```bash
cd scripts
pip install -r requirements.txt
```

### Configuration

Create a `.env` file at the **project root** (one level above `scripts/`):

```bash
cp scripts/.env.example .env
```

Edit `.env` and add your Stripe test API key:

```
STRIPE_API_KEY=sk_test_your_key_here
```

Alternatively, pass the key via CLI:

```bash
python seed_stripe_data.py --api-key sk_test_your_key_here
```

### Running the Script

#### Default seeding (75 customers)

```bash
python seed_stripe_data.py
```

#### Custom customer count

```bash
python seed_stripe_data.py --num-customers 100
```

#### Dry-run mode (no API calls)

```bash
python seed_stripe_data.py --dry-run
```

Useful for testing without consuming API quota or creating real data.

#### Custom random seed (for reproducibility)

```bash
python seed_stripe_data.py --seed 42
```

Same seed produces the same customer status distribution every time.

### Expected Output

```
======================================================================
STRIPE TEST DATA SEEDING SUMMARY
======================================================================
Seeded 75 customers
  Active:    52 (69%)
  Canceled:  15 (20%)
  Past Due:  8 (11%)

Date range: Dec 07, 2025 – Jun 06, 2026
Test clocks created: 25
Errors encountered: 0
======================================================================
```

### Cleanup

After testing, delete the created test clocks:

```bash
python seed_stripe_data.py --cleanup
```

This will prompt for confirmation before deleting clocks matching the pattern `mrr-seed-clock-*`.

### Testing

Run the comprehensive test suite:

```bash
cd scripts
python -m pytest tests/ -v
```

Tests include:
- API key validation (rejecting live keys)
- Clock allocation and limits enforcement
- Status distribution accuracy
- Rate limit retry logic
- Idempotency and deduplication
- Polling timeouts
- Invoice coverage verification
- Payment failure handling for Past Due subscriptions

### Architecture

The script is organized into focused modules for maintainability and testability:

- **`seed_stripe_data.py`** — CLI entry point and orchestration logic
- **`stripe_seeder/config.py`** — Environment variable loading and validation
- **`stripe_seeder/clock_manager.py`** — Stripe Test Clock lifecycle management
- **`stripe_seeder/customer_factory.py`** — Customer and subscription creation with rate-limit handling
- **`stripe_seeder/summary.py`** — Formatted summary output
- **`stripe_seeder/errors.py`** — Custom exception types

### Troubleshooting

#### Rate Limit Errors

The script automatically retries on rate limits with exponential backoff (1s, 2s, 4s, 8s, 16s). If you still see rate limit errors:

- Reduce `--num-customers` (e.g., 50 instead of 100)
- Increase time between runs
- Use a higher API rate limit tier in your Stripe account

#### Clock Timeout Errors

If a test clock fails to reach 'ready' status within 30 seconds:

- Check your internet connection
- Verify the Stripe API key is valid
- Retry the script; this is often transient

#### Live Key Detection

The script **only works with test API keys** (format: `sk_test_*`). It will abort if you provide a live key (`sk_live_*`), protecting your production data.

---

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
