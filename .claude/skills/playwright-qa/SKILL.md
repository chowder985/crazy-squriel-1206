---
name: playwright-qa
description: How the Evaluator drives the Playwright MCP to actually exercise a running app — not just screenshot it. Edge cases, probing patterns, network interception, DB inspection, and the anti-patterns that produce false-positive evaluations.
---

# Playwright QA

> Out of the box, Claude tests superficially: navigate, take a screenshot, declare success. That produces false positives. This skill exists to push the Evaluator into the kind of probing a skeptical QA engineer would do — multiple paths per criterion, edge cases, network-and-DB inspection, not just visual.

---

## Prerequisites

- Playwright MCP must be installed in the user's MCP config:
  ```
  claude mcp add playwright npx @playwright/mcp@latest
  ```
- The Generator's handoff file (`.harness/handoffs/sprint-NN-handoff.md`) tells you where the app is running. Read it first. If the URLs are unreachable, restart the dev server yourself via Bash before evaluating — do not score "fail" because the server is down.

---

## Per-Criterion Exercise Pattern

For **every** criterion, the Evaluator must run **at least two paths**:

1. **Happy path** — the obvious successful flow.
2. **At least one edge** — pick from: empty state, error state, network failure, concurrent action, refresh mid-flow, unauthenticated access, very large input, very small input (0/1 items), keyboard-only, slow connection.

Single-happy-path testing is the #1 reason superficial bugs survive QA. The article's level-editor sprint surfaced bugs like the `LevelEditor.tsx:892` delete handler exactly because the Evaluator probed beyond the happy path.

---

## What "substantive Playwright" looks like

Concrete browser actions, in this order, for a typical UI criterion:

1. **Navigate** to the surface (`browser_navigate`).
2. **Snapshot** the accessibility tree (`browser_snapshot`) to see what's actually rendered — do not rely on screenshots alone.
3. **Locate** the target element by accessible role/name when possible, by text or test id otherwise.
4. **Act** — click, type, drag, key-press.
5. **Assert** by re-snapshotting and reading the new state. Check both the DOM and any visible feedback.
6. **Verify the side-effects:**
   - **Network:** read network log (`browser_network_requests`); confirm expected endpoint was called with expected payload and returned expected status.
   - **DB:** call a read endpoint or query the SQLite file directly via Bash (e.g., `sqlite3 .harness/data/app.db "SELECT * FROM cards WHERE id=?;"`).
7. **Screenshot** for evidence — save to `.harness/evaluations/screenshots/sprint-NN-criterion-id-step.png`. Screenshots are *evidence*, not the assertion.

---

## Edge-case probing recipes

### Network failure / 5xx
- Use `browser_network_request` or route-intercept patterns to make a specific endpoint return 500 (or hang).
- Verify the UI shows an error state (not a silent failure or a stuck spinner).
- Verify state is consistent — no half-applied optimistic mutations left over.

### Concurrent actions
- Open a second tab (`browser_tabs`).
- Perform conflicting actions in both tabs (e.g., reorder the same list).
- Verify both tabs converge to the same state — usually via websocket broadcast.

### Refresh mid-flow
- Start a multi-step flow, complete N-1 of N steps.
- Reload (`browser_navigate` to the same URL).
- Verify the user lands somewhere coherent (resume the flow, or land at a clean entry — not a broken half-state).

### Unauthenticated access
- Clear cookies / localStorage.
- Try to access a protected route directly.
- Verify redirect to login (not a leaked page or a 500).

### Empty / 0-item / 1-item states
- Seed the DB to be empty (delete all rows for the relevant table) before navigating.
- Verify a real empty state with a call-to-action — not a blank screen.
- Repeat with exactly 1 item — boundary often hides bugs (pagination off-by-one, "1 items" string).

### Keyboard-only path
- For any new interaction, attempt to complete it with `browser_press_key` only — no mouse.
- Verify focus order, that focus is visible, and that the action completes.

### Very large input
- For text fields without an obvious cap, type a 5,000-char string.
- For lists, seed the DB with 1,000+ items (via API or directly).
- Verify the UI doesn't freeze and the API doesn't 500.

---

## API-level probes

The Evaluator should not test only through the UI. For each backend endpoint touched by the sprint:

- **Schema check:** call with valid payload; assert response status and JSON shape.
- **Validation check:** call with missing required fields, wrong types, oversized values; assert 4xx with a useful error message (not 500).
- **Auth check:** call without auth; assert 401/403.
- **Idempotency / re-entry:** for PUT/PATCH/DELETE, call twice in a row; assert sensible behavior (not a 500 on the second call).
- **Race:** fire two of the same request in parallel; verify final DB state is consistent.

Use Bash with `curl` for ad-hoc; the network-request tools are fine for in-browser flows.

---

## DB-level probes

Don't trust UI-displayed state alone — verify the database.

- For SQLite (default stack): `sqlite3 path/to/db "SELECT ..."` via Bash.
- For Postgres: psql, or query a debug endpoint if the app exposes one.
- Specifically verify: row count, foreign key integrity, expected column values after the action, no orphan rows.

---

## Anti-patterns (the Evaluator must avoid these)

- **Screenshot-only.** "Looks like the button is there." → Click it. Verify the side-effect.
- **Single happy path.** "I dragged a card and it moved." → Now drag with a network failure, drag from another tab, drag with keyboard.
- **Trusting the UI.** "The card disappeared from the list." → Query the DB. Verify it's actually deleted, not just hidden.
- **Skipping the API.** "The form submitted." → Confirm the request was made with the expected payload and the response was processed.
- **Saying "passes" without exercising.** Every "PASS" must cite the specific Playwright steps that produced it.

---

## Reporting back

When a criterion fails, the bug report must include:

- **Symptom** in plain language (what the user would see / experience).
- **Reproduction** — exact Playwright steps that surfaced it.
- **Root cause guess** with file:line — e.g., `boardStore.ts:142`. Read the source if needed; do not guess.
- **Severity** — does this make the feature unusable, degrade it, or just look wrong.
- **Recommendation** — what to change. Be specific enough that the Generator can act without re-investigating.

Model the report shape on the article's example:

> **Delete key handler at `LevelEditor.tsx:892` requires both `selection` and `selectedEntityId` to be set, but clicking an entity only sets `selectedEntityId`. Condition should be `selection || (selectedEntityId && activeLayer === 'entity')`.**
