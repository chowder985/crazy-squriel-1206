import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    // tests/ is the Playwright e2e directory — different runner, different
    // imports (@playwright/test). Vitest must skip it.
    exclude: ['**/node_modules/**', '**/dist/**', 'tests/**'],
  },
})
