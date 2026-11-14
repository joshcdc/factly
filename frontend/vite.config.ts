import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Forward /api calls to the FastAPI backend (Agent 1) when VITE_USE_MOCK=false.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
