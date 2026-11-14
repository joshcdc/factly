// Every node is the same small circle; node type is told apart by colour only.

interface Props { r?: number; fill: string; stroke?: string; strokeWidth?: number }

export const NODE_RADIUS = 6

export default function NodeGlyph({ r = NODE_RADIUS, fill, stroke = 'rgba(242,245,248,.7)', strokeWidth = 1.5 }: Props) {
  return <circle r={r} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
}
