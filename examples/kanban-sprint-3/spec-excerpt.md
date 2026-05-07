# Spec Excerpt — Driftboard (Kanban Board) — Sprint 3 Slice

> Excerpt of the full spec at `.harness/plans/spec.md`. This file shows only the parts relevant to **Sprint 3 — Realtime drag-and-drop reordering**, plus enough surrounding context (Section 1 overview, design language, data model fragment) for the Generator and Evaluator to ground the contract.

---

## 1. Overview

**Driftboard** is a small-team kanban board for product squads who care about the texture of their workflow. It is opinionated: a single board per workspace, columns are flow stages (not arbitrary lists), and cards carry just enough metadata to be useful without becoming Jira. Realtime by default — when one teammate moves a card, everyone watching sees it within the same animation frame.

## 4. Design Language (excerpt)

- **Mood:** *Quiet, considered, slightly editorial.* Off-white canvas (`#F8F6F1`), warm slate ink (`#1F2937`), one accent (`#5B6CFF` for in-flight states only).
- **Type system:** Inter for UI, Source Serif 4 for column headings only — gives the board the feel of a desk plan rather than software.
- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.
- **Motion:** all card transitions on `cubic-bezier(0.22, 1, 0.36, 1)` at 180ms — never abrupt, never floaty. The drag preview lifts 4px and gains a 12% opacity shadow.
- **Voice:** verbs in plain present tense ("Move", "Add", "Done"), no exclamation marks anywhere.

## 6. Data Model (sketch)

| Entity | Fields | Relationships |
|---|---|---|
| User | id, email, password_hash, display_name, created_at | belongs to Workspace |
| Workspace | id, name, created_at | has many Users, has one Board |
| Board | id, workspace_id, name | has many Columns |
| Column | id, board_id, name, position (int) | has many Cards |
| Card | id, column_id, title, description, position (int), created_at, updated_at | belongs to Column |

> The `position` column on `Card` is what Sprint 3 introduces. Generator chooses fractional vs integer position semantics — both are defensible.

## 7. Page / Screen List (excerpt)

- `/` — landing (marketing, out of scope for Sprint 3)
- `/login`, `/signup` — auth (delivered in Sprint 1)
- `/board` — the only app surface; everything happens here

## 9. Sprint Decomposition — Sprint 3 entry

**Sprint 3 — Realtime drag-and-drop reordering**

User-meaningful outcome: *"I can drag a card to a new position, and my teammate sees the new order in real time."*

Why this sprint matters: drag-and-drop is the central interaction of a kanban board. Without realtime sync, two people editing the same board produce conflicting state. The article's whole point about "no display-only or stubbed features" applies here especially — a kanban that pretends to be realtime but actually requires refresh is theater.

**Depth criteria** (carried into the contract):
- Optimistic local update — the card moves before the server replies.
- Server validates and rebroadcasts via WebSocket to all subscribed clients.
- Rollback on server failure with a small inline notice ("Couldn't save — restored").
- Concurrent moves from two users converge to a single consistent order.
- Keyboard-only reorder (Tab to a card, Space to grab, arrow keys to move, Space to drop).
- Reduced-motion users get an instant snap, no transition.
- A11y: drag handle has an accessible name; focus moves with the card; live region announces moves.
- Server endpoint and websocket payload are versioned (`v1`) so future schema changes don't break in-flight clients.

**Out of scope for this sprint:**
- Cross-board moves (only one board per workspace exists right now).
- Card archiving (Sprint 4).
- Drag-and-drop on touch devices (Sprint 5 — needs different gesture handling).

## 11. Success Criteria (Sprint 3 contribution)

- A user dragging a card sees it move within one animation frame (16ms).
- A second teammate watching the same board sees the new order within 250ms over a typical broadband connection.
- If the network drops mid-drag, the card returns to its original position with a non-blocking inline notice; no toast spam.
- Accessibility floor: all drag-and-drop functionality reachable via keyboard, with audible announcements (WCAG 2.2 AA).
