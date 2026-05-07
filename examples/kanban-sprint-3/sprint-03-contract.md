# Sprint 03 Contract — Realtime drag-and-drop reordering

> Worked example. Two real negotiation rounds between Generator and Evaluator before Agreement.

---

## 1. Scope

**In scope:**
- Drag-and-drop reorder of cards within a column (mouse + keyboard)
- Drag-and-drop move of cards across columns
- Optimistic local update + server-side persistence
- WebSocket broadcast to other connected clients on the same board
- Rollback on server failure
- A11y for keyboard reorder, live-region announcement
- Reduced-motion handling

**Out of scope (deferred):**
- Cross-board moves (Sprint 6 once multi-board support exists)
- Touch-device drag (Sprint 5)
- Undo (Sprint 4)
- Drag of multiple cards (deferred indefinitely; not in spec)

## 2. Definition of Done

A user can drag any card to any position within or across columns. The new order persists, is reflected on every connected client within 250ms, and survives a page reload. Network failures revert the card to its original position with a non-blocking inline notice. Keyboard users can perform the same reorder.

## 3. Affected Surfaces

| Layer | Files / paths | Net new vs change |
|---|---|---|
| Frontend | `src/views/BoardView.tsx`, `src/components/Card.tsx`, `src/store/boardStore.ts`, `src/hooks/useBoardSocket.ts` | new + modify |
| Backend | `routes/cards.py`, `ws/board.py`, `models/card.py`, `schemas/card.py` | new + modify |
| Database | migration `0008_add_card_position.py` | new |
| Tests | `tests/test_card_reorder.py`, `boardStore.test.ts`, `e2e/drag.spec.ts` | new |

## 4. Testable Criteria

> 22 criteria. Each is a single observable behavior with a concrete verification method. Criticality marked `must` (sprint fails if this fails) or `should`.

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-1 | User can drag a card to a new position within the same column | Playwright: drag card "Ship onboarding" from index 2 to index 0 in column "In Progress"; assert DOM order in column container | must |
| C-2 | User can drag a card across columns | Playwright: drag from "Todo" to "In Progress"; assert column membership and final position | must |
| C-3 | Drag visual feedback appears within 16ms of mousedown | Playwright: track time from mousedown to ghost-element render via `performance.now()` injection; assert <16ms | should |
| C-4 | Reorder persists after page reload | Playwright: reload `/board`; assert DOM order matches the post-drag order | must |
| C-5 | PATCH /api/v1/cards/reorder returns 200 with `{cards: [{id, column_id, position}]}` | curl with valid payload; assert HTTP 200 and JSON shape | must |
| C-6 | DB row count for `cards` table does not change on reorder | sqlite query before/after; assert delta == 0 | must |
| C-7 | Optimistic update applied immediately (before server response) | Playwright with route delay (1000ms): assert UI updated within 50ms; server response not yet received | must |
| C-8 | Optimistic update rolled back if server returns non-2xx | Playwright with route intercept returning 500; assert UI reverts to pre-drag state within 200ms; assert inline notice "Couldn't save — restored" appears | must |
| C-9 | WebSocket broadcasts the reorder to other connected clients within 250ms | Playwright: open second tab; drag in tab A; assert tab B reflects new order within 250ms | must |
| C-10 | Concurrent moves from two clients converge to a consistent order | Playwright: tab A moves card X; tab B moves card Y in parallel; assert both tabs end with same DOM order matching server response | must |
| C-11 | Server payload is versioned `v1` (envelope key or path prefix) | curl: assert URL contains `/v1/` and JSON body uses versioned schema | should |
| C-12 | Card is keyboard-reorderable (Tab → Space → arrows → Space) | Playwright: keyboard-only sequence; assert card moved | must |
| C-13 | Drag handle has accessible name "Drag card: <title>" | Playwright snapshot: assert ARIA name on drag-handle element | must |
| C-14 | Live region announces "Moved <title> to position N in <column>" | Playwright: aria-live region content polled after move; assert string match | should |
| C-15 | Reduced-motion users see instant snap (no transition) | Playwright with `forcedColors: 'none'` and `prefers-reduced-motion: reduce`; assert computed transition-duration is `0s` | should |
| C-16 | Empty-column drop target shows visible state on hover | Playwright: drag over empty column; snapshot; assert hover style applied | should |
| C-17 | Drop on the same position is a no-op (no PATCH fired) | Playwright: drag and drop in same spot; assert no `/cards/reorder` request in network log | should |
| C-18 | Unauthenticated PATCH returns 401 | curl without session cookie; assert HTTP 401 | must |
| C-19 | PATCH with malformed payload returns 422 with field-level errors | curl missing `position`; assert HTTP 422 with `detail` array citing field | must |
| C-20 | WebSocket connection auto-reconnects on close | Playwright: kill backend, restart; assert UI reconnects within 5s and a missed broadcast is replayed (or full state refetched) | should |
| C-21 | New `position` migration is idempotent (re-applying does not error) | Bash: run migration twice; assert second run is a no-op | must |
| C-22 | Existing tests still pass | Bash: run `pytest` and `npm test`; assert both green | must |

## 5. Negotiation Log

### Round 1 — Generator proposal (timestamp: 2026-05-06T22:01:14Z)

> The Generator initially submitted 14 criteria covering C-1, C-2, C-4, C-5, C-7, C-8, C-9, C-12, C-13, C-15, C-16, C-18, C-19, C-22.

### Round 1 — Evaluator review (timestamp: 2026-05-06T22:14:02Z)

**Accept as-is:** C-1, C-2, C-4, C-5, C-7, C-8, C-9, C-13, C-18, C-19, C-22.

**Reject — too vague:**
- *"Drag feels responsive"* (Generator's original C-3) → rewrite as **C-3** above with a measurable threshold (<16ms to ghost render).

**Reject — duplicate:**
- *"Server updates DB on reorder"* → already covered by C-5 (returns 200) + C-6 (no row delta). Collapse.

**Add — Evaluator catches missing edges:**
- **C-6**: The Generator only verified UI state. A "reorder" should not change the `cards` table row count — verify the DB invariant directly. (`should` → `must`: silent row creation is a real risk on optimistic-update bugs.)
- **C-10**: Concurrent moves from two clients. The Generator's contract doesn't address what happens when two people drag the same card at the same time. This is the textbook two-user kanban bug.
- **C-11**: Versioning. Spec calls out `v1` envelope — must verify it's actually present.
- **C-14**: A11y live-region announcement. Drag handle alone is not enough; screen-reader users need a confirmation when the move completes.
- **C-17**: Drop-on-same-position no-op. Without this, every accidental click-drag fires a PATCH; pollutes the network log and risks a server-side conflict on truly concurrent edits.
- **C-20**: WebSocket reconnect. The spec requires realtime; if the socket drops, the UI must recover, not silently desync.
- **C-21**: Migration idempotency. New column on a real table — re-running on a stale env without idempotency breaks deploys.

**Reject — wrong scope:**
- *"Animate the avatar of the user who moved a card"* (Generator's stretch idea) — defer; not in spec for Sprint 3, belongs in a polish sprint.

**Push back on count:** Generator proposed 14 criteria for a sprint that is the central interaction of the product. That is below the 15–30 floor for a non-trivial sprint and means the spec is being skimmed (specifically: edge cases and a11y were under-covered). Resubmit.

### Round 2 — Generator revised (timestamp: 2026-05-06T22:24:48Z)

> Generator accepted all additions and rewrites. Two follow-ups:
>
> 1. *"For C-10, what's the convergence rule? Server-wins last-write-wins, or something more sophisticated?"* — Evaluator response: **Last-write-wins is acceptable for v1 (spec doesn't require CRDTs); the criterion just verifies that both clients end up at the same final state, not how the conflict resolves.**
> 2. *"For C-3 (16ms feedback), is `performance.now()` injection acceptable since Playwright tracing isn't precise enough?"* — Evaluator: **Yes; but also assert visual feedback element exists in the DOM after the first frame.**

### Round 2 — Evaluator final (timestamp: 2026-05-06T22:28:13Z)

All criteria accepted. Promoted C-6 from `should` to `must` (DB invariant).

### Agreement (timestamp: 2026-05-06T22:29:01Z)

Both agents acknowledge the 22 criteria above as the definitive contract for Sprint 03. No new criteria during implementation; no criteria silently dropped during evaluation.

## 6. Threshold Applied

- **Per-criterion threshold:** 7/10 (default).
- **Iteration cap:** 15.
- **Escalation:** standard — Generator writes `.harness/escalations/sprint-03-escalation.md` if cap is hit.

## 7. Rubric Selection

- [x] Full-stack rubric (full-app sprint with backend, frontend, state)
- [ ] Frontend rubric
- [ ] Add Design Fidelity criterion (no Figma source provided)
