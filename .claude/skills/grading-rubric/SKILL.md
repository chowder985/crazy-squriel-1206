---
name: grading-rubric
description: The two rubrics (frontend design + full-stack), threshold mechanics, the Figma Design Fidelity extension, and few-shot calibration examples. Loaded by the Evaluator before scoring and read by the Generator so it knows what it's being judged against.
---

# Grading Rubric

> The wording of these criteria *directly shapes the Generator's output*. Phrases like "the best designs are museum quality" pulled designs toward visual convergence in the original harness experiment. Treat the language here as part of the prompt the Generator will read, not just the Evaluator's checklist.

---

## Scoring Mechanic

- **Scale:** 0–10 per criterion.
- **Per-criterion threshold:** **7/10** by default. Configurable per sprint contract (Section 6 of `templates/contract-template.md`).
- **Sprint outcome rule:** If **any** `must`-criticality criterion scores below threshold, the sprint **fails** and the Generator iterates. `should`-criticality failures degrade the overall score but do not block.
- **No averaging across criteria.** Do not let strong scores in one criterion compensate for a sub-threshold score in another. The article's whole point of separating scoring is to prevent the smoothing-over instinct.
- **Iteration cap:** 15 cycles per sprint (per-sprint mode), 5 build/QA rounds (end-to-end mode). At cap, the Generator writes an escalation file and the run halts for the user.

---

## Rubric A — Frontend Design

> Use this rubric when the work is primarily UI / frontend / visual generation. **Weight design quality and originality more heavily** in your judgment — Claude scores well on craft and functionality by default but tends toward bland outputs on the first two.

### A1. Design quality

> Does the design feel like a coherent whole rather than a collection of parts? Strong work means the colors, typography, layout, imagery, and other details combine to create a distinct mood and identity. **The best designs are museum quality.**

- **0–3:** A collection of components glued together. No identifiable mood. Default Tailwind / shadcn aesthetics with no customization.
- **4–6:** Coherent in places but inconsistent. Some surfaces feel considered, others feel like filler.
- **7–8:** A clear mood pervades the whole product. Type, color, spacing, and imagery agree with each other.
- **9–10:** Museum-quality. The design *is* the product, not decoration on top of it.

### A2. Originality

> Is there evidence of custom decisions, or is this template layouts, library defaults, and AI-generated patterns? A human designer should recognize deliberate creative choices. Unmodified stock components, or telltale signs of AI generation like purple gradients over white cards, fail here.

- **0–3:** Generic AI aesthetic — gradients on cards, sans-serif Title Case headings, three-column feature grids, "Get Started" buttons. Could be any SaaS landing page.
- **4–6:** Some custom touches but the underlying skeleton is template-shaped.
- **7–8:** Clear deliberate decisions: distinctive typography pairing, unusual but defensible layout, considered color palette outside default ranges.
- **9–10:** Surprising, specific, defensible — feels designed rather than generated. Could only have been made for *this* product.

### A3. Craft

> Technical execution: typography hierarchy, spacing consistency, color harmony, contrast ratios. This is a competence check rather than a creativity check.

- **0–3:** Misaligned baselines, inconsistent paddings, contrast under WCAG AA, type sizes from a random sample.
- **4–6:** Mostly tidy but several visible inconsistencies — half-pixel borders, mismatched corner radii, sibling components with different paddings.
- **7–8:** Consistent tokens, clear hierarchy, AA-passing contrast, restrained motion.
- **9–10:** Pixel-clean, defensible spacing scale, zero visible inconsistencies.

### A4. Functionality

> Usability independent of aesthetics. Can users understand what the interface does, find primary actions, and complete tasks without guessing?

- **0–3:** Primary action is unfindable; navigation is unclear; states are missing or wrong.
- **4–6:** Works but takes thought. Unlabeled icons, hidden controls, or surprising interactions.
- **7–8:** Discoverable. A first-time user completes the primary task without help.
- **9–10:** Effortless. The interface predicts what the user needs.

---

## Rubric B — Full-Stack

> Use this rubric for full application builds (backend + frontend + state). Each criterion still scores 0–10, threshold 7.

### B1. Product depth

> Feature completeness vs. spec; depth of interaction; no display-only or stubbed features where the spec calls for real ones.

- **0–3:** Many features stubbed or wired to fixed data. Empty states missing. Forms that don't persist. The "AI feature" that returns hardcoded text.
- **4–6:** Half the spec is real, half is theater. Critical flows have dead ends.
- **7–8:** Every feature in the spec is implemented end-to-end. Empty/error/loading states exist. AI features actually call the model.
- **9–10:** Real-product depth — keyboard shortcuts, undo, optimistic UI, considered empty states with calls-to-action, useful error messages.

### B2. Functionality

> Core flows actually work end-to-end; no broken wiring between layers; APIs and database state behave correctly under real use.

- **0–3:** Frontend mocks data the backend doesn't serve. Routes return 500 on the second request. State persists incorrectly.
- **4–6:** Happy path works; first edge case breaks (concurrent edits, refresh mid-flow, unauthenticated access).
- **7–8:** Happy path + common edge cases handled. API contracts match frontend usage. DB state is consistent across reloads.
- **9–10:** Robust under adversarial use — concurrent operations, network failures, unexpected payloads.

### B3. Visual design

> Coherent identity and design choices. Inherits the spirit of Rubric A but applied to the whole product, not just one screen.

- **0–3:** Stock components, no theming, inconsistent across screens.
- **4–6:** Theming exists but only partially applied.
- **7–8:** Coherent across all screens, deliberate choices visible.
- **9–10:** Museum-quality applied at product scale.

### B4. Code quality

> Readable, maintainable code. **Existing-codebase mode:** this includes consistency with the existing codebase patterns — file layout, naming, module structure, idioms.

- **0–3:** Magic numbers, copy-paste duplication, large files, no separation of concerns. In existing-codebase mode: introduces a new pattern when the existing one would do.
- **4–6:** Reasonable but inconsistent. Some files clean, others sprawling.
- **7–8:** Cohesive style; functions focused; tests exist for new behavior. Existing-codebase mode: matches existing conventions.
- **9–10:** Code feels like it belongs in the codebase already; could be reviewed and merged with minimal comments.

---

## Rubric Extension — Design Fidelity (Figma source present)

> Append this criterion to whichever rubric is in use whenever a Figma source was provided at init.

### F1. Design Fidelity

> Pixel-level adherence to the Figma source. Deviations require explicit justification with specific deltas — not "looks close."

**Required to flag:**
- Spacing deltas exceeding ~4px on any visible boundary.
- Color hex mismatches (Figma defines tokens; if the implementation uses a different hex, that's a delta — even if "visually similar").
- Typography scale or weight mismatches (e.g., Figma `1.5rem/600` vs implemented `1.25rem/500`).
- Missing component states (hover, focus, disabled, loading, empty) defined in the Figma file.
- Structural layout deviations (column count, sidebar width, grid gap).

**Scoring:**
- **0–3:** Multiple high-severity deltas across multiple surfaces. Implementation looks "inspired by" Figma rather than implementing it.
- **4–6:** A handful of medium-severity deltas; missing states.
- **7–8:** Minor deltas only (<4px spacing here and there); all states implemented; tokens match.
- **9–10:** Indistinguishable from the Figma source at the pixel level (modulo browser font rendering).

> When marking a deviation, the Evaluator MUST log it in the Design Fidelity table with: surface, Figma frame id, deviation, *measured* delta, severity. "Looks close" is not allowed.

---

## Calibration — Few-Shot Scoring Examples

> The Evaluator should reference these when scoring to keep judgment aligned across iterations and avoid drift. Calibration was the lever the original author used to keep the evaluator's judgment matching theirs.

### Example 1 — Frontend, scoring `Originality`

**App:** A landing page for a fictional indie developer tool.

**Implementation observed:** Hero section with a purple-to-blue gradient background, white card overlay containing a centered headline in Inter Bold 56px, three feature cards below in a grid, "Get Started Free" CTA in indigo. Footer with three columns of links.

**Score:** **2/10 — FAIL**
**Reasoning:** This is the canonical AI-generated SaaS landing page. Purple gradient over a white card is a *telltale sign of AI generation*. Inter, indigo, three feature columns — every choice is the default. No deliberate decision visible.

---

### Example 2 — Frontend, scoring `Design quality`

**App:** A reading app for long-form articles.

**Implementation observed:** Single-column layout, serif body type (Source Serif Pro), generous line height (1.7), warm off-white background `#FAF8F4`, sidebar collapsed by default revealing only a thin progress indicator. Typography hierarchy uses three sizes (article title, subhead, body) with a coherent rhythm.

**Score:** **8/10 — PASS**
**Reasoning:** Coherent identity — every choice agrees with "this is for reading." Type system is restrained, color palette is purposeful, the progress indicator is a deliberate choice over a standard sidebar. Not yet museum-quality (no surprising creative move), but solidly considered.

---

### Example 3 — Full-stack, scoring `Product depth`

**App:** Habit tracker; spec calls for streaks, weekly review, AI-suggested habit categories.

**Implementation observed:** Daily check-off works and persists. Streaks display correctly. Weekly review screen exists but shows "Coming soon." AI suggestions return hardcoded strings instead of calling the API.

**Score:** **4/10 — FAIL**
**Reasoning:** The "Coming soon" weekly review is theater for a feature that's in the spec. The fake AI is the worse offense — the spec explicitly required AI weaving, and a hardcoded string violates the contract. Two `must` criteria failed; sprint must iterate.

---

### Example 4 — Full-stack, scoring `Functionality` (threshold case)

**App:** Kanban board; tested drag-drop reorder.

**Implementation observed:** Happy path works (drag card within column, reorder persists). Cross-column drag works. Edge case probed: with two browser tabs open, dragging in tab A does not update tab B until manual refresh — the websocket broadcast isn't wired.

**Score:** **6/10 — FAIL** (threshold 7)
**Reasoning:** Single-user happy path is solid, but the spec called for realtime sync. Missing the broadcast is a `must` failure even though the local experience works. Don't round this up because "the basic case works" — that's the talking-yourself-out-of-it failure mode.

---

### Example 5 — Full-stack, scoring `Code quality` in existing-codebase mode

**App:** Adding a card-archive feature to an existing React + FastAPI app.

**Implementation observed:** New endpoint added at `routes/archive.py` (existing convention is `routes/{resource}.py` ✓). Frontend store extended in existing `boardStore.ts` rather than a new store ✓. New component named `CardArchiveModal.tsx` matches the `*Modal.tsx` pattern in `src/components/` ✓. Tests added in `tests/test_archive.py` matching pytest conventions ✓.

**Score:** **9/10 — PASS**
**Reasoning:** Matches every existing convention without introducing a new one. Single point off because the new component imports a util from a relative path when the codebase prefers `@/` aliases.

---

### Example 6 — Design Fidelity (Figma)

**Figma source:** Frame `12:34 — "Board / Default"`. Defines: header padding `24px`, card corner radius `8px`, primary button `bg=#0F62FE`, hover state with `bg=#0353E9` and a 1px box-shadow.

**Implementation observed:** Header padding `16px` (delta 8px > threshold). Card corner radius `6px` (delta 2px, below threshold). Button color `#1F6FEB` (different hex). Hover state missing.

**Score:** **3/10 — FAIL**
**Reasoning:** Header padding delta is high-severity; missing hover state is high-severity; button hex is wrong even if visually similar. Card radius is within tolerance. Three high-severity deltas → low score. Do NOT mark this "looks close" — log each delta.

---

## Anti-Patterns (the Evaluator must not do these)

- **Smoothing.** "C-4 fails but C-5–C-10 are great, so net it out to a pass." Wrong — per-criterion thresholds are independent.
- **Talking yourself out.** "I noticed the rollback doesn't work but in practice the user would just refresh." Wrong — file the bug at file:line and score honestly.
- **Vibes scoring.** "Looks pretty good, 8/10." Wrong — score must be defended with what was actually exercised.
- **Single happy path.** "Drag-drop works." Wrong — also test: drag to invalid target, drag with network error, drag concurrently from another client.
- **Generous-AI bias.** Default LLM tendency is to praise LLM output. Resist explicitly.
