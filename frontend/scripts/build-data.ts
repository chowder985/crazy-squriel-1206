import { BigQuery } from '@google-cloud/bigquery'
import * as fs from 'fs'
import * as path from 'path'

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

    // Substitute ${dataset} placeholder with env var (default: mrr_dev)
    const dataset = process.env.BQ_DATASET || 'mrr_dev'
    const sql = sqlTemplate.replace(/\$\{dataset\}/g, `\`${client.projectId}.${dataset}\``)

    console.log(`[build-data] Executing MRR monthly query against dataset: ${dataset}`)

    // Execute the query
    const [rows] = await client.query({ query: sql })

    // Transform BigQuery results to JSON format
    const mrrData: MrrDataPoint[] = rows.map((row: Record<string, unknown>) => {
      const month = row.month as string | Date
      const mrr_amount = row.mrr_amount as string | number

      // Convert month to ISO string if it's a Date object
      const monthStr = typeof month === 'string' ? month : new Date(month).toISOString().split('T')[0]

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
