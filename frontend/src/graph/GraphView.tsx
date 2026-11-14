import { useEffect, useRef, useState } from 'react'
import { Simulation, seed, type SimNode } from './forceSim'
import type { GraphEdge, GraphNode } from '../types/graph'
import NodeGlyph, { NODE_RADIUS } from './shapes'

export const NODE_COLORS: Record<string, string> = {
  person: '#8fc5ff', organisation: '#57c7b6', company: '#57c7b6', location: '#f2bd5b',
  event: '#c084fc', concept: '#9aa7b3', claim: '#fb7185', source: '#cbd5e1',
}
const STANCE_COLORS: Record<string, string> = { supports: '#4ade80', contradicts: '#f87171', neutral: '#6b7785' }

/** supports: solid; contradicts: dashed; claim "about" links: thin dotted; entity relations: solid grey. */
const edgeDash = (e: GraphEdge) =>
  e.stance === 'contradicts' ? '7 4' : e.relationship === 'about' ? '2 4' : undefined

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
  const drag = useRef<{ node: SNode | null; panX: number; panY: number; moved: boolean } | null>(null)
  const [, setTick] = useState(0)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })

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
    return () => cancelAnimationFrame(raf.current)
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
    sim.current!.reheat(0.55)
    run()
  }
  const onBgDown = (e: React.PointerEvent) => {
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
  const onWheel = (e: React.WheelEvent) => {
    const k = Math.min(4, Math.max(0.3, view.k * (e.deltaY < 0 ? 1.1 : 0.9)))
    setView((v) => ({ ...v, k }))
  }

  const s = sim.current
  return (
    <svg ref={svgRef} className="graph-svg" onPointerDown={onBgDown} onPointerMove={onMove}
         onPointerUp={onUp} onPointerCancel={onUp} onWheel={onWheel}>
      <defs>
        {Object.entries(STANCE_COLORS).map(([k, c]) => (
          <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="14" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 0L10 5L0 10z" fill={c} />
          </marker>
        ))}
      </defs>
      <g ref={gRef} transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
        {s && edges.map((e) => {
          const a = s.nodes.find((n) => n.id === e.source), b = s.nodes.find((n) => n.id === e.target)
          if (!a || !b) return null
          const stance = e.stance ?? 'neutral'
          const label = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
          return (
            <g key={e.id} className="edge" onPointerDown={(ev) => ev.stopPropagation()}
               onClick={() => onSelect({ kind: 'edge', item: e })}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={STANCE_COLORS[stance]}
                    strokeOpacity={selectedId === e.id ? 1 : 0.55} strokeWidth={selectedId === e.id ? 3 : 1.5}
                    strokeDasharray={edgeDash(e)}
                    markerEnd={`url(#arrow-${stance})`} />
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={12} />
              <text x={label.x} y={label.y} className="edge-label">{e.relationship}</text>
            </g>
          )
        })}
        {s?.nodes.map((n) => (
          <g key={n.id} transform={`translate(${n.x} ${n.y})`} className="node"
             onPointerDown={(ev) => onNodeDown(ev, n)}>
            <NodeGlyph fill={nodeColor?.(n) ?? NODE_COLORS[n.type] ?? '#999'}
                       stroke={selectedId === n.id ? '#fff' : 'rgba(242,245,248,.7)'} strokeWidth={selectedId === n.id ? 3 : 1.5} />
            <text y={-NODE_RADIUS - 6} className="node-label">{n.label}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}
