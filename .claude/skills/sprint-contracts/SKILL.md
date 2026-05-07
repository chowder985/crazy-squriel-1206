---
name: sprint-contracts
description: How the Generator and Evaluator negotiate a sprint contract before any code is written. Defines criterion quality, the negotiation protocol, and what counts as "testable." Loaded by both agents at the start of every sprint in per-sprint mode.
---

# Sprint Contracts

> **What this exists for:** to bridge the gap between the spec's user stories and concrete, testable behaviors. The spec stays high-level on purpose — the contract is where that vagueness gets turned into the things the Generator will actually build and the Evaluator will actually verify.
> Reference point from the original harness: a single sprint had **27 criteria** covering a level editor. That granularity is the target, not 5 vague checkboxes.

---

## When to use

- **Per-sprint mode:** every sprint starts with a contract negotiation.
- **End-to-end mode:** one contract at the start covering the whole spec; the QA round scores against it.

---

## The Three Roles a Contract Plays

1. **Scope agreement.** What this sprint includes and (just as important) what it does not.
2. **Done definition.** What the user can do at the end of the sprint that they couldn't do before.
3. **Verification map.** A list of 15–30 specific behaviors with a verification method for each. The Evaluator will use exactly this list to score — no new criteria invented later, no criteria silently dropped.

---

## Criterion Quality — what counts as "testable"

A criterion is testable if a different agent, reading only the criterion text and the running app, can verify it without inventing context.

### Good criterion shape

> **C-N | Behavior | Verification | Criticality**

- **Behavior** is a single observable thing the user, browser, API, or DB does. One verb, one subject, one outcome.
- **Verification** is the concrete method: Playwright steps, an API call with expected status + JSON shape, a DB query with expected row count, a file inspection.
- **Criticality** is `must` (sprint fails if this fails) or `should` (degrades score, not blocking).

### Examples — testable

- *C-1 | User can drag a card to a new position within the same column | Playwright: locate card by text, drag to position 0, assert DOM order in column container | must*
- *C-2 | Reorder persists after page reload | Playwright: reload page, assert DOM order matches the order before reload | must*
- *C-3 | PATCH /cards/reorder returns 200 with `{positions: [{id, position}]}` | curl with valid payload; assert HTTP status and JSON shape | must*
- *C-4 | Optimistic update is rolled back if server returns non-2xx | Playwright with route intercept: respond 500; assert UI reverts within 200ms | must*

### Examples — NOT testable (rewrite before agreeing)

- *"App feels snappy"* → quantify: "drag→drop visual feedback within 16ms"
- *"Drag and drop works"* → too coarse; split into 4–6 sub-criteria for the actual flows
- *"User can manage cards"* → "manage" hides 5+ behaviors; list each
- *"AI-powered suggestions are useful"* → "useful" is unmeasurable; specify "given input X, the model returns at least N suggestions and the user can accept one"
- *"Error handling is robust"* → enumerate the error paths

---

## The Negotiation Protocol

The Generator proposes; the Evaluator pushes back; they iterate. Aim for 1–3 rounds. Both write inline into the same `sprint-NN-contract.md` file using the structure in `templates/contract-template.md`.

### Round 1 — Generator proposal

The Generator drafts:
- Scope (in/out)
- Done definition
- 15–30 candidate criteria
- Affected surfaces (files/paths)
- Rubric selection

### Round 1 — Evaluator review

For each candidate criterion the Evaluator answers:

- **Accept** as-is, or
- **Reject — too vague** (and rewrite to be testable), or
- **Reject — wrong scope** (defer to a later sprint, or split off into a separate one), or
- **Reject — duplicate** (collapse into another criterion), or
- **Add** (a behavior the Generator missed — common: empty/error/loading states, accessibility, edge cases like concurrent users or refresh-mid-flow).

The Evaluator should also evaluate the *count* — fewer than 15 criteria for a non-trivial sprint usually means the spec is being skimmed.

### Round 2+ — Generator revises

Address each rejection. Ask if anything is unclear. Propose alternatives where the Evaluator's pushback is hard to apply.

### Final — Agreement

Both agents write a concluding `Agreement` block. From this point, the criteria list is frozen for the sprint. Neither agent may add criteria mid-implementation or drop them mid-evaluation. New things discovered mid-sprint go into the next sprint's contract.

---

## What the Evaluator should always push back on

- **Missing edge cases.** Concurrent users, refresh during a multi-step flow, network failure mid-request, unauthenticated access, very large inputs, very small inputs (0 items, 1 item).
- **Missing states.** Loading, empty, error, success, disabled. If a UI surface exists, it has at least 3 of these.
- **Missing accessibility.** Keyboard reachability of any new interaction; ARIA labels on icon-only buttons; visible focus.
- **Missing AI-feature realism.** If the spec calls for an AI feature, the contract must verify the model is actually called (intercept the request, assert payload shape) — not that some text appears on screen.
- **Missing persistence verification.** If the user creates / edits / deletes something, verify both that the DB state changed and that a reload preserves it.

---

## Existing-Codebase Mode — extra criteria the Evaluator should add

- **Convention conformance.** A `must` criterion: "new files match existing naming/layout patterns" with verification "diff against tree structure conventions."
- **No regression.** A `must` criterion: "existing tests still pass" with verification "run the existing test command."
- **No new dependencies without justification.** Either the contract names new deps or it forbids them.

---

## Figma Mode — extra criteria

- For each Figma frame in scope: "Implementation of `<frame name>` matches frame at the pixel level (Design Fidelity rubric F1 applies)."
- "All token references use the design tokens declared in the spec; no inline hex."
- "All component states defined in Figma (hover, focus, disabled, etc.) are implemented."

---

## Why granularity matters (don't skip this)

Coarse criteria let the Evaluator round up — "the feature works, 8/10" — even when half the cases are broken. The article's level-editor sprint had 27 criteria precisely because granularity prevents that smoothing. If you're tempted to write fewer than 15 for a real sprint, you're probably hiding work the Generator will skip and the Evaluator won't catch.
