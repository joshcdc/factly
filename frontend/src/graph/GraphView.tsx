import { useEffect, useRef, useState } from 'react'
import { Simulation, seed, type SimNode } from './forceSim'
import type { GraphEdge, GraphNode } from '../types/graph'
import NodeGlyph, { CLAIM_RADIUS, NODE_RADIUS } from './shapes'
import fitIcon from '../assets/icons/fit.svg'

export const NODE_COLORS: Record<string, string> = {
  person: '#8fc5ff', organisation: '#57c7b6', company: '#57c7b6', location: '#f2bd5b',
  event: '#c084fc', concept: '#9aa7b3', claim: '#fb7185', source: '#cbd5e1',
}
const STANCE_COLORS: Record<string, string> = { supports: '#4ade80', contradicts: '#f87171', neutral: '#6b7785' }

const MIN_Z = 0.3, MAX_Z = 4
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

type SNode =GraphNode & SimNode
type Picked = { kind: 'node'; item: GraphNode } | { kind: 'edge'; item: GraphEdge } | null

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId?: string
  nodeColor?: (n: GraphNode) => string | undefined
  onSelect: (p: Picked) => void
}

export default function GraphView({ nodes, edges, selectedId, nodeColor, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const gRef = useRef<SVGGElement>(null)
  const sim = useRef<Simulation<SNode> | null>(null)
  const raf = useRef(0)
  const pan = useRef(0) // animation frame of the recentre glide
  const drag = useRef<{ node: SNode | null; panX: number; panY: number; moved: boolean } | null>(null)
  const [, setTick] = useState(0)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [dragId, setDragId] = useState<string | null>(null) // node being dragged right now

  const run = () => {
    cancelAnimationFrame(raf.current)
    const frame = () => {
      const s = sim.current
      if (!s) return
      const settled = s.step(!!drag.current?.node)
      setTick((t) => t + 1)
      if (!settled || drag.current?.node) raf.current = requestAnimationFrame(frame)
    }
    raf.current = requestAnimationFrame(frame)
  }

  // Rebuild the simulation whenever the data changes.
  useEffect(() => {
    const box = svgRef.current!.getBoundingClientRect()
    const w = Math.max(box.width, 640), h = Math.max(box.height, 460)
    const simNodes = seed(nodes.map((n) => ({ ...n, group: n.type })), w, h) as SNode[]
    const byId = new Map(simNodes.map((n) => [n.id, n]))
    const links = edges.flatMap((e) => {
      const source = byId.get(e.source), target = byId.get(e.target)
      return source && target ? [{ source, target }] : []
    })
    sim.current = new Simulation(simNodes, links, w, h)
    setView({ x: 0, y: 0, k: 1 })
    run()
    return () => { cancelAnimationFrame(raf.current); cancelAnimationFrame(pan.current) }
  }, [nodes, edges])

  // Client coords -> graph coords (accounts for pan and zoom).
  const toGraph = (e: React.PointerEvent) => {
    const m = gRef.current!.getScreenCTM()!.inverse()
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m)
    return { x: p.x, y: p.y }
  }

  const onNodeDown = (e: React.PointerEvent, node: SNode) => {
    e.stopPropagation()
    svgRef.current!.setPointerCapture(e.pointerId)
    drag.current = { node, panX: 0, panY: 0, moved: false }
    setDragId(node.id)
    sim.current!.reheat(0.55)
    run()
  }
  const onBgDown = (e: React.PointerEvent) => {
    cancelAnimationFrame(pan.current) // grabbing the canvas stops a recentre in progress
    svgRef.current!.setPointerCapture(e.pointerId)
    drag.current = { node: null, panX: e.clientX, panY: e.clientY, moved: false }
  }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    d.moved = true
    if (d.node) {
      const p = toGraph(e)
      d.node.fx = d.node.x = p.x
      d.node.fy = d.node.y = p.y
      sim.current!.reheat(0.35)
    } else {
      const dx = e.clientX - d.panX, dy = e.clientY - d.panY
      d.panX = e.clientX; d.panY = e.clientY
      setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }))
    }
  }
  const onUp = () => {
    const d = drag.current
    drag.current = null
    setDragId(null)
    if (!d) return
    if (d.node) {
      d.node.fx = d.node.fy = null
      if (!d.moved) onSelect({ kind: 'node', item: d.node })
      sim.current!.reheat(0.65)
      run()
    } else if (!d.moved) {
      onSelect(null)
    }
  }
  // Zoom around the cursor; the layout is not re-run.
  const onWheel = (e: React.WheelEvent) => {
    cancelAnimationFrame(pan.current)
    const box = svgRef.current!.getBoundingClientRect()
    const mx = e.clientX - box.left, my = e.clientY - box.top
    setView((v) => {
      const k = clamp(v.k * (e.deltaY < 0 ? 1.1 : 0.9), MIN_Z, MAX_Z)
      const r = k / v.k
      return { k, x: mx - (mx - v.x) * r, y: my - (my - v.y) * r }
    })
  }


  // Glide the view so the claim (the main node) sits in the middle of the graph area. Zoom level is kept.
  const recentre = () => {
    const main = sim.current?.nodes.find((n) => n.type === 'claim') ?? sim.current?.nodes[0]
    const svg = svgRef.current
    if (!main || !svg) return
    const box = svg.getBoundingClientRect()
    const from = view
    const to = { x: box.width / 2 - from.k * main.x, y: box.height / 2 - from.k * main.y }
    cancelAnimationFrame(pan.current)
    const t0 = performance.now()
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 250), e = 1 - Math.pow(1 - p, 3) // ease-out
      setView({ k: from.k, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e })
      if (p < 1) pan.current = requestAnimationFrame(step)
    }
    pan.current = requestAnimationFrame(step)
  }

  const s = sim.current
  const byId = new Map(s?.nodes.map((n) => [n.id, n]))
  // The dragged node is drawn last, then the selected one, so they and their labels sit in front of everything else.
  const rank = (id: string) => (id === dragId ? 2 : id === selectedId ? 1 : 0)
  const ordered = [...(s?.nodes ?? [])].sort((p, q) => rank(p.id) - rank(q.id))
  return (
    <>
      <svg ref={svgRef} className="graph-svg" onPointerDown={onBgDown} onPointerMove={onMove}
           onPointerUp={onUp} onPointerCancel={onUp} onWheel={onWheel}>
        <g ref={gRef} transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {s && edges.map((e) => {
            const a = byId.get(e.source), b = byId.get(e.target)
            if (!a || !b) return null
            const stance = e.stance ?? 'neutral'
            const sel = selectedId === e.id
            return (
              <g key={e.id} className="edge" onPointerDown={(ev) => ev.stopPropagation()}
                 onClick={() => onSelect({ kind: 'edge', item: e })}>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={STANCE_COLORS[stance]}
                      strokeOpacity={sel ? 1 : 0.3} strokeWidth={1.5} />
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={12} />
              </g>
            )
          })}
          {ordered.map((n) => (
            <g key={n.id} transform={`translate(${n.x} ${n.y})`} className="node"
               onPointerDown={(ev) => onNodeDown(ev, n)}>
              <NodeGlyph r={(n.type === 'claim' ? CLAIM_RADIUS : NODE_RADIUS)} fill={nodeColor?.(n) ?? NODE_COLORS[n.type] ?? '#999'}
                         stroke={selectedId === n.id ? '#fff' : 'rgba(242,245,248,.7)'} strokeWidth={selectedId === n.id ? 3 : 1.5} />
            </g>
          ))}
          {/* Labels sit in their own layer above every node, so a circle can never cover text */}
          {ordered.map((n) => (
            <text key={n.id} x={n.x} y={n.y - (n.type === 'claim' ? CLAIM_RADIUS : NODE_RADIUS) - 6}
                  className={n.type === 'claim' ? 'node-label claim-label' : 'node-label'}>{n.label}</text>
          ))}
        </g>
      </svg>
      <button className="graph-recentre" onClick={recentre} title="Centre the graph on the claim"
              aria-label="Centre the graph on the claim">
        <img src={fitIcon} alt="" />Recentre
      </button>
    </>
  )
}
