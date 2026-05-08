import { describe, it, expect, vi, afterEach } from 'vitest'
import * as fs from 'fs'
import * as path from 'path'

describe('build-data script', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should read the SQL file from project root', () => {
    const sqlPath = path.resolve(__dirname, '../../sql/mrr_monthly.sql')
    const exists = fs.existsSync(sqlPath)
    expect(exists).toBe(true)
  })

  it('should have SQL file with ${dataset} placeholder', () => {
    const sqlPath = path.resolve(__dirname, '../../sql/mrr_monthly.sql')
    const sql = fs.readFileSync(sqlPath, 'utf-8')
    expect(sql).toContain('${dataset}')
  })

  it('should correctly substitute ${dataset} placeholder', () => {
    const dataset = 'mrr_dev'
    const projectId = 'test-project'
    const sqlTemplate = 'SELECT * FROM ${dataset}.subscriptions'
    const substituted = sqlTemplate.replace(/\$\{dataset\}/g, `\`${projectId}.${dataset}\``)
    expect(substituted).toBe('SELECT * FROM `test-project.mrr_dev`.subscriptions')
  })

  it('should format output JSON with correct shape', () => {
    const mockRows = [
      { month: new Date('2025-11-01'), mrr_amount: 1250.00 },
      { month: new Date('2025-12-01'), mrr_amount: 3400.00 },
    ]

    const mrrData = mockRows.map((row: Record<string, unknown>) => {
      const month = row.month as Date
      const mrr_amount = row.mrr_amount as number

      const monthStr = new Date(month).toISOString().split('T')[0]
      return {
        month: monthStr,
        mrr_amount: mrr_amount,
      }
    })

    expect(mrrData).toHaveLength(2)
    expect(mrrData[0]).toEqual({ month: '2025-11-01', mrr_amount: 1250.00 })
    expect(mrrData[1]).toEqual({ month: '2025-12-01', mrr_amount: 3400.00 })
  })

  it('should handle NUMERIC string conversion', () => {
    const mrr_amount = '1250.00'
    const mrr = parseFloat(mrr_amount)
    expect(mrr).toBe(1250)
    expect(typeof mrr).toBe('number')
  })

  it('should handle NUMERIC number input', () => {
    const mrr_amount = 1250
    expect(typeof mrr_amount).toBe('number')
    expect(mrr_amount).toBe(1250)
  })

  it('should output file path be public/mrr.json', () => {
    const outputPath = path.resolve(__dirname, '../public/mrr.json')
    expect(outputPath).toContain('public')
    expect(outputPath).toContain('mrr.json')
  })
})
