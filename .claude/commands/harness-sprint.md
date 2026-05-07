---
description: Run a single sprint cycle — contract negotiation, implementation, evaluation, and iteration up to the per-sprint cap. In end-to-end mode, runs one full build/QA round.
argument-hint: [--sprint <NN>] [--max-iterations <N>]
---

# /harness-sprint — execute one sprint cycle

Argument string: `$ARGUMENTS`

## What this command does

1. **Read state** from `.harness/state.json`:
   - If missing → tell user to run `/harness-init` first; halt.
   - If `phase == "escalated"` → tell user to read `.harness/escalations/sprint-NN-escalation.md` and decide before continuing.
   - Pick `current_sprint` (or honor `--sprint NN` if passed).

2. **Per-sprint mode flow:**
   1. **Contract negotiation:**
      - Invoke the Generator (`subagent_type: generator`) with the sprint number; instruct it to write Round 1 of the contract at `.harness/contracts/sprint-NN-contract.md`.
      - Invoke the Evaluator (`subagent_type: evaluator`) with the same sprint number; instruct it to review the contract and write its responses inline.
      - Loop until both write an `Agreement` block. Aim for 1–3 rounds.
   2. **Implementation:**
      - Invoke the Generator to implement against the agreed contract.
      - The Generator commits per sprint, starts dev servers, writes the handoff at `.harness/handoffs/sprint-NN-handoff.md`.
   3. **Evaluation:**
      - Invoke the Evaluator (separate invocation, ALWAYS) to read the handoff, exercise the running app via Playwright, and write `.harness/evaluations/sprint-NN-evaluation.md`.
   4. **Verdict:**
      - **Pass** → update state (`current_sprint += 1`, `current_iteration = 0`), commit, return summary.
      - **Iterate** → if `current_iteration < iteration_cap_per_sprint`: invoke Generator again with the failing criteria; loop back to step 3.
      - **Cap hit** → invoke Generator to write the escalation file; set state `phase: "escalated"`; halt and notify user.

3. **End-to-end mode flow:**
   - Step 1 contract negotiation covers the whole spec (one contract).
   - Generator implements the entire spec.
   - Evaluator runs full QA.
   - Up to 5 build/QA rounds; same escalation rule.

4. **Always print** at the end:
   - Sprint number, iteration count, verdict.
   - Per-criterion pass/fail summary (counts).
   - Next action (`/harness-sprint` for next sprint, `/harness-resume` after manual intervention, `/harness-status` to inspect).

## Guardrails

- Generator and Evaluator MUST be SEPARATE Task invocations. Never combine.
- If Playwright MCP is missing, halt with install instructions.
- If the dev server isn't reachable from the handoff URLs, restart it (Bash) before evaluating; do not score "fail" on infra.
- Honor `--max-iterations N` to override the default (15 per-sprint, 5 end-to-end) for this run only.
