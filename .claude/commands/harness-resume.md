---
description: Resume an interrupted harness run. Reads .harness/state.json, determines where the run was interrupted, and continues from there.
argument-hint: [--skip-sprint] [--reset-iteration]
---

# /harness-resume — pick up where the harness left off

Argument string: `$ARGUMENTS`

## What this command does

1. **Read `.harness/state.json`.** If missing → tell user to run `/harness-init`; halt.

2. **Determine resume point** by reading the most recent files:
   - If `phase == "spec-complete"` and no contract for `current_sprint` exists → start contract negotiation (Generator → Evaluator).
   - If a contract exists with no `Agreement` block → resume contract negotiation from the last round.
   - If contract is agreed but no handoff exists → invoke Generator to implement.
   - If a handoff exists but no evaluation for the current iteration → invoke Evaluator to grade.
   - If an evaluation exists with `Iterate` and `current_iteration < cap` → invoke Generator with the failing criteria.
   - If `phase == "escalated"` → tell the user to read the escalation file; do NOT auto-resume.

3. **Honor flags:**
   - `--skip-sprint` — advance `current_sprint` without trying to satisfy the current one. Useful when the user manually fixed things and wants to move on. Records the skip in state.
   - `--reset-iteration` — reset `current_iteration` to 0 for the current sprint (e.g., after the user manually changed code or relaxed the contract).

4. **Print resume summary** before invoking anything: where the harness picked up, what it's about to do, what files it consulted to decide.

## Guardrails

- Never silently overwrite an evaluation file. If one exists for the same iteration, keep it and increment.
- If the working tree has uncommitted changes the user didn't make manually (e.g., a Generator interrupted mid-write), surface a diff and ask before continuing.
- Same agent-separation rule: Generator and Evaluator are SEPARATE invocations.
