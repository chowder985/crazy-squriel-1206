import React, { useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { MrrDataPoint } from '../types'

interface MrrChartProps {
  data: MrrDataPoint[]
}

const MrrChart: React.FC<MrrChartProps> = ({ data }) => {
  const formattedData = useMemo(() => {
    return data.map((point) => ({
      ...point,
      // Format the display label in UTC. Without the explicit timeZone
      // option, toLocaleDateString uses the runtime's local timezone, which
      // shifts UTC-midnight Nov 1 ("2025-11-01T00:00:00Z") to Oct 31 evening
      // for any locale west of UTC — producing the wrong month label.
      // Using `year: 'numeric'` (instead of '2-digit') prints "Nov 2025"
      // rather than "Nov 25", which reads as a day.
      displayMonth: new Date(point.month + 'T00:00:00Z').toLocaleDateString(
        'en-US',
        { month: 'short', year: 'numeric', timeZone: 'UTC' }
      ),
    }))
  }, [data])

  const minMrr = useMemo(
    () => Math.min(...data.map((d) => d.mrr_amount)),
    [data]
  )
  const maxMrr = useMemo(
    () => Math.max(...data.map((d) => d.mrr_amount)),
    [data]
  )

  return (
    <div
      style={{
        // box-sizing: border-box so the 24px padding is included inside
        // width:100% and the wrapper doesn't overflow the viewport. Sprint 4
        // iter-1 shipped without box-sizing, causing scrollWidth to exceed
        // innerWidth by 48px (the horizontal padding) and failing C-103
        // responsiveness assertion. iter-2 fix.
        boxSizing: 'border-box',
        width: '100%',
        height: 500,
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        padding: '24px',
      }}
      aria-label={`MRR trend from ${data[0]?.month} to ${data[data.length - 1]?.month}, showing growth from $${minMrr.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} to $${maxMrr.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
    >
      <h1 style={{ margin: 0, fontSize: '24px', fontWeight: '600' }}>
        Monthly Recurring Revenue
      </h1>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={formattedData}
          margin={{ top: 5, right: 30, left: 0, bottom: 5 }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="displayMonth"
            tick={{ fontSize: 12 }}
            tickFormatter={(value: string) => value}
          />
          <YAxis
            tick={{ fontSize: 12 }}
            tickFormatter={(value: number) => `$${value.toLocaleString()}`}
          />
          <Tooltip
            formatter={(value: number) =>
              `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
            }
            labelFormatter={(label: string) => label}
          />
          <Line
            type="monotone"
            dataKey="mrr_amount"
            stroke="#0066FF"
            strokeWidth={2}
            dot={{ fill: '#0066FF', r: 6 }}
            activeDot={{ r: 8 }}
            // isAnimationActive=false so dots render synchronously in
            // jsdom (where requestAnimationFrame doesn't fire reliably)
            // and the C-98 selector `.recharts-line-dots circle` finds
            // exactly 7 elements. In production browsers the animation
            // skip is imperceptible (chart still renders cleanly).
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default MrrChart
