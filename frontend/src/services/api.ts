import type { Investigation } from '../types/graph'
import { mockInvestigation } from './mock'

// Mock data is the default. Set VITE_USE_MOCK=false in frontend/.env to use the backend.
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const POLL_MS = 1500
const TIMEOUT_MS = 180_000

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function json(res: Response): Promise<Investigation> {
  if (!res.ok) throw new Error(`Request failed (${res.status})`)
  return res.json()
}

/** Start an investigation, then poll until the backend reports it complete or failed. */
export async function investigate(
  query: string,
  onUpdate?: (inv: Investigation) => void,
): Promise<Investigation> {
  if (USE_MOCK) {
    await sleep(600)
    return { ...mockInvestigation, query }
  }
  let inv = await json(await fetch('/api/investigate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  }))
  const deadline = Date.now() + TIMEOUT_MS
  while (inv.status === 'running') {
    if (Date.now() > deadline) throw new Error('Investigation timed out')
    await sleep(POLL_MS)
    inv = await json(await fetch(`/api/investigate/${inv.investigation_id}`))
    onUpdate?.(inv)
  }
  if (inv.status === 'failed') throw new Error(inv.error ?? 'Investigation failed')
  return inv
}
