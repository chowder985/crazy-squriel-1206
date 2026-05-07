# Sprint 03 Handoff (iteration 1) — Generator → Evaluator

> Worked example. This is what the Generator writes to `.harness/handoffs/sprint-03-handoff.md` after implementation. The Evaluator reads this before driving Playwright.

---

## URLs

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/ws/board/{boardId}

## Demo credentials

- User A: `alice@driftboard.test` / `synthetic-pw-A`
- User B: `bob@driftboard.test` / `synthetic-pw-B`
- Pre-seeded board: workspace "Acme", board "Roadmap" with 3 columns ("Todo", "In Progress", "Done") and 8 cards.

## Files changed this iteration

### Backend (FastAPI + SQLAlchemy)
- `backend/migrations/0008_add_card_position.py` — adds `position INTEGER NOT NULL` to `cards`; backfills existing rows with `row_number() OVER (PARTITION BY column_id ORDER BY created_at)`. Idempotent guard on column existence.
- `backend/models/card.py` — added `position: Mapped[int]`. Composite index `(column_id, position)`.
- `backend/schemas/card.py` — added `CardReorderItem` (id, column_id, position) and `CardReorderRequest` (list of CardReorderItem).
- `backend/routes/cards.py:88` — new `PATCH /api/v1/cards/reorder` endpoint. Validates payload, applies reorder in a single transaction, returns updated cards. Auth via existing `Depends(current_user)`.
- `backend/ws/board.py` — new module. `ConnectionManager` keyed by board_id; `broadcast_reorder(board_id, payload, exclude_session)` called from the route after commit.
- `backend/main.py:42` — mount `ws/board.py` router at `/ws/board/{board_id}`.

### Frontend (React + Vite + Zustand)
- `frontend/src/store/boardStore.ts:142` — new `applyLocalMove(cardId, toColumnId, toPosition)` mutation. Stores prior order in `pendingOps[opId].snapshot` for rollback.
- `frontend/src/store/boardStore.ts:171` — `commitMove(opId)` and `rollbackMove(opId, reason)`.
- `frontend/src/hooks/useBoardSocket.ts` — new hook. Opens WebSocket, subscribes to `reorder` events, applies them to the store via `applyRemoteMove` (skips if `pendingOps[remoteOpId]` exists).
- `frontend/src/components/Card.tsx` — added drag handle, `aria-grabbed`, keyboard handlers (Space to grab, arrow keys to move, Space to drop, Esc to cancel).
- `frontend/src/views/BoardView.tsx` — wires drag-drop via `dnd-kit`; calls `applyLocalMove` on drop; calls `commitMove` on PATCH success, `rollbackMove` on failure.
- `frontend/src/components/LiveRegion.tsx` — new aria-live="polite" region; subscribes to store's `lastAnnouncement` field.
- `frontend/src/styles/tokens.css` — adds `--motion-card: 180ms cubic-bezier(0.22, 1, 0.36, 1)`; respects `@media (prefers-reduced-motion: reduce)` to set duration to 0.

### Tests
- `backend/tests/test_card_reorder.py` — 9 unit + integration tests covering payload validation, transactional update, broadcast call, auth.
- `frontend/src/store/boardStore.test.ts` — 6 tests covering `applyLocalMove`, `rollbackMove`, snapshot restore, no-op detection.
- `frontend/e2e/drag.spec.ts` — happy-path drag for smoke; deeper E2E left to the Evaluator.

## Self-evaluation summary

Ran through the 22 contract criteria locally. Self-judged:

- **Passing locally:** C-1, C-2, C-3, C-4, C-5, C-6, C-7, C-9, C-11, C-12, C-13, C-15, C-16, C-17, C-18, C-19, C-21, C-22 (18/22).
- **Concerns I want the Evaluator to verify:**
  - **C-8** (rollback on 5xx): I implemented `rollbackMove` but I'm not 100% confident it restores correctly when the WebSocket broadcast for a *different* user's move arrives during the failed PATCH window. There's a race in `boardStore.ts:171` worth probing.
  - **C-10** (concurrent convergence): I implemented last-write-wins server-side, but the client deduplication in `useBoardSocket.ts` is `pendingOps`-based — if the user makes a second move before the first PATCH returns, behavior is untested.
  - **C-14** (live region announcement): the string is hardcoded English. Spec doesn't require i18n yet, but flagging for completeness.
  - **C-20** (WS reconnect): exponential backoff implemented; missed broadcasts trigger a full board refetch on reconnect rather than per-event replay. Self-judged correct but Evaluator may want a different design.

## Refine / Pivot decision

- **Iteration:** 1 — N/A.

## Figma mappings

- No Figma source provided for this run; Visual Design criterion applies via spec design language only.

## Notes for the Evaluator

- Seed the DB to a clean state with `python -m backend.scripts.seed_demo` before testing — it resets to the 3-column / 8-card baseline.
- The `pendingOps` map in `boardStore.ts` is the most likely place for race-condition bugs; please probe it adversarially.
