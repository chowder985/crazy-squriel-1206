# MRR Dashboard Frontend

A lightweight React + Vite + TypeScript dashboard displaying monthly recurring revenue (MRR) trends as a Recharts line chart. Data is sourced from BigQuery via a build-time SQL query and served as static JSON.

## 1. Installation

Requires Node 18+.

```bash
cd frontend
npm install
```

## 2. Environment Setup

The build-time script requires BigQuery credentials. Set the following environment variables:

### Required
- `GOOGLE_APPLICATION_CREDENTIALS` — Path to your Google Cloud service account JSON file
  ```bash
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
  ```

### Optional
- `GOOGLE_CLOUD_PROJECT` — Your GCP project ID (if not set, inferred from service account)
  ```bash
  export GOOGLE_CLOUD_PROJECT=my-project-id
  ```

- `BQ_DATASET` — BigQuery dataset name (defaults to `mrr_dev`)
  ```bash
  export BQ_DATASET=mrr_dev
  ```

**Important:** These credentials are used ONLY at build time. The runtime bundle contains no credentials or BigQuery SDK code — the browser fetches pre-computed static JSON.

## 3. Build the Data

Execute the MRR monthly calculation SQL query and generate the data JSON:

```bash
npm run build-data
```

This will:
- Read `../sql/mrr_monthly.sql` from the project root
- Substitute the `${dataset}` placeholder
- Query BigQuery and fetch 7 rows (Nov 2025 – May 2026)
- Write the result to `public/mrr.json`

The `npm run build` command (used for production) automatically invokes this as a prebuild step.

## 4. Dev Server

Start the Vite dev server:

```bash
npm run dev
```

The app will be available at `http://localhost:5173` by default.

### Quick start (combined)

```bash
npm install && npm run build-data && npm run dev
```

## 5. Build Static Bundle

Create a production-ready static bundle:

```bash
npm run build
```

This will:
1. Run `npm run build-data` (regenerate JSON from BigQuery)
2. Run `vite build` (bundle React app)
3. Output to `dist/` directory

The `dist/` directory is ready for deployment to any static host (Vercel, Netlify, GitHub Pages, S3, etc.).

## 6. Data Flow & JSON Shape

### Data Source
- **SQL:** `../sql/mrr_monthly.sql` (BigQuery Standard SQL, parameterized by dataset)
- **Query:** Calculates normalized monthly MRR from active subscriptions
- **Execution:** Build-time only, via `scripts/build-data.ts`

### JSON Format
Location: `frontend/public/mrr.json` (served as `/mrr.json` at runtime)

```typescript
// TypeScript interface:
interface MrrDataPoint {
  month: string        // ISO 8601 date string (YYYY-MM-DD), first day of month
  mrr_amount: number   // USD amount, exact-cent precision (e.g., 1250.00)
}

// Array of exactly 7 rows (Nov 2025 – May 2026)
const data: MrrDataPoint[] = [
  { "month": "2025-11-01", "mrr_amount": 1250.00 },
  { "month": "2025-12-01", "mrr_amount": 3400.00 },
  { "month": "2026-01-01", "mrr_amount": 3700.00 },
  { "month": "2026-02-01", "mrr_amount": 5100.00 },
  { "month": "2026-03-01", "mrr_amount": 6700.00 },
  { "month": "2026-04-01", "mrr_amount": 6700.00 },
  { "month": "2026-05-01", "mrr_amount": 6700.00 }
]
```

### React Consumption
- `App.tsx` fetches `/mrr.json` on mount
- Passes data to `MrrChart.tsx` (Recharts component)
- Renders a line chart with month labels on X-axis and USD amounts on Y-axis

## 7. Error-State Testing

To manually test the error state (e.g., when JSON fails to load):

Append `?simulate=error` to the URL:
```
http://localhost:5173/?simulate=error
```

The component will display: "Failed to load MRR data. Please refresh the page." (red text, `role="alert"`).

This is useful for verifying error handling without corrupting the data file.

---

## Additional Information

### Tests

```bash
npm test                # Run unit and integration tests
RUN_E2E=1 npm run test:e2e  # Run E2E tests (requires dev server running)
```

### Stack

- **Frontend:** React 18 + TypeScript + Vite
- **Charting:** Recharts
- **Testing:** Vitest + Playwright
- **Build time:** Node.js + @google-cloud/bigquery SDK
- **Hosting:** Static (no backend)

### Troubleshooting

**npm run build-data fails:** Check that `GOOGLE_APPLICATION_CREDENTIALS` points to a valid service account JSON and the account has BigQuery roles on `BQ_DATASET`.

**Dev server won't start:** Verify port 5173 is available or change it in `vite.config.ts`.
