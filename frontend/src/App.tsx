import { useState } from 'react'
import GraphView, { NODE_COLORS } from './graph/GraphView'
import { investigate } from './services/api'
import type { GraphEdge, GraphNode, Investigation } from './types/graph'
import './App.css'

type Selected = { kind: 'node'; item: GraphNode } | { kind: 'edge'; item: GraphEdge } | null

export default function App() {
  const [query, setQuery] = useState('')
  const [data, setData] = useState<Investigation | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Selected>(null)

  async function run(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim().length < 3) return
    setLoading(true); setError(''); setSelected(null)
    try {
      setData(await investigate(query.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const sources = (ids: string[]) => data?.sources.filter((s) => ids.includes(s.id)) ?? []
  const evidence = (ids: string[]) => data?.evidence.filter((v) => ids.includes(v.id)) ?? []
  // The claim node's id equals its claim_id (AGENT.md hand-off), so this matches directly.
  const assessment = selected?.kind === 'node'
    ? data?.assessments.find((a) => a.claim_id === selected.item.id)
    : undefined
  const types = [...new Set(data?.nodes.map((n) => n.type))]

  return (
    <div className="app">
      <form className="bar" onSubmit={run}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter a claim to fact-check…"
          maxLength={500}
        />
        <button disabled={loading}>{loading ? 'Investigating…' : 'Investigate'}</button>
      </form>
      {error && <p className="error">{error}</p>}

      <div className="main">
        <div className="graph">
          {data ? (
            <>
              <GraphView nodes={data.nodes} edges={data.edges} selectedId={selected?.item.id} onSelect={setSelected} />
              <div className="legend">
                {types.map((t) => (
                  <span key={t}><i style={{ background: NODE_COLORS[t] }} />{t}</span>
                ))}
              </div>
            </>
          ) : (
            <p className="empty">{loading ? 'Investigating…' : 'Enter a claim to build a graph.'}</p>
          )}
        </div>

        {selected && (
          <aside className="panel">
            <h2>{selected.kind === 'node' ? selected.item.label : selected.item.relationship}</h2>
            <p>{selected.item.description}</p>
            {selected.kind === 'node' && <small>Type: {selected.item.type}</small>}
            {assessment && (
              <p>
                <b>{assessment.status.replace('_', ' ')}</b> ({Math.round(assessment.confidence * 100)}% confidence)
                <br />{assessment.explanation}
              </p>
            )}
            {selected.kind === 'edge' && evidence(selected.item.evidence_ids).map((v) => (
              <blockquote key={v.id}>"{v.excerpt}" <small>({v.stance})</small></blockquote>
            ))}
            <h3>Sources</h3>
            {sources(selected.item.source_ids).map((s) => (
              <p key={s.id}>
                <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
                <br /><small>{s.publisher} · credibility {s.credibility_score ?? 'not rated'}/5</small>
              </p>
            ))}
          </aside>
        )}
      </div>
    </div>
  )
}
