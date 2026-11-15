import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Forward /api calls to the FastAPI backend.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
