# Sprint {{NN}} Contract — {{Sprint Name}}

> **Purpose:** bridge the gap between the spec's user stories and concrete, testable behaviors that both the Generator and Evaluator can reason about.
> Negotiated *before* any code is written for this sprint.
> Both agents use this exact contract — no moving goalposts during evaluation.

---

## 1. Scope

**In scope:**
- {{bullet — what this sprint builds}}
- ...

**Explicitly out of scope (deferred to later sprints):**
- {{bullet}}
- ...

## 2. Definition of Done

A short paragraph describing what the user can do at the end of this sprint that they couldn't do before. Concrete enough that anyone reading it knows whether the sprint shipped.

## 3. Affected Surfaces

| Layer | Files / paths | Net new vs change |
|---|---|---|
| Frontend | {{e.g. `src/views/BoardView.tsx`, `src/store/boardStore.ts`}} | new + modify |
| Backend | {{e.g. `routes/cards.py`, `ws/board.py`}} | new + modify |
| Database | {{e.g. add `position` column to `cards`}} | migration |
| Tests | {{e.g. `tests/test_card_reorder.py`, `boardStore.test.ts`}} | new |

## 4. Testable Criteria (target: 15–30)

> Each criterion is a single observable behavior. Verification method must be concrete enough for the Evaluator to execute via Playwright, API call, DB query, or file inspection.
> Mark **criticality** as `must` (sprint fails if this fails) or `should` (degrades score but not blocking).

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-1 | {{User can drag a card to a new position within the same column}} | Playwright: drag-drop, assert DOM order | must |
| C-2 | {{Reorder persists after page reload}} | Playwright: reload, assert DOM order matches API response | must |
| C-3 | {{Server returns 200 with new positions array on PATCH /cards/reorder}} | curl + assert JSON shape | must |
| C-4 | {{Optimistic update is rolled back if server returns non-2xx}} | Playwright with intercept: respond 500, assert UI reverts within 200ms | must |
| C-5 | {{...}} | {{...}} | should |
| ... | ... | ... | ... |

## 5. Negotiation Log

> Captured inline. Generator proposes; Evaluator pushes back; iterate until both agree.

### Round 1 — Generator proposes (timestamp: {{ISO}})
- {{summary of proposal}}

### Round 1 — Evaluator review (timestamp: {{ISO}})
- **Accept:** {{C-1, C-2, C-3}}
- **Reject — too vague:** {{"app should feel snappy" → quantify: "drag→drop visual feedback within 16ms (one frame at 60fps)"}}
- **Reject — wrong scope:** {{"add user permissions" — defer to a later sprint, not in spec for this one}}
- **Add:** {{C-X — keyboard reorder for accessibility}}, {{C-Y — concurrent-move conflict resolution}}

### Round 2 — Generator revised (timestamp: {{ISO}})
- {{addressed feedback}}

### Round N — Agreement (timestamp: {{ISO}})
- Both agents acknowledge the criteria above as the definitive contract for this sprint.

## 6. Threshold Applied

- **Per-criterion threshold:** {{e.g. 7/10}} (from `.claude/skills/grading-rubric/SKILL.md`; override here if needed and justify)
- **Iteration cap:** {{e.g. 15}}
- **Escalation behavior:** at cap, the Generator writes `.harness/escalations/sprint-{{NN}}-escalation.md` summarizing failing criteria, last attempt, and Evaluator's most recent findings — the run halts for the user.

## 7. Rubric Selection

- [ ] Frontend rubric (UI-primary work)
- [ ] Full-stack rubric (full app work)
- [ ] Add Design Fidelity criterion (Figma source present — frame mappings below)

### Figma Frame Mappings (when applicable)

| Surface | Figma frame id / name | Notes |
|---|---|---|
| {{BoardView}} | {{12:34 — "Board / Default"}} | {{...}} |
