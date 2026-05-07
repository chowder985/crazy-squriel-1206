# Spec — {{PRODUCT_NAME}}

> Written by the **Planner agent** for the Generator and Evaluator to consume.
> Stay at high-level product context and high-level technical design.
> Do NOT specify granular technical implementation — that gets locked in too early and cascades errors. Let the Generator make those calls during sprints.

## 1. Overview

{{One paragraph: what this product is, who it's for, the experience that makes it feel like a real product instead of a demo. Be ambitious about scope.}}

## 2. Target Users & Core Value

- **Primary user:** {{who}}
- **Core value:** {{the one sentence the user would tell a friend}}
- **Stretch users / scenarios:** {{secondary audiences worth supporting if scope permits}}

## 3. Mode

- [ ] **New project** — Generator scaffolds the stack from scratch
- [ ] **Existing codebase** — Generator extends an existing app; constrained to match conventions

### Detected Stack (existing-codebase mode only)

| Layer | Detected | Source of truth |
|---|---|---|
| Frontend | {{e.g. React 18 + Vite + TS}} | `package.json` |
| Backend | {{e.g. FastAPI 0.110}} | `pyproject.toml` |
| Database | {{e.g. SQLite via SQLAlchemy}} | imports + migrations |
| Tests | {{e.g. Vitest + pytest}} | scripts / configs |
| Style/format | {{e.g. ESLint + Prettier + ruff}} | configs |
| Component conventions | {{e.g. PascalCase files in `src/components/`, hooks in `src/hooks/`}} | directory scan |

> Generator MUST match this. Do not introduce new conventions when an existing one will do.

### Default Stack (new project mode)

React + Vite + TypeScript + Tailwind, FastAPI + SQLite (via SQLAlchemy + Alembic), pytest + Vitest + Playwright. PostgreSQL is a reasonable production upgrade — note in tech notes if the spec asks for it.

## 4. Design Language

> Produced after consulting the Anthropic frontend-design skill at https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md. The best designs are museum quality — make deliberate creative choices, not template defaults.

- **Mood / identity:** {{2–3 sentences describing the feel — concrete adjectives, references to actual aesthetics, not "modern and clean"}}
- **Type system:** {{font families, scale, weights}}
- **Color tokens:** {{semantic names → hex}}
- **Spacing scale:** {{base unit, scale stops}}
- **Layout primitives:** {{grid, sidebar, density choices}}
- **Imagery / illustration direction:** {{photography vs illustration vs none, treatment}}
- **Motion:** {{easing curves, duration ranges, where motion is used}}
- **Voice & microcopy:** {{tone samples}}

### Figma Source (when applicable)

- **File URL or local export dir:** {{...}}
- **Token export format:** {{Style Dictionary JSON, raw, etc.}}
- **Frame inventory:** {{per-screen frame ids the Generator must implement to}}

## 5. Feature List

For each feature: user stories, what "real" means (depth, not demo), and which screen(s) it lives on.

### Feature: {{Name}}

- **User stories:**
  - As a {{user}}, I can {{action}} so that {{outcome}}.
  - ...
- **Depth criteria:** {{things that distinguish a real implementation from a stub: empty states, error states, optimistic UI, undo, keyboard support, etc.}}
- **Screens / surfaces:** {{...}}
- **AI features (if any):** {{specifically how AI weaves in — not "add AI" but "given the user's last 5 entries, suggest tags using the Anthropic API with the user's API key"}}
- **Out of scope:** {{...}}

## 6. Data Model (sketch only)

| Entity | Fields | Relationships |
|---|---|---|
| {{User}} | id, email, password_hash, created_at | has many {{Boards}} |
| ... | ... | ... |

> Sketch only — Generator finalizes during implementation.

## 7. Page / Screen List

- `/` — {{landing or app shell}}
- `/login`, `/signup`
- `/{{primary surface}}` — {{description}}
- `/{{settings or profile}}`
- ...

## 8. AI Features (cross-cutting)

{{If the product benefits from AI features, describe them here — what they do, where they live, what data they need, and which provider (default: Anthropic Messages API). If none, state explicitly.}}

## 9. Sprint Decomposition (proposed)

> Used in per-sprint mode. End-to-end mode ignores this.

1. **Sprint 1 — Foundation.** Auth, app shell, primary entity CRUD.
2. **Sprint 2 — {{...}}.** ...
3. **Sprint 3 — {{...}}.** ...
4. **Sprint N — Polish.** Empty states, error states, accessibility, motion.

> The Generator may renegotiate this decomposition with the Evaluator if sprints turn out to be wrongly-sized.

## 10. Out of Scope

- {{Features explicitly NOT in this build}}
- {{Anti-features — things that would make the product worse}}

## 11. Success Criteria (high-level)

- {{What does a v1 that ships look like? — be concrete; this becomes input to the rubric.}}
- {{Performance / scale targets if relevant.}}
- {{Accessibility floor — recommend WCAG 2.2 AA at minimum.}}
