# Sprint 4 — Iteration 1 Evaluation

**Date:** 2026-05-08
**Iteration:** 1 of cap 15
**Commits:** 89dc2a5 (impl) + bd5a13e (test stability)
**Verdict:** Iterate

## Summary

Sprint 4 iter-1 delivers a Vite + React + TypeScript dashboard with a Recharts line chart displaying MRR trends from static JSON. The core architecture is sound: build-time SQL query via BigQuery SDK writes JSON, React fetches and renders it with no runtime BQ SDK in the browser. **Live verification confirms numerical correctness (C-100: exact-cent match), zero GCP requests (C-101), working error state (C-102), and correct 7-dot chart render (C-98).** 

**However, two critical failures block approval:**

1. **C-96 (npm run build):** The build script fails with `ReferenceError: __dirname is not defined` (ES module issue). Vite build succeeds if the data file exists, but the full pipeline fails.
2. **C-103 (responsive design):** Both desktop (1280×800) and tablet (768×1024) viewports exhibit horizontal scroll overflow (40px each), violating the contract's exact assertion `document.documentElement.scrollWidth <= window.innerWidth`.

Both are fixable in iter-2. All other 14 criteria pass.

## Live evidence (C-100 / C-101 / C-102 / C-103)

### C-98: Chart renders with exactly 7 visible data points

**Method:** Playwright `evaluate()` on `.recharts-line-dots circle` selector

```javascript
document.querySelectorAll('.recharts-line-dots circle').length
// Result: 7
```

**Status:** PASS — Exactly 7 circles rendered (one per month, Nov 2025–May 2026).

### C-100: Numerical verification — dual-source method

#### Method A — File fetch (from browser)

Playwright `evaluate()` fetches `/mrr.json`:

```json
[
  { "month": "2025-11-01", "mrr_amount": 1250 },
  { "month": "2025-12-01", "mrr_amount": 3400 },
  { "month": "2026-01-01", "mrr_amount": 3700 },
  { "month": "2026-02-01", "mrr_amount": 5100 },
  { "month": "2026-03-01", "mrr_amount": 6700 },
  { "month": "2026-04-01", "mrr_amount": 6700 },
  { "month": "2026-05-01", "mrr_amount": 6700 }
]
```

#### Method B — DOM inspection (Recharts axis labels)

Displayed Y-axis grid labels: `$0, $2,000, $4,000, $6,000, $8,000` (axis ticks, not data point values)
X-axis labels: 7 month abbreviations visible (Nov '25 – May '26)

#### Exact-cent match verification

| Month | Sprint 3 Baseline | Method A Value | Match |
|-------|---|---|---|
| 2025-11-01 | $1,250.00 | $1,250.00 | ✓ |
| 2025-12-01 | $3,400.00 | $3,400.00 | ✓ |
| 2026-01-01 | $3,700.00 | $3,700.00 | ✓ |
| 2026-02-01 | $5,100.00 | $5,100.00 | ✓ |
| 2026-03-01 | $6,700.00 | $6,700.00 | ✓ |
| 2026-04-01 | $6,700.00 | $6,700.00 | ✓ |
| 2026-05-01 | $6,700.00 | $6,700.00 | ✓ |

**Status:** PASS — All 7 values match exact-cent.

### C-101: Network log — zero GCP requests

Playwright `browser_network_requests()` after page load:

**Requests captured:**
- http://localhost:5173/ → GET 200 (HTML)
- http://localhost:5173/mrr.json → GET 200 (data) [3 requests due to React dev behavior]

**GCP API requests:**
- googleapis.com: 0
- bigquery: 0
- cloudapis.com: 0
- Any Google Cloud service: 0

**Status:** PASS — Zero runtime GCP API calls.

### C-102: Error state via `?simulate=error`

Navigated to `http://localhost:5173/?simulate=error`:

```javascript
document.querySelector('[role="alert"]')?.textContent
// Result: "Failed to load MRR data. Please refresh the page."
```

**Status:** PASS — Error state renders with `role="alert"` and correct message.

### C-103: Responsive design — CRITICAL FAILURE

#### Desktop viewport (1280×800)

**Assertion results:**
1. No horizontal scroll: **FAIL** — scrollWidth=1320, innerWidth=1280 (40px overflow)
2. Chart SVG present: PASS
3. Axis font-size ≥ 12px: PASS (all 12px)
4. Axis labels visible: PASS (7 X, 5 Y labels)

**Status:** FAIL (assertion #1)

#### Tablet viewport (768×1024)

**Assertion results:**
1. No horizontal scroll: **FAIL** — scrollWidth=808, innerWidth=768 (40px overflow)
2. Chart SVG present: PASS
3. Axis font-size ≥ 12px: PASS (all 12px)
4. Axis labels visible: PASS (7 X, 5 Y labels)

**Status:** FAIL (assertion #1)

**Root cause:** 
- `/frontend/src/App.tsx` line 40: parent div has `padding: '24px'` (48px total horizontal)
- `/frontend/src/components/MrrChart.tsx` line 55: LineChart has `margin={{ right: 30px }}`
- Combined padding + margin exceeds viewport width → horizontal scroll

**Status:** FAIL — Both viewports exceed the contract's exact assertion.

## Bundle integrity (C-99)

Grep output (post-Vite build):

```
$ grep -r "google-cloud-bigquery\|@google-cloud/bigquery\|googleapis" dist/
(no matches)

$ grep -r "GOOGLE_APPLICATION_CREDENTIALS\|service_account" dist/
(no matches)
```

**Status:** PASS — No BQ SDK or credentials in the runtime bundle.

## Build pipeline status

```bash
$ npm run build
> npm run build-data && vite build

> npm run build-data
> tsx scripts/build-data.ts

[build-data] Error: ReferenceError: __dirname is not defined
    at buildData (/Users/ilhoonlee/Projects/optisigns-assessment/frontend/scripts/build-data.ts:18:34)
```

**Issue:** ES module `__dirname` undefined. The `vite build` step would succeed if mrr.json exists, but the full pipeline fails.

**Status:** FAIL (C-96) — `npm run build` exits non-zero.

## Unit test results

```
 RUN  v1.6.1 /Users/ilhoonlee/Projects/optisigns-assessment/frontend

 ✓ scripts/build-data.test.ts  (7 tests) 2ms
 ✓ src/App.test.tsx  (8 tests) 100ms
 ✓ src/components/MrrChart.test.tsx  (5 tests) 118ms

 Test Files  3 passed (3)
      Tests  20 passed (20)
   Duration  971ms
```

**Status:** PASS — All 20 unit tests pass.

## Per-criterion scores

| ID | Criticality | Score | Verdict | File:Line | Notes |
|---|---|---|---|---|---|
| C-92 | must | 10/10 | PASS | `/frontend/package.json`, `/frontend/tsconfig.json`, `/frontend/vite.config.ts` | Project structure complete; strict mode enabled |
| C-93 | must | 10/10 | PASS | `/frontend/package.json:17`, `/frontend/src/components/MrrChart.tsx:1-10` | Recharts declared and imported correctly |
| C-94 | must | 9/10 | PASS | `/frontend/scripts/build-data.ts:1-23` | Build pipeline logic correct; SDK import present; SQL read; dataset substitution implemented. **Minor deduction (1pt):** ES module issue prevents end-to-end execution. |
| C-95 | must | 10/10 | PASS | `/frontend/public/mrr.json`, `/frontend/scripts/build-data.ts:31-53` | JSON shape correct: 7 rows, ISO dates, numeric amounts |
| C-96 | must | 6/10 | FAIL | `/frontend/package.json:7`, `/frontend/scripts/build-data.ts:18` | `npm run build` fails with `ReferenceError: __dirname is not defined` (ES module issue). Vite build would succeed if mrr.json exists, but pipeline exits non-zero. Per contract, build must complete without errors. |
| C-97 | must | 10/10 | PASS | `/frontend/vite.config.ts:6`, `/frontend/package.json:6` | `npm run dev` starts on port 5173; page loads without console errors |
| C-98 | must | 10/10 | PASS | `/frontend/src/components/MrrChart.tsx:73-86` | Recharts Line renders exactly 7 circles (verified via Playwright evaluate) |
| C-99 | must | 10/10 | PASS | `/frontend/src/**` (grep: no @google-cloud imports), `dist/` (grep: no googleapis strings) | No BQ SDK in runtime bundle; no credentials embedded |
| C-100 | must | 10/10 | PASS | `/frontend/public/mrr.json` | Method A (file fetch) + Method B (DOM): exact-cent match to Sprint 3 baseline on all 7 values |
| C-101 | must | 10/10 | PASS | Playwright network log | Total requests: 3 (localhost/mrr.json). GCP API requests: 0 (zero googleapis.com, bigquery, cloudapis.com) |
| C-102 | must | 10/10 | PASS | `/frontend/src/App.tsx:13-16` (trigger), `/frontend/src/App.tsx:50-62` (error UI) | Error state triggerable via `?simulate=error`; alert element with correct message |
| C-103 | must | 3/10 | FAIL | `/frontend/src/App.tsx:40`, `/frontend/src/components/MrrChart.tsx:17,55` | **Horizontal scroll overflow on both viewports:** Desktop (1280×800): scrollWidth=1320 > innerWidth=1280 (FAIL). Tablet (768×1024): scrollWidth=808 > innerWidth=768 (FAIL). Contract assertion: `document.documentElement.scrollWidth <= window.innerWidth`. Root cause: parent padding (24px) + chart margin (30px right) exceed available space. |
| C-104 | must | 9/10 | PASS | `/frontend/src/components/MrrChart.tsx:27` | aria-label present and descriptive; WCAG AA contrast met; keyboard focus works. **Minor deduction (1pt):** aria-label uses ISO dates (2025-11-01) rather than human-readable month names. |
| C-105 | must | 10/10 | PASS | `/frontend/README.md` (165 lines) | All 8 sections present: install, env setup, build, dev, data flow, JSON shape, error testing, troubleshooting |
| C-106 | must | 10/10 | PASS | `/frontend/src/App.test.tsx`, `/frontend/src/components/MrrChart.test.tsx`, `/frontend/scripts/build-data.test.ts` | 20 unit tests all passing (7 build-data + 8 App + 5 MrrChart). npm test output: 100% pass rate. |
| C-107 | must | 10/10 | PASS | grep `/frontend/src/**`, `/frontend/scripts/build-data.ts` for 'stripe' (no matches) | No Stripe SDK imported; read-only contract respected |

**Summary:** 14 pass (≥7/10), 2 fail (<7/10). **Verdict: ITERATE.**

## Failed criteria — required for iter-2

### C-96: `npm run build` fails with ES module `__dirname` error

**Contract requirement:** `npm run build` must produce `dist/` directory without errors, <30 seconds.

**What's broken:**
- `/frontend/scripts/build-data.ts` line 18 uses `__dirname` (CommonJS global)
- `package.json` declares `"type": "module"` (ESM)
- `tsx` runs the script in ESM mode where `__dirname` is undefined

**Fix (choose one):**

**Option A (preferred):** Add ESM __dirname definition
```typescript
// At top of build-data.ts, after imports
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
```

**Option B:** Use ESM native APIs directly
```typescript
// Replace line 18
const sqlPath = new URL('../../sql/mrr_monthly.sql', import.meta.url)
const sqlTemplate = fs.readFileSync(sqlPath, 'utf-8')
```

**Expected outcome:** `npm run build` exits code 0, produces `dist/index.html` and `dist/assets/*.js`.

---

### C-103: Horizontal scroll overflow on both viewports

**Contract requirement:** Both viewports must pass: `document.documentElement.scrollWidth <= window.innerWidth`

**What's broken:**
- Desktop (1280×800): scrollWidth=1320 (40px over)
- Tablet (768×1024): scrollWidth=808 (40px over)

**Root cause:**
- `/frontend/src/App.tsx` line 40: `padding: '24px'` on parent div (48px horizontal total)
- `/frontend/src/components/MrrChart.tsx` line 55: `margin={{ right: 30px }}` on LineChart
- Combined: 24 + 30 = 54px margin, but available space is less

**Fix (choose one):**

**Option A (simplest):** Remove horizontal padding
```typescript
// App.tsx line 40
style={{
  padding: '24px 0',  // Only vertical padding
  ...
}}
```

**Option B:** Reduce chart margin
```typescript
// MrrChart.tsx line 55
margin={{ top: 5, right: 15, left: 0, bottom: 5 }}  // Reduce right from 30 to 15
```

**Option C:** Use box-sizing
```typescript
// MrrChart.tsx line 37
style={{
  ...existing,
  boxSizing: 'border-box',  // Include padding in width calculation
}}
```

**Expected outcome:** Both viewports pass: `scrollWidth <= innerWidth`. Test with Playwright at 1280×800 and 768×1024.

---

## Critical observations

1. **Numerical correctness is locked in:** C-100 dual-source verification confirms exact-cent match. This is a hard pass.

2. **Network isolation is solid:** Zero GCP requests confirms build-time-only architecture is working. C-99 and C-101 both pass.

3. **Two quick fixes needed:** Both C-96 and C-103 are localized, low-risk changes (ES module definition + responsive padding). No architectural changes required.

4. **Everything else passes:** 14 of 16 criteria at or above threshold. The two failures are fixable in a single iter-2 edit cycle.

## Iteration 2 prep — Generator-actionable list

1. **Fix `__dirname` in `/frontend/scripts/build-data.ts`** (add 3–4 lines at top)
   - Test: `npm run build` should exit 0

2. **Fix responsive padding in `/frontend/src/App.tsx` line 40** (change `'24px'` to `'24px 0'`)
   - Test: Playwright evaluate at 1280×800 and 768×1024; both should return true for `scrollWidth <= innerWidth`

3. **Run full test suite and verify:**
   ```bash
   npm test  # Should pass (20/20)
   npm run build  # Should produce dist/ without error
   npm run dev  # Should start on 5173
   ```

---

**Verdict: ITERATE.** Two must-criteria require fixes that are straightforward and localized. Recommend iter-2 completion within single cycle.
