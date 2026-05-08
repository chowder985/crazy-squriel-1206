import { BigQuery } from '@google-cloud/bigquery'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

// ESM equivalent of __dirname. The frontend package.json declares
// "type": "module"; CommonJS __dirname is not defined in ESM scopes,
// so derive it from import.meta.url. Sprint 4 iter-1 originally used
// the bare __dirname identifier, which crashed `npm run build` with
// ReferenceError; iter-2 fix.
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

interface MrrDataPoint {
  month: string
  mrr_amount: number
}

async function buildData(): Promise<void> {
  try {
    // Initialize BigQuery client (uses GOOGLE_APPLICATION_CREDENTIALS env var)
    const client = new BigQuery({
      projectId: process.env.GOOGLE_CLOUD_PROJECT,
    })

    // Read the SQL file from project root
    const sqlPath = path.resolve(__dirname, '../../sql/mrr_monthly.sql')
    const sqlTemplate = fs.readFileSync(sqlPath, 'utf-8')

    // Substitute ${dataset} placeholder. The SQL file wraps the placeholder
    // in backticks (e.g., `${dataset}.subscriptions`), so the substituted
    // value MUST NOT add its own backticks — doing so produces an empty
    // identifier (``proj.dataset`.subscriptions`) and BigQuery responds
    // with "Syntax error: Invalid empty identifier". iter-2 fix.
    const dataset = process.env.BQ_DATASET || 'mrr_dev'
    const sql = sqlTemplate.replace(/\$\{dataset\}/g, `${client.projectId}.${dataset}`)

    console.log(`[build-data] Executing MRR monthly query against dataset: ${dataset}`)

    // Execute the query
    const [rows] = await client.query({ query: sql })

    // Transform BigQuery results to JSON format
    const mrrData: MrrDataPoint[] = rows.map((row: Record<string, unknown>) => {
      const month = row.month as unknown
      const mrr_amount = row.mrr_amount as string | number

      // BigQuery returns DATE columns as BigQueryDate { value: 'YYYY-MM-DD' },
      // not as JS Date. iter-1 used `new Date(month).toISOString()` which
      // failed with RangeError because Date can't parse the wrapper. iter-2
      // fix: handle the wrapper's .value, fall back to string/Date paths.
      let monthStr: string
      if (typeof month === 'string') {
        monthStr = month
      } else if (
        month !== null &&
        typeof month === 'object' &&
        'value' in month &&
        typeof (month as { value: unknown }).value === 'string'
      ) {
        monthStr = (month as { value: string }).value
      } else if (month instanceof Date) {
        monthStr = month.toISOString().split('T')[0]
      } else {
        monthStr = String(month)
      }

      // Convert mrr_amount to number (BigQuery NUMERIC can return as string or BigInt wrapper)
      let mrr: number
      if (typeof mrr_amount === 'string') {
        mrr = parseFloat(mrr_amount)
      } else if (typeof mrr_amount === 'number') {
        mrr = mrr_amount
      } else {
        // Handle BigQuery NUMERIC objects that have toString()
        mrr = parseFloat(String(mrr_amount))
      }

      return {
        month: monthStr,
        mrr_amount: mrr,
      }
    })

    // Write to public/mrr.json
    const outputDir = path.resolve(__dirname, '../public')
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true })
    }

    const outputPath = path.join(outputDir, 'mrr.json')
    fs.writeFileSync(outputPath, JSON.stringify(mrrData, null, 2))

    console.log(`[build-data] Successfully wrote ${mrrData.length} rows to ${outputPath}`)
  } catch (err) {
    console.error('[build-data] Error:', err)
    process.exit(1)
  }
}

buildData()
