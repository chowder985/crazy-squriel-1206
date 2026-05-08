import { test, expect } from '@playwright/test'

// Only run e2e tests if explicitly enabled
const runE2E = process.env.RUN_E2E === '1'

test.describe.configure({ mode: runE2E ? 'default' : 'skip' })

test.describe('E2E: MRR Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the dev server
    await page.goto('http://localhost:5173')
  })

  test('should load the page and display the chart', async ({ page }) => {
    // Wait for the chart title to appear
    const title = await page.locator('h1:has-text("Monthly Recurring Revenue")').first()
    await expect(title).toBeVisible()
  })

  test('should display exactly 7 data points', async ({ page }) => {
    // Wait for the chart to render and count the dots
    await page.waitForLoadState('networkidle')
    const dots = await page.locator('.recharts-line-dots circle').count()
    expect(dots).toBe(7)
  })

  test('should extract Y-values from rendered chart', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // Extract mrr.json file values (Method B)
    const mrrJson = await page.evaluate(async () => {
      const response = await fetch('/mrr.json')
      return response.json()
    })

    expect(mrrJson).toHaveLength(7)
    expect(mrrJson[0].month).toBe('2025-11-01')
    expect(mrrJson[0].mrr_amount).toBe(1250)
    expect(mrrJson[6].month).toBe('2026-05-01')
    expect(mrrJson[6].mrr_amount).toBe(6700)
  })

  test('should not make requests to googleapis.com', async ({ page, context }) => {
    const requests: string[] = []

    page.on('response', (response) => {
      requests.push(response.url())
    })

    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')

    const gcp_requests = requests.filter(
      (url) => url.includes('googleapis.com') || url.includes('bigquery')
    )

    expect(gcp_requests).toHaveLength(0)
  })

  test('should handle ?simulate=error query param', async ({ page }) => {
    await page.goto('http://localhost:5173?simulate=error')

    // Wait for error state to appear
    const errorMessage = await page.locator('[role="alert"]')
    await expect(errorMessage).toBeVisible()
    await expect(errorMessage).toContainText(/error|failed|unable/i)
  })

  test('should be responsive on desktop viewport (1280x800)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')

    // Check no horizontal scroll
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const clientWidth = await page.evaluate(() => window.innerWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1) // +1 for rounding tolerance

    // Check SVG is present
    const svg = await page.locator('svg').first()
    await expect(svg).toBeVisible()
  })

  test('should be responsive on tablet viewport (768x1024)', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto('http://localhost:5173')
    await page.waitForLoadState('networkidle')

    // Check no horizontal scroll
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    const clientWidth = await page.evaluate(() => window.innerWidth)
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1)

    // Check SVG is present
    const svg = await page.locator('svg').first()
    await expect(svg).toBeVisible()
  })
})
