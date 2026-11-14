// Mirrors the shared data contract in AGENT.md section 3.

export type NodeType =
  | 'person' | 'organisation' | 'company' | 'location'
  | 'event' | 'concept' | 'claim' | 'source'

export interface Source {
  id: string
  url: string
  title: string
  publisher: string
  published_at: string | null
  content: string
  source_type: string
  credibility_score: number | null
  relevance_score: number
}

export interface GraphNode {
  id: string
  type: NodeType
  label: string
  description: string
  properties: Record<string, unknown>
  source_ids: string[]
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  relationship: string
  stance: 'supports' | 'contradicts' | 'neutral' | null
  description: string
  evidence_ids: string[]
  source_ids: string[]
}

export interface Evidence {
  id: string
  claim_id: string
  source_id: string
  stance: 'supports' | 'contradicts' | 'neutral'
  excerpt: string
  reasoning: string
  strength: number
}

export interface Assessment {
  claim_id: string
  status: 'supported' | 'partially_supported' | 'contradicted' | 'insufficient_evidence'
  confidence: number
  supporting_evidence: string[]
  contradicting_evidence: string[]
  explanation: string
}

export interface Investigation {
  investigation_id: string
  query: string
  status: 'running' | 'complete' | 'failed'
  error: string | null
  nodes: GraphNode[]
  edges: GraphEdge[]
  sources: Source[]
  evidence: Evidence[]
  assessments: Assessment[]
}



