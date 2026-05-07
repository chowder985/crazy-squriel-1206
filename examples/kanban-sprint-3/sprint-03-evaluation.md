# Sprint 03 Evaluation (iteration 1) — Evaluator → Generator

> Worked example. This is what the Evaluator writes to `.harness/evaluations/sprint-03-evaluation.md` after exercising the running app via Playwright.

---

## Run Context

- **Mode:** per-sprint
- **Iteration:** 1 of 15
- **App URLs:** Frontend http://localhost:5173, Backend http://localhost:8000
- **Database state:** seeded via `python -m backend.scripts.seed_demo` before each criterion's runs
- **Figma source:** none (Design Fidelity criterion does not apply)
- **Rubric in effect:** full-stack
- **Per-criterion threshold:** 7/10
- **Started:** 2026-05-06T23:14:02Z
- **Finished:** 2026-05-07T00:06:51Z

---

## Per-Criterion Scores (22 criteria)

### C-1 — Drag within column

- **Score:** 9/10 — **PASS**
- **Verification:** Logged in as Alice. Navigated to /board. Dragged "Ship onboarding" from index 2 of "In Progress" to index 0. Snapshot confirms new DOM order. Repeated three times in succession; no glitches.
- **Evidence:** screenshots `sprint-03-c1-{1,2,3}.png`; network log shows three PATCH /api/v1/cards/reorder calls with correct payloads.
- **Notes:** Animation is buttery; design language ("180ms cubic-bezier") is honored.

### C-2 — Drag across columns

- **Score:** 9/10 — **PASS**
- **Verification:** Dragged "Write RFC" from "Todo" → "In Progress" → "Done" → back to "Todo". Each move correctly persisted; column membership matches the column's `cards` association in the DB (verified via `sqlite3 driftboard.db "SELECT id, column_id, position FROM cards WHERE id=42;"`).

### C-3 — Drag visual feedback within 16ms

- **Score:** 8/10 — **PASS**
- **Verification:** Injected `performance.now()` instrumentation; measured average 9.4ms across 10 trials, max 14.8ms. Ghost element renders on the first frame.
- **Notes:** Solid. One trial spiked to 22ms when DevTools was open, but that's expected — outside test conditions.

### C-4 — Reorder persists after reload

- **Score:** 9/10 — **PASS**
- **Verification:** Performed three moves, hard-reloaded `/board`. DOM order matches the order from before the reload. DB rows confirm via direct query.

### C-5 — PATCH endpoint shape

- **Score:** 10/10 — **PASS**
- **Verification:** `curl -X PATCH http://localhost:8000/api/v1/cards/reorder -H "Cookie: ..." -d '...'` returns 200 with `{cards: [{id, column_id, position}]}`. Tried five payloads with varying counts; all returned consistent shape.

### C-6 — DB row count invariant

- **Score:** 10/10 — **PASS**
- **Verification:** `SELECT COUNT(*) FROM cards;` before and after 20 sequential reorders. Row count: 8 → 8. No silent inserts.

### C-7 — Optimistic update is immediate

- **Score:** 9/10 — **PASS**
- **Verification:** Used Playwright route delay of 1000ms on `/cards/reorder`. UI updated within 24ms of mouseup (well under the 50ms criterion). Server response did not arrive until ~1010ms later; no UI flicker.

### C-8 — Rollback on server failure

- **Score:** **3/10** — **FAIL** (threshold 7)
- **Verification:** Used Playwright route intercept to make `PATCH /api/v1/cards/reorder` return 500. Dragged "Refactor pipeline" from index 0 to index 4 in "In Progress".
  - **Observed:** UI moved card to index 4 immediately. ~870ms later (after the 500 came back), the card briefly flickered, ended up at **index 1** (not its original index 0), and **no inline notice appeared**. A second drag in this window left the board in an inconsistent state visible in the second tab.
- **Bug report:**
  > **Optimistic rollback is not snapshot-restoring; it's recomputing from a stale derived state.**
  > `boardStore.ts:171` — `rollbackMove(opId)` reads `cards` directly from the current store and tries to "undo" by inserting the card back at `pendingOps[opId].fromIndex`. But if a remote `applyRemoteMove` from the WebSocket fired between `applyLocalMove` and the rollback, the indices have shifted, so the card lands wrong. The snapshot stored in `pendingOps[opId].snapshot` (created by `applyLocalMove` at line 142) is never read back.
  > Additionally, the inline notice path is unreachable: the catch-block at `BoardView.tsx:218` calls `rollbackMove(opId)` but never sets `lastAnnouncement` or shows the "Couldn't save — restored" string referenced in the spec design language.
  > Recommendation: in `rollbackMove`, replace the in-place patch with `setState({cards: pendingOps[opId].snapshot})`. Then in `BoardView.tsx:218`, on rollback, set `lastAnnouncement` and dispatch a non-blocking inline notice (the spec specifies inline, not toast).

### C-9 — Broadcast within 250ms

- **Score:** 8/10 — **PASS**
- **Verification:** Two tabs, both logged in as Alice. Drag in tab A; tab B reflects within 132ms (timed via `performance.now()` injection on the WebSocket message handler).

### C-10 — Concurrent moves converge

- **Score:** **5/10** — **FAIL** (threshold 7)
- **Verification:** Tab A (Alice) moved card X from "Todo" to "In Progress". Tab B (Bob) simultaneously moved card Y from "In Progress" to "Done". Final state:
  - Server DB: matches A's last write (correct under last-write-wins rules).
  - Tab A: shows correct state.
  - Tab B: shows X in original "Todo" position; Bob's move was visually accepted but the broadcast for A's move overwrote tab B's optimistic state for X (acceptable) AND silently undid Bob's move for Y (NOT acceptable — Bob's move was never broadcast back to him because of `pendingOps` dedup).
- **Bug report:**
  > **Client-side broadcast deduplication is overly aggressive.**
  > `useBoardSocket.ts` — `applyRemoteMove` skips any incoming event whose `opId` is in `pendingOps`. But it should ONLY skip the event whose `opId` matches the local pending op for the *same card*. Currently any pending op for any card causes the entire incoming reorder snapshot to be skipped, which silently drops other users' moves.
  > Recommendation: scope the dedup check by `cardId`, not by the presence of any pending op. Or switch to per-card opId tracking and reconcile by full server snapshot on broadcast (simpler, costs a re-render).

### C-11 — Versioned `v1` payload

- **Score:** 9/10 — **PASS**
- **Verification:** All endpoints under `/api/v1/`; payload bodies use the v1 envelope.

### C-12 — Keyboard reorder

- **Score:** 7/10 — **PASS** (just at threshold)
- **Verification:** Tab to card, Space to grab (verified via `aria-grabbed=true`), arrow keys move (DOM order updates), Space drops. Worked.
- **Caveat:** Esc-to-cancel was implemented but does not restore the focused card to its original position — it just exits grab mode with the card in its current position. Spec doesn't require Esc-restore explicitly so I'm not failing it, but it's worth tightening for Sprint 3.5 polish.

### C-13 — Drag handle accessible name

- **Score:** 8/10 — **PASS**
- **Verification:** Snapshot of accessibility tree shows `[name="Drag card: Ship onboarding"]` on each handle.

### C-14 — Live region announcement

- **Score:** **6/10** — **FAIL** (threshold 7)
- **Verification:** Performed a move with VoiceOver-equivalent monitoring of the aria-live region.
  - **Observed:** Region updates with the string but the timing is wrong — announcement fires on `applyLocalMove` (immediate) rather than on `commitMove`, so a failed move that gets rolled back still announces the move as successful.
- **Bug report:**
  > **Live announcement fires before server confirmation.**
  > `boardStore.ts:147` — `applyLocalMove` sets `lastAnnouncement = "Moved <title>..."`. This means the screen reader hears "Moved" even when the move later rolls back, leaving the user with an incorrect mental model.
  > Recommendation: defer the announcement to `commitMove` (so it fires only after server success). On rollback, set `lastAnnouncement = "Couldn't save move; restored"`.

### C-15 — Reduced-motion snap

- **Score:** 9/10 — **PASS**
- **Verification:** Set `prefers-reduced-motion: reduce`; computed style on card transition is `0s`.

### C-16 — Empty-column drop hover state

- **Score:** 8/10 — **PASS**
- **Verification:** Cleared "Done" column; dragged "Refactor pipeline" over it. Drop zone showed accent border (`#5B6CFF`) per design language.

### C-17 — Drop on same position is a no-op

- **Score:** 10/10 — **PASS**
- **Verification:** Dragged and dropped in the same spot. Network log shows zero `/cards/reorder` requests. Verified by intercepting all PATCH calls.

### C-18 — Unauthenticated PATCH returns 401

- **Score:** 10/10 — **PASS**
- **Verification:** `curl -X PATCH http://localhost:8000/api/v1/cards/reorder -d '{}'` (no cookie) returns `401 {"detail":"Not authenticated"}`.

### C-19 — Malformed payload returns 422

- **Score:** 10/10 — **PASS**
- **Verification:** `curl` with body `{"cards":[{"id":1}]}` (missing `position`, `column_id`) returns `422` with `detail` array citing both fields.

### C-20 — WebSocket auto-reconnect

- **Score:** 8/10 — **PASS**
- **Verification:** Killed backend (`pkill uvicorn`), waited 3s, restarted. Frontend reconnected after 4.2s (exponential backoff: 1s, 2s, 4s). Triggered a board refetch on reconnect — state matches server.

### C-21 — Migration idempotency

- **Score:** 10/10 — **PASS**
- **Verification:** Ran the migration twice consecutively; the second run reported "No changes" and exited 0.

### C-22 — Existing tests still pass

- **Score:** **0/10** — **FAIL** (threshold 7)
- **Verification:** `pytest backend/tests/` reports 2 failures.
- **Bug report:**
  > **Existing test `test_card_create_returns_full_card` now fails.**
  > `backend/tests/test_cards.py:48` — the test asserts the create-card response shape includes specific keys, but the new `position` field added in this sprint isn't in the asserted set, AND the existing fixture `default_card_payload` doesn't supply a `position` so creates default to `0` colliding with existing rows. Two failures: assertion mismatch + integrity error on second create.
  > `backend/tests/test_columns.py:91` — fails because `Column` rendering now includes ordered-by-position joins, which broke the existing `test_columns_list_alphabetical` ordering assumption.
  > Recommendation: update `test_cards.py:48` to include `position` in the expected keys; update the create-card route to default `position = MAX(position) + 1 WHERE column_id = ?` rather than hardcoded `0`; update `test_columns_list_alphabetical` to either re-seed deterministically or change the assertion to "by-position" (since alphabetical was incidental to seed order).

---

## Aggregate Verdict

- **Criteria evaluated:** 22
- **Pass:** 18 / 22
- **Fail:** 4 / 22
- **Failing criteria (must):** C-8, C-10, C-22
- **Failing criteria (should):** C-14

**Sprint outcome:** **Iterate** (3 `must` criteria below threshold; 11 of the 15 iterations remain).

---

## Strategic Note to Generator

- **Direction:** **refine** (not pivot).
- **Why:** Eighteen of twenty-two criteria pass at strong scores. The four failures cluster around two real but localized defects: (1) `boardStore.ts` rollback path doesn't actually use the snapshot it stores (which causes both C-8 and C-14 — same root cause, different symptoms), and (2) `useBoardSocket.ts` over-deduplicates broadcasts (C-10). C-22 is unrelated test debt from the new `position` field. None of these require rethinking the architecture; the optimistic-update + WebSocket-broadcast design is sound. Refine.
- **Anti-pattern check:** I caught myself wanting to pass C-14 because "the announcement does fire" — but the spec's intent is correct-state announcement, and the failed-rollback case proves the current implementation announces wrongly. Filed as fail.

---

## Evaluator Self-Check

- [x] Did I run more than one Playwright path per criterion (happy + at least one edge)? Yes — concurrent tab probe, intercepted-failure probe, kill-server probe, malformed-payload probe.
- [x] Did I check API responses AND database state? Yes — direct `sqlite3` queries on C-4, C-6.
- [x] Did I file every issue I found, even minor ones? Yes — including the C-12 Esc-cancel caveat and the C-3 DevTools spike.
- [x] Are all bug reports file:line specific? Yes — `boardStore.ts:171`, `BoardView.tsx:218`, `useBoardSocket.ts`, `test_cards.py:48`, `test_columns.py:91`, `boardStore.ts:147`.
- [x] Did I score originality / design quality strictly? N/A this sprint — full-stack rubric, design quality assessed via spec adherence (motion token honored, accent color used appropriately).
