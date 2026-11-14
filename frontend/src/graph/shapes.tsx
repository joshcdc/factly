import type { ReactNode } from 'react'

// Shape per node type, so type is never conveyed by colour alone.
// Drawn centred on (0, 0); `r` is the node radius in px.

const hex = (r: number) =>
  [0, 1, 2, 3, 4, 5].map((i) => `${(r * Math.cos(Math.PI / 3 * i)).toFixed(1)},${(r * Math.sin(Math.PI / 3 * i)).toFixed(1)}`).join(' ')

function outline(type: string, r: number, p: Record<string, unknown>): ReactNode {
  switch (type) {
    case 'claim': return <polygon points={hex(r)} {...p} />
    case 'company': return <rect x={-r} y={-r} width={2 * r} height={2 * r} rx={r * 0.3} {...p} />
    case 'location':
      return <path d={`M0 ${r} L${-r * 0.85} ${-r * 0.2} A${r} ${r} 0 1 1 ${r * 0.85} ${-r * 0.2} Z`} {...p} />
    case 'event': return <polygon points={`0,${-r * 1.15} ${r * 1.15},0 0,${r * 1.15} ${-r * 1.15},0`} {...p} />
    case 'concept': return <circle r={r} {...p} strokeDasharray="3 2.5" />
    case 'source':
      return <path d={`M${-r * 0.7} ${-r} H${r * 0.3} L${r * 0.7} ${-r * 0.5} V${r} H${-r * 0.7} Z`} {...p} />
    default: return <circle r={r} {...p} /> // person
  }
}

interface Props { type: string; r: number; fill: string; stroke?: string; strokeWidth?: number }

export default function NodeGlyph({ type, r, fill, stroke = 'rgba(242,245,248,.7)', strokeWidth = 1.5 }: Props) {
  return (
    <>
      {outline(type, r, { fill, stroke, strokeWidth })}
    </>
  )
}

/** Node radius: claim largest, others grow with the number of sources behind them. */
export const nodeRadius = (type: string, sourceCount: number) =>
  type === 'claim' ? 18 : type === 'source' ? 10 : 9 + Math.min(sourceCount, 4) * 1.5
