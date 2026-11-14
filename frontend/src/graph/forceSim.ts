// Force simulation ported from graph-engine/graph_engine.py (spring links, grid-bucketed
// repulsion, per-group clustering, velocity damping, settle detection).
// Dropped: the Markdown vault parser, folder nodes, HTTP server and DOM code.

export interface SimNode {
  id: string
  group: string
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null // pinned position while dragging
  fy: number | null
}

export interface SimLink<N extends SimNode = SimNode> {
  source: N
  target: N
}

const PADDING = 24
const SETTLED_SPEED = 0.02
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))
const S = {
  springStrength: 0.03,
  springLength: 110,
  maxSpringLength: 300,
  repulsionStrength: 640,
  repulsionLength: 250,
  maxSpeed: 100,
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

function stableAngle(value: string): number {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) / 4294967296) * Math.PI * 2
}

export function clusterCenters(groups: string[], w: number, h: number) {
  const names = [...new Set(groups)].sort()
  const centers = new Map<string, { x: number; y: number }>()
  names.forEach((g, i) => {
    const a = (Math.PI * 2 * i) / names.length - Math.PI / 2
    const spread = names.length > 1
    centers.set(g, { x: w / 2 + (spread ? Math.cos(a) * w * 0.28 : 0), y: h / 2 + (spread ? Math.sin(a) * h * 0.24 : 0) })
  })
  return centers
}

/** Give each node a starting position near its group's cluster centre. */
export function seed<T extends { id: string; group: string }>(items: T[], w: number, h: number): (T & SimNode)[] {
  const centers = clusterCenters(items.map((n) => n.group), w, h)
  const counts = new Map<string, number>()
  return items.map((n) => {
    const i = counts.get(n.group) ?? 0
    counts.set(n.group, i + 1)
    const c = centers.get(n.group)!
    const angle = i * GOLDEN_ANGLE + stableAngle(n.id)
    const r = 14 + Math.sqrt(i + 1) * 12
    return {
      ...n,
      x: clamp(c.x + Math.cos(angle) * r, PADDING, w - PADDING),
      y: clamp(c.y + Math.sin(angle) * r, PADDING, h - PADDING),
      vx: 0, vy: 0, fx: null, fy: null,
    }
  })
}

export class Simulation<N extends SimNode> {
  alpha = 1
  settledFrames = 0
  nodes: N[]
  links: SimLink<N>[]
  width: number
  height: number
  private centers: Map<string, { x: number; y: number }>

  constructor(nodes: N[], links: SimLink<N>[], width: number, height: number) {
    this.nodes = nodes
    this.links = links
    this.width = width
    this.height = height
    this.centers = clusterCenters(nodes.map((n) => n.group), width, height)
  }

  reheat(alpha: number) {
    this.alpha = Math.max(this.alpha, alpha)
    this.settledFrames = 0
  }

  /** Advance one tick. Returns true once the layout has settled. */
  step(dragging: boolean): boolean {
    const alpha = dragging ? Math.max(this.alpha, 0.22) : this.alpha
    this.repel(alpha)
    this.springs(alpha)
    this.attract(alpha)

    let maxV = 0
    for (const n of this.nodes) {
      if (n.fx !== null && n.fy !== null) {
        n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0
        continue
      }
      n.vx *= 0.82
      n.vy *= 0.82
      const speed = Math.hypot(n.vx, n.vy)
      if (speed > S.maxSpeed) { n.vx = (n.vx / speed) * S.maxSpeed; n.vy = (n.vy / speed) * S.maxSpeed }
      n.x = clamp(n.x + n.vx, PADDING, this.width - PADDING)
      n.y = clamp(n.y + n.vy, PADDING, this.height - PADDING)
      maxV = Math.max(maxV, Math.hypot(n.vx, n.vy))
    }
    if (!dragging) this.alpha *= 0.965
    this.settledFrames = !dragging && maxV <= SETTLED_SPEED ? this.settledFrames + 1 : 0
    return this.settledFrames >= 18
  }

  private repel(alpha: number) {
    const cut = S.repulsionLength
    const grid = new Map<string, number[]>()
    this.nodes.forEach((n, i) => {
      const key = `${Math.floor(n.x / cut)},${Math.floor(n.y / cut)}`
      const b = grid.get(key)
      if (b) b.push(i); else grid.set(key, [i])
    })
    this.nodes.forEach((a, i) => {
      const cx = Math.floor(a.x / cut), cy = Math.floor(a.y / cut)
      for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) {
        for (const j of grid.get(`${cx + ox},${cy + oy}`) ?? []) {
          if (j <= i) continue
          const b = this.nodes[j]
          let dx = a.x - b.x, dy = a.y - b.y
          let d2 = dx * dx + dy * dy
          if (d2 >= cut * cut) continue
          if (d2 < 0.01) { const t = stableAngle(a.id + b.id); dx = Math.cos(t) * 0.1; dy = Math.sin(t) * 0.1; d2 = 0.01 }
          const falloff = 1 - Math.sqrt(d2) / cut
          const f = (S.repulsionStrength / Math.max(d2, 64)) * falloff * alpha * 0.08
          if (a.fx === null) { a.vx += dx * f; a.vy += dy * f }
          if (b.fx === null) { b.vx -= dx * f; b.vy -= dy * f }
        }
      }
    })
  }

  private springs(alpha: number) {
    for (const { source: a, target: b } of this.links) {
      const dx = b.x - a.x, dy = b.y - a.y
      const d = Math.hypot(dx, dy) || 1
      const f = (d - S.springLength) * S.springStrength * alpha * 0.35 + Math.max(0, d - S.maxSpringLength) * S.springStrength * alpha * 1.4
      if (a.fx === null) { a.vx += (dx / d) * f; a.vy += (dy / d) * f }
      if (b.fx === null) { b.vx -= (dx / d) * f; b.vy -= (dy / d) * f }
    }
  }

  private attract(alpha: number) {
    for (const n of this.nodes) {
      if (n.fx !== null) continue
      const c = this.centers.get(n.group) ?? { x: this.width / 2, y: this.height / 2 }
      n.vx += (c.x - n.x) * 0.00045 * alpha + (this.width / 2 - n.x) * 0.00012 * alpha
      n.vy += (c.y - n.y) * 0.00045 * alpha + (this.height / 2 - n.y) * 0.00012 * alpha
    }
  }
}
