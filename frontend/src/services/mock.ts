import type { Investigation } from '../types/graph'

export const mockInvestigation: Investigation = {
  investigation_id: 'mock_1',
  status: 'complete',
  error: null,
  query: 'Microsoft controls OpenAI',
  nodes: [
    { id: 'e1', type: 'company', label: 'Microsoft', description: 'Technology company and OpenAI investor.', properties: {}, source_ids: ['s1'] },
    { id: 'e2', type: 'company', label: 'OpenAI', description: 'AI research company.', properties: {}, source_ids: ['s1', 's2'] },
    { id: 'e3', type: 'person', label: 'Sam Altman', description: 'CEO of OpenAI.', properties: {}, source_ids: ['s2'] },
    { id: 'c1', type: 'claim', label: 'Microsoft controls OpenAI', description: 'The claim under investigation.', properties: {}, source_ids: ['s1', 's2'] },
  ],
  edges: [
    { id: 'r1', source: 'e1', target: 'e2', relationship: 'invested in', stance: null, description: 'Microsoft is a major investor.', evidence_ids: ['ev1'], source_ids: ['s1'] },
    { id: 'r2', source: 'e3', target: 'e2', relationship: 'leads', stance: null, description: 'Altman is CEO.', evidence_ids: [], source_ids: ['s2'] },
    { id: 'r3', source: 'c1', target: 'e1', relationship: 'supported by', stance: 'supports', description: 'Partial support.', evidence_ids: ['ev1'], source_ids: ['s1'] },
    { id: 'r4', source: 'c1', target: 'e2', relationship: 'contradicted by', stance: 'contradicts', description: 'OpenAI is governed by its own board.', evidence_ids: ['ev2'], source_ids: ['s2'] },
  ],
  sources: [
    { id: 's1', url: 'https://example.com/a', title: 'Microsoft invests in OpenAI', publisher: 'Example News', published_at: '2026-01-01', content: '', source_type: 'news', credibility_score: 4, relevance_score: 5 },
    { id: 's2', url: 'https://example.com/b', title: 'OpenAI governance explained', publisher: 'Example Review', published_at: '2026-02-01', content: '', source_type: 'analysis', credibility_score: 5, relevance_score: 4 },
  ],
  evidence: [
    { id: 'ev1', claim_id: 'c1', source_id: 's1', stance: 'supports', excerpt: 'Microsoft has invested billions in OpenAI.', reasoning: 'Large investment suggests influence.', strength: 3 },
    { id: 'ev2', claim_id: 'c1', source_id: 's2', stance: 'contradicts', excerpt: 'OpenAI is governed by its own board.', reasoning: 'Independent governance contradicts control.', strength: 4 },
  ],
  assessments: [
    { claim_id: 'c1', status: 'partially_supported', confidence: 0.6, supporting_evidence: ['ev1'], contradicting_evidence: ['ev2'], explanation: 'Microsoft has major influence but does not control OpenAI.' },
  ],
}

