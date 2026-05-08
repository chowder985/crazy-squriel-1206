import { useEffect, useState } from 'react'
import type { MrrDataPoint, LoadingState } from './types'
import MrrChart from './components/MrrChart'

function App(): JSX.Element {
  const [data, setData] = useState<MrrDataPoint[]>([])
  const [state, setState] = useState<LoadingState>('loading')

  useEffect(() => {
    const loadData = async () => {
      try {
        // Check if error simulation is requested
        const params = new URLSearchParams(window.location.search)
        if (params.get('simulate') === 'error') {
          setState('error')
          return
        }

        const response = await fetch('/mrr.json')
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        const jsonData = await response.json() as MrrDataPoint[]

        if (!Array.isArray(jsonData) || jsonData.length === 0) {
          setState('empty')
          return
        }

        setData(jsonData)
        setState('success')
      } catch (err) {
        console.error('Failed to load MRR data:', err)
        setState('error')
      }
    }

    loadData()
  }, [])

  if (state === 'loading') {
    return (
      <div style={{ padding: '24px' }} role="status">
        Loading...
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div
        style={{
          padding: '24px',
          color: '#EF4444',
          fontSize: '16px',
        }}
        role="alert"
      >
        Failed to load MRR data. Please refresh the page.
      </div>
    )
  }

  if (state === 'empty') {
    return (
      <div style={{ padding: '24px' }}>
        No data to display.
      </div>
    )
  }

  return <MrrChart data={data} />
}

export default App
