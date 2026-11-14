import type { GraphEdge, GraphNode, Investigation } from '../types/graph'

const NAMES = [
  'Microsoft', 'OpenAI', 'Google', 'Amazon', 'Nvidia', 'Meta', 'Apple', 'Tesla', 'Anthropic', 'Intel',
  'Sam Altman', 'Satya Nadella', 'Sundar Pichai', 'Jensen Huang', 'Elon Musk', 'Mark Zuckerberg', 'Tim Cook', 'Dario Amodei', 'Lisa Su', 'Andy Jassy',
  'Azure', 'AWS', 'Gemini', 'ChatGPT', 'Claude', 'CUDA', 'LLaMA', 'Copilot', 'Starlink', 'Autopilot',
  'Seattle', 'San Francisco', 'Redmond', 'Mountain View', 'Cupertino', 'Santa Clara', 'Austin', 'London', 'Taipei', 'Palo Alto',
  'AI Act', 'Chip export ban', 'Board dispute', 'Funding round', 'Antitrust probe', 'Product launch', 'Data centre build', 'IPO filing', 'Merger talks', 'Leadership change',
  'TSMC', 'AMD', 'Oracle', 'IBM', 'Salesforce', 'Samsung', 'SoftBank', 'Mistral', 'xAI', 'DeepMind',
]

/** Random graph with random priorities, to check zoom levels and frame rate. Open the app with ?fake=60. */
export function fakeInvestigation(count: number): Investigation {
  const types = ['person', 'company', 'concept', 'location', 'event']
  const nodes: GraphNode[] = Array.from({ length: count }, (_, i) => ({
    id: `entity_${i}`, type: types[i % types.length] as GraphNode['type'], label: NAMES[i % NAMES.length],
    description: `Fake node ${i}`, properties: { priority: Math.round(Math.random() * 100) / 100 }, source_ids: [],
  }))
  const edges: GraphEdge[] = Array.from({ length: count * 2 }, (_, i) => {
    const s = Math.floor(Math.random() * count)
    const t = (s + 1 + Math.floor(Math.random() * (count - 1))) % count
    return {
      id: `edge_${i}`, source: `entity_${s}`, target: `entity_${t}`,
      relationship: i % 11 === 0 ? 'mentioned with' : i % 7 === 0 ? 'alleged owns' : 'partners with',
      stance: null, description: '', evidence_ids: [], source_ids: [], weight: Math.round(Math.random() * 100) / 100,
    }
  })
  return {
    investigation_id: 'fake', query: `Fake graph (${count} nodes)`, status: 'complete', error: null,
    nodes, edges, sources: [], evidence: [], assessments: [],
  }
}
