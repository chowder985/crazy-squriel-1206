import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import MrrChart from './MrrChart'
import type { MrrDataPoint } from '../types'

// Recharts' ResponsiveContainer relies on element measurement that jsdom
// doesn't simulate end-to-end (ResizeObserver + layout); the chart ends up
// rendering at zero dimensions and skips dot SVG emission. Replace it with
// a passthrough that gives explicit width/height so the underlying
// LineChart actually paints.
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  const { cloneElement, isValidElement } = await import('react')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => {
      const child = isValidElement(children)
        ? cloneElement(children as ReactElement, { width: 800, height: 400 })
        : children
      return <div style={{ width: 800, height: 400 }}>{child}</div>
    },
  }
})

describe('MrrChart component', () => {
  const mockData: MrrDataPoint[] = [
    { month: '2025-11-01', mrr_amount: 1250 },
    { month: '2025-12-01', mrr_amount: 3400 },
    { month: '2026-01-01', mrr_amount: 3700 },
    { month: '2026-02-01', mrr_amount: 5100 },
    { month: '2026-03-01', mrr_amount: 6700 },
    { month: '2026-04-01', mrr_amount: 6700 },
    { month: '2026-05-01', mrr_amount: 6700 },
  ]

  it('should render the chart title', () => {
    render(<MrrChart data={mockData} />)
    const title = screen.getByText('Monthly Recurring Revenue')
    expect(title).toBeInTheDocument()
  })

  it('should render with 7 data points (dots)', () => {
    const { container } = render(<MrrChart data={mockData} />)
    const dots = container.querySelectorAll('.recharts-line-dots circle')
    expect(dots).toHaveLength(7)
  })

  it('should have an aria-label describing the trend', () => {
    const { container } = render(<MrrChart data={mockData} />)
    const chartContainer = container.querySelector('[aria-label]')
    expect(chartContainer).toBeInTheDocument()
    const ariaLabel = chartContainer?.getAttribute('aria-label')
    expect(ariaLabel).toContain('MRR trend')
    expect(ariaLabel).toContain('2025-11-01')
    expect(ariaLabel).toContain('2026-05-01')
  })

  it('should render without errors with valid data', () => {
    expect(() => render(<MrrChart data={mockData} />)).not.toThrow()
  })

  it('should render ResponsiveContainer for responsiveness', () => {
    const { container } = render(<MrrChart data={mockData} />)
    const responsiveContainer = container.querySelector('div[style*="width"]')
    expect(responsiveContainer).toBeInTheDocument()
  })
})
