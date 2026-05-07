# Sprint {{NN}} Evaluation — {{Sprint Name}}

> Written by the **Evaluator agent** after exercising the running app via Playwright MCP.
> Be skeptical. Score each criterion against the per-criterion threshold from `.claude/skills/grading-rubric/SKILL.md`.
> **Do NOT** identify a real issue and then talk yourself into approving it anyway.

---

## Run Context

- **Mode:** {{per-sprint | end-to-end-round-N}}
- **Iteration:** {{N of 15}}
- **App URLs (from Generator handoff):**
  - Frontend: {{http://localhost:5173}}
  - Backend: {{http://localhost:8000}}
- **Database state:** {{path or connection note}}
- **Figma source (if any):** {{file URL or `.harness/figma/` dir}}
- **Rubric in effect:** {{frontend | full-stack | + Design Fidelity}}
- **Per-criterion threshold:** {{7 / 10}}
- **Started:** {{ISO timestamp}}
- **Finished:** {{ISO timestamp}}

---

## Per-Criterion Scores

> One block per criterion from the contract. Each block must include: score, pass/fail vs threshold, what was actually exercised, and a specific bug report if failing.

### C-1 — {{behavior text from contract}}

- **Score:** {{8}}/10 — **PASS** (threshold {{7}})
- **Verification performed:** {{Playwright steps in concrete language: navigated to /board, dragged card "Buy milk" from column "Todo" to position 1 in column "Doing", asserted DOM order matches}}
- **Evidence:** {{screenshots saved to .harness/evaluations/screenshots/sprint-NN-c1-*.png; network log excerpt; DB query result}}
- **Notes:** {{}}

### C-4 — {{Optimistic update is rolled back if server returns non-2xx}}

- **Score:** {{4}}/10 — **FAIL** (threshold {{7}})
- **Verification performed:** {{Used Playwright route intercept to make PATCH /cards/reorder return 500. Dragged card. UI showed card in new position for ~3 seconds, then reverted only after a manual refresh.}}
- **Bug report:**
  > **Optimistic rollback does not occur on server failure.**
  > `boardStore.ts:142` — `applyLocalMove` mutates state but stores no `revertSnapshot`. The catch block at `:171` calls `refetch()` instead of restoring previous state, so users see the wrong order until the network round-trip completes (~700ms in test). Should snapshot the prior `cards` array before applying and restore on rejection.
- **Recommendation:** Snapshot-and-restore pattern; add a Vitest unit test exercising the rejection branch.

### C-N — {{...}}

- **Score:** ...

---

## Aggregate Verdict

- **Criteria evaluated:** {{N}}
- **Pass:** {{x}} / {{N}}
- **Fail:** {{y}} / {{N}}
- **Failing criteria (must-criticality):** {{C-4, C-9}}
- **Failing criteria (should-criticality):** {{C-12}}

**Sprint outcome:** one of:
- [ ] **Pass** — all `must` criteria meet threshold; sprint accepted; advance to next sprint.
- [ ] **Iterate** — at least one criterion below threshold; iteration {{N}} of 15. Generator must address the failing items.
- [ ] **Escalate** — iteration cap reached. Generator writes escalation file; run halts for user.

---

## Strategic Note to Generator (when iterating)

> Brief, opinionated guidance. Should the Generator refine the current direction or pivot?

- **Direction:** {{refine | pivot}}
- **Why:** {{2–3 sentences. e.g. "The race condition in C-4 is local to the optimistic path; the rest of the implementation is sound. Refine — fix the rollback and re-verify."}}

---

## Design Fidelity (when Figma source present)

> Specific deltas, not "looks close." Each deviation must include a measured difference.

| Surface | Figma frame | Deviation | Measured delta | Severity |
|---|---|---|---|---|
| {{BoardView header}} | {{12:34}} | Title font size | Implemented `1.25rem` (20px); Figma `1.5rem` (24px) | high |
| {{Card hover state}} | {{12:50}} | Missing | Hover not implemented; Figma defines `bg=#F5F5F5, scale=1.02` | high |
| {{Board padding}} | {{12:34}} | Spacing too tight | Implemented `16px`; Figma `24px` (>4px delta) | medium |

**Design Fidelity score:** {{6}}/10 — **FAIL** (threshold {{7}})

---

## Evaluator Self-Check (anti-talking-yourself-out-of-issues)

Before submitting this evaluation, the Evaluator must answer YES to all:

- [ ] Did I run more than one Playwright path per criterion (happy + at least one edge)?
- [ ] Did I check API responses AND database state, not just visual output?
- [ ] Did I file every issue I found, even minor ones, instead of "rounding up" the score?
- [ ] Are all bug reports file:line specific?
- [ ] Did I score originality / design quality strictly, not generously?
