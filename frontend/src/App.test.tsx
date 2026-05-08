import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import App from './App'
import type { MrrDataPoint } from './types'

const mockData: MrrDataPoint[] = [
  { month: '2025-11-01', mrr_amount: 1250 },
  { month: '2025-12-01', mrr_amount: 3400 },
  { month: '2026-01-01', mrr_amount: 3700 },
  { month: '2026-02-01', mrr_amount: 5100 },
  { month: '2026-03-01', mrr_amount: 6700 },
  { month: '2026-04-01', mrr_amount: 6700 },
  { month: '2026-05-01', mrr_amount: 6700 },
]

describe('App component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render loading state initially', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {}))) // Never resolves
    render(<App />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('should render chart after data loads', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => mockData,
      } as Response)
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Monthly Recurring Revenue')).toBeInTheDocument()
    })
  })

  it('should render error state on fetch failure', async () => {
    global.fetch = vi.fn(() =>
      Promise.reject(new Error('Network error'))
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load MRR data/)).toBeInTheDocument()
    })
  })

  it('should render error state when simulate=error query param is set', async () => {
    // Mock window.location.search
    delete (window as Partial<Window>).location
    window.location = { search: '?simulate=error' } as Location

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load MRR data/)).toBeInTheDocument()
    })
  })

  it('should render error state on non-200 response', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 404,
      } as Response)
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load MRR data/)).toBeInTheDocument()
    })
  })

  it('should render empty state when data array is empty', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => [],
      } as Response)
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('No data to display.')).toBeInTheDocument()
    })
  })

  it('should have alert role on error message', async () => {
    global.fetch = vi.fn(() =>
      Promise.reject(new Error('Network error'))
    )

    render(<App />)

    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert).toBeInTheDocument()
    })
  })

  it('should have status role on loading message', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    render(<App />)
    const status = screen.getByRole('status')
    expect(status).toBeInTheDocument()
  })
})
