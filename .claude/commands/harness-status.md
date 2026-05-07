---
description: Show the current state of an active harness run — sprint, iteration, last evaluator scores, next action. Read-only.
---

# /harness-status — inspect the active harness run

## What this command does

Read-only summary. Touches no state.

1. **Read `.harness/state.json`.** If missing → "No active run. Use `/harness-init` to start."

2. **Print:**

   ```
   Mode:                <per-sprint | end-to-end>
   Phase:               <spec-complete | contract-negotiating | implementing | evaluating | iterating | escalated | done>
   Current sprint:      <NN>
   Current iteration:   <M> / <cap>
   Threshold:           <T>/10 per criterion
   Started:             <ISO timestamp>
   Spec:                .harness/plans/spec.md
   Figma source:        <path | url | none>
   ```

3. **Latest contract** (`.harness/contracts/sprint-NN-contract.md` for current sprint):
   - Number of criteria.
   - Last round number.
   - Whether `Agreement` block is present.

4. **Latest evaluation** (`.harness/evaluations/sprint-NN-evaluation.md` for current sprint, latest iteration):
   - Aggregate verdict (Pass / Iterate / —).
   - Per-criterion: pass count / fail count.
   - Failing criteria IDs (must vs should).
   - Strategic note's refine/pivot recommendation.

5. **Next action** suggestion:
   - If contract is mid-negotiation → "Run `/harness-sprint` to continue contract negotiation."
   - If implementing → "Generator is working; check `git log` and `.harness/handoffs/` for progress."
   - If evaluation pending → "Run `/harness-sprint` to invoke the Evaluator."
   - If iterate → "Run `/harness-sprint` to start iteration <M+1>."
   - If escalated → "Read `.harness/escalations/sprint-NN-escalation.md`; choose to relax the contract, intervene manually, or `/harness-resume --skip-sprint`."
   - If all sprints done → "Run is complete. Review the spec at `.harness/plans/spec.md` and final commits via `git log`."

6. **Recent activity** (last 5 commits in the project, last 5 files written under `.harness/`).
