import { useMemo, useState } from 'react'
import GraphView, { NODE_COLORS } from './graph/GraphView'
import NodeGlyph from './graph/shapes'
import { investigate } from './services/api'
import type { GraphEdge, GraphNode, Investigation } from './types/graph'
import factlySymbol from './assets/factly-symbol.svg'
import plusIcon from './assets/icons/plus.svg'
import graphIcon from './assets/icons/graph.svg'
import graphSmallIcon from './assets/icons/graph-small.svg'
import infoIcon from './assets/icons/info.svg'
import infoSmallIcon from './assets/icons/info-small.svg'
import closePanelIcon from './assets/icons/close-panel.svg'
import arrowIcon from './assets/icons/arrow.svg'
import docIcon from './assets/icons/doc.svg'
import './App.css'

type Selected = { kind: 'node'; item: GraphNode } | { kind: 'edge'; item: GraphEdge } | null

const STATUS_COLORS: Record<string, string> = {
  supported: '#4ade80', partially_supported: '#f2bd5b', contradicted: '#f87171', insufficient_evidence: '#9aa7b3',
}

const STATUS_LABEL: Record<string, string> = {
  supported: 'Supported',
  partially_supported: 'Partially supported',
  contradicted: 'Contradicted',
  insufficient_evidence: 'Insufficient evidence',
}

export default function App() {
  const [query, setQuery] = useState('')
  const [data, setData] = useState<Investigation | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState<Selected>(null)
  const [sourcesOpen, setSourcesOpen] = useState(false)

  async function run(e: React.FormEvent) {
    e.preventDefault()
    if (query.trim().length < 3) return
    setLoading(true); setError(''); setPicked(null)
    try {
      setData(await investigate(query.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const sources = (ids: string[]) => data?.sources.filter((s) => ids.includes(s.id)) ?? []
  // The claim node is drawn (coloured by its status); until something else is picked its details fill the inspector.
  const claimNode = data?.nodes.find((n) => n.type === 'claim')
  const selected: Selected = picked ?? (claimNode ? { kind: 'node', item: claimNode } : null)

  // The claim node's id equals its claim_id (AGENT.md hand-off), so this matches directly.
  const assessment = selected?.kind === 'node'
    ? data?.assessments.find((a) => a.claim_id === selected.item.id)
    : undefined
  // Source nodes are hidden by default (AGENT.md); their details appear in the inspector instead.
  const graph = useMemo(() => {
    const nodes = data?.nodes.filter((n) => n.type !== 'source') ?? []
    const ids = new Set(nodes.map((n) => n.id))
    const edges = data?.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) ?? []
    return { nodes, edges }
  }, [data])
  // The legend swatch for the claim uses the same status colour as the claim node itself.
  const legendColor = (t: string) => {
    const claim = t === 'claim' ? graph.nodes.find((n) => n.type === 'claim') : undefined
    return (claim && claimColor(claim)) || NODE_COLORS[t] || '#999'
  }
  const claimColor = (n: GraphNode) => {
    const a = n.type === 'claim' ? data?.assessments.find((x) => x.claim_id === n.id) : undefined
    return a && STATUS_COLORS[a.status]
  }
  // Sources for whatever is shown: every source for the claim (with its stance), otherwise the item's own source_ids.
  const isClaim = selected?.kind === 'node' && selected.item.type === 'claim'
  const listed = (isClaim ? data?.sources ?? [] : sources(selected?.item.source_ids ?? [])).map((s) => ({
    source: s,
    stance: isClaim
      ? data?.edges.find((e) => e.source === s.id && e.target === selected.item.id)?.stance
        ?? data?.evidence.find((v) => v.source_id === s.id && v.claim_id === selected.item.id)?.stance
      : undefined,
    quotes: data?.evidence.filter((v) => v.source_id === s.id && (isClaim ? v.claim_id === selected?.item.id : selected?.kind === 'edge' && selected.item.evidence_ids.includes(v.id))) ?? [],
  }))
  const node = (id: string) => data?.nodes.find((n) => n.id === id)
  const label = (id: string) => node(id)?.label ?? id
  const types = [...new Set(graph.nodes.map((n) => n.type))]

  // Nodes linked to the selected node, with the relationship that links them.
  const connected = selected?.kind === 'node'
    ? (data?.edges ?? []).flatMap((e) => {
        const otherId = e.source === selected.item.id ? e.target : e.target === selected.item.id ? e.source : null
        const other = otherId ? graph.nodes.find((n) => n.id === otherId) : undefined
        return other ? [{ edge: e, other }] : []
      })
    : []

  const heading = selected?.kind === 'node'
    ? selected.item.label
    : selected
      ? `${label(selected.item.source)} ${selected.item.relationship} ${label(selected.item.target)}`
      : ''

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-symbol" src={factlySymbol} alt="" />
          <span className="brand-name">factly</span>
          <span className="badge-beta">BETA</span>
        </div>

        <button className="btn-primary new-check" onClick={() => document.getElementById('claim-input')?.focus()}>
          <img src={plusIcon} alt="" /> New fact-check
        </button>

        <nav className="nav">
          <a className="nav-item active" aria-current="page"><img src={graphIcon} alt="" />Connections</a>
        </nav>

        {data && (
          <section className="networks">
            <h3 className="eyebrow">YOUR NETWORKS</h3>
            <div className="network-item"><img src={graphSmallIcon} alt="" />{data.query}</div>
            <p className="meta">{graph.nodes.length} nodes · {graph.edges.length} connections</p>
          </section>
        )}

        <div className="sidebar-bottom">
          <div className="notice">
            <img src={infoIcon} alt="" />
            <strong>Example workspace</strong>
            <p>Relationships shown here are illustrative and unverified.</p>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="workspace-head">
          <div>
            <p className="eyebrow">FOLLOW THE CONNECTIONS</p>
            <h1>See the bigger picture.</h1>
            <p className="subtitle">Explore who and what sits behind a claim.</p>
          </div>
        </header>

        <form className="claim-form" onSubmit={run}>
          <input
            id="claim-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter a claim to fact-check…"
            maxLength={500}
          />
          <button className="btn-primary" disabled={loading}>{loading ? 'Investigating…' : 'Investigate'}</button>
        </form>
        {error && <p className="error">{error}</p>}

        <div className="content">
          <div className="graph-col">
            <div className="graph">
              {data ? (
                <>
                  <GraphView nodes={graph.nodes} edges={graph.edges} nodeColor={claimColor} selectedId={picked?.item.id} onSelect={setPicked} />
                  <p className="graph-count">{graph.nodes.length} nodes / {graph.edges.length} connections</p>
                  <ul className="legend">
                    {types.map((t) => (
                      <li key={t}>
                        <svg width="22" height="22" viewBox="-11 -11 22 22"><NodeGlyph fill={legendColor(t)} /></svg>{t}
                      </li>
                    ))}
                    <li><svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke="#6b7785" strokeWidth="2" /></svg>relation</li>
                  </ul>
                  <p className="graph-help">Drag to explore · Select a node or connection</p>
                </>
              ) : (
                <p className="empty">{loading ? 'Investigating…' : 'Enter a claim to build a graph.'}</p>
              )}
            </div>
          </div>

          <aside className="inspector">
            <div className="inspector-head">
              <h2>{selected?.kind === 'edge' ? 'Connection details' : 'Claim details'}</h2>
              {picked && (
                <button className="icon-btn" aria-label="Close details" onClick={() => setPicked(null)}>
                  <img src={closePanelIcon} alt="" />
                </button>
              )}
            </div>

            {selected ? (
              <>
                <div className="selected">
                  <div className="selected-status">
                    <span className="eyebrow">{selected.kind === 'node' ? `SELECTED ${selected.item.type.toUpperCase()}` : 'SELECTED CONNECTION'}</span>
                    {selected.kind === 'edge' && selected.item.stance && (
                      <span className={`status ${selected.item.stance}`}>{selected.item.stance}</span>
                    )}
                  </div>
                  <h3 className="selected-title">{heading}</h3>
                  {isClaim && (
                    <div className={`verdict ${assessment?.status ?? 'unchecked'}`}>
                      <span className="verdict-eyebrow">VERDICT</span>
                      <strong className="verdict-status">{assessment ? STATUS_LABEL[assessment.status] : 'Not checked'}</strong>
                      {assessment && (
                        <>
                          <div className="verdict-confidence">
                            <span className="verdict-pct">{Math.round(assessment.confidence * 100)}%</span>
                            <span className="verdict-caption">model-assessed confidence<br />(not a probability of truth)</span>
                          </div>
                          <div className="verdict-bar"><i style={{ width: `${Math.round(assessment.confidence * 100)}%` }} /></div>
                          <div className="verdict-counts">
                            <span className="against">{assessment.contradicting_evidence.length} contradicting</span>
                            <span className="for">{assessment.supporting_evidence.length} supporting</span>
                          </div>
                          <p className="verdict-why">{assessment.explanation}</p>
                        </>
                      )}
                    </div>
                  )}
                  <p className="muted">{selected.item.description}</p>
                  {selected.kind === 'node' && typeof selected.item.properties.summary === 'string' && (
                    <p className="muted">{selected.item.properties.summary}</p>
                  )}
                  {selected.kind === 'node' && typeof selected.item.properties.sources === 'number' && (
                    <p className="meta">
                      {selected.item.properties.sources} sources
                      {typeof selected.item.properties.publishers === 'number' && ` · ${selected.item.properties.publishers} publishers`}
                    </p>
                  )}
                  {selected.kind === 'node' && selected.item.type === 'source' && typeof selected.item.properties.url === 'string' && (
                    <a href={selected.item.properties.url} target="_blank" rel="noreferrer">{selected.item.properties.url}</a>
                  )}
                </div>

                {selected.kind === 'node' && (
                  <section className="block">
                    <div className="block-head"><h4>Connected entities</h4><span>{connected.length}</span></div>
                    {connected.map(({ edge, other }) => (
                      <button key={edge.id} className="entity" onClick={() => setPicked({ kind: 'node', item: other })}>
                        <i style={{ background: NODE_COLORS[other.type] }} />
                        <span className="entity-text">
                          <strong>{other.label}</strong>
                          <small>{edge.relationship} · {other.type}</small>
                        </span>
                        <img src={arrowIcon} alt="" />
                      </button>
                    ))}
                  </section>
                )}

                <section className="block">
                  <button className="sources-toggle" aria-expanded={sourcesOpen} onClick={() => setSourcesOpen(!sourcesOpen)}>
                    <img src={docIcon} alt="" />
                    <span>{sourcesOpen ? 'Hide sources' : 'View sources'}</span>
                    <small>{listed.length}</small>
                  </button>
                  {sourcesOpen && (listed.length === 0 ? (
                    <div className="empty-card">
                      <strong><img src={docIcon} alt="" />No sources attached</strong>
                      <p>Check this claim to start reviewing the evidence behind it.</p>
                    </div>
                  ) : (
                    <ul className="source-list">
                      {listed.map(({ source: s, stance, quotes }) => (
                        <li key={s.id} className="source">
                          {stance && <span className={"status " + stance}>{stance}</span>}
                          <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
                          <small>{s.publisher} · credibility {s.credibility_score ?? 'not rated'}/5</small>
                          {quotes.map((v) => (
                            <blockquote key={v.id} className={v.stance}>“{v.excerpt}” <small>({v.stance})</small></blockquote>
                          ))}
                        </li>
                      ))}
                    </ul>
                  ))}
                </section>
              </>
            ) : (
              <p className="muted">Select a node or connection in the graph to see its details.</p>
            )}

            <p className="context-note"><img src={infoSmallIcon} alt="" />Graph links describe relationships, not a factual verdict.</p>
          </aside>
        </div>
      </section>
    </div>
  )
}
