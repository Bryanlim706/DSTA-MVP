import { useState } from 'react'
import type { EntityScore, MappedRequirement, Step6Result } from '../types'

interface Props {
  result: Step6Result | null
  loading: boolean
}

const TYPE_STYLES: Record<string, string> = {
  node: 'bg-sky-100 text-sky-700',
  element: 'bg-violet-100 text-violet-700',
  edge: 'bg-amber-100 text-amber-700',
}

const EDGE_KIND_STYLES: Record<string, string> = {
  data: 'bg-red-100 text-red-700',
  navigation: 'bg-green-100 text-green-700',
  structural: 'bg-blue-100 text-blue-700',
}

function eColor(e: number): string {
  if (e >= 0.8) return 'text-green-700'
  if (e >= 0.5) return 'text-amber-600'
  return 'text-red-600'
}

function eBarColor(e: number): string {
  if (e >= 0.8) return 'bg-green-500'
  if (e >= 0.5) return 'bg-amber-400'
  return 'bg-red-400'
}

function EntityRow({ es }: { es: EntityScore }) {
  const typeStyle = TYPE_STYLES[es.type] ?? 'bg-gray-100 text-gray-700'
  const ekStyle = es.edge_kind ? EDGE_KIND_STYLES[es.edge_kind] ?? '' : ''
  const opacity = es.primary ? '' : 'opacity-50'
  const eVal = es.e ?? 0

  let evidence = es.evidence ?? ''
  if (!evidence) {
    if (es.type === 'node' && es.matched_route) evidence = es.matched_route
    else if (es.type === 'element' && es.matched_element_label) evidence = es.matched_element_label + (es.matched_selector ? ` · ${es.matched_selector}` : '')
    else if (es.type === 'edge' && es.edge_kind === 'data' && es.matched_endpoint) evidence = es.matched_endpoint
    else if (es.type === 'edge' && es.edge_kind === 'navigation' && es.matched_nav_target) evidence = `→ ${es.matched_nav_target}`
    else if (es.type === 'edge' && (es.edge_kind === 'structural') && es.trigger_element_label) evidence = es.trigger_element_label
  }

  return (
    <div className={`flex items-center gap-2 py-1 ${opacity}`}>
      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${typeStyle}`}>
        {es.type}
      </span>
      {es.edge_kind && (
        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${ekStyle}`}>
          {es.edge_kind}
        </span>
      )}
      {!es.primary && (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-500">sec</span>
      )}
      <span className="text-xs text-gray-700 flex-1 truncate">{es.label}</span>
      {evidence && (
        <span className="text-[10px] text-gray-400 font-mono truncate max-w-[200px]">{evidence}</span>
      )}
      <span className={`text-xs font-semibold tabular-nums w-8 text-right ${eColor(eVal)}`}>
        {eVal.toFixed(1)}
      </span>
    </div>
  )
}

function RequirementRow({ req }: { req: MappedRequirement }) {
  const [open, setOpen] = useState(false)
  const [showJson, setShowJson] = useState(false)
  const e = req.e_score

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2.5 bg-white hover:bg-gray-50 text-left"
      >
        <span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-mono font-semibold shrink-0">
          {req.req_id}
        </span>
        <span className="flex-1 text-sm text-gray-800 truncate">{req.description}</span>
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-20 h-1.5 rounded-full bg-gray-200 overflow-hidden">
            <div
              className={`h-full rounded-full ${eBarColor(e)}`}
              style={{ width: `${Math.round(e * 100)}%` }}
            />
          </div>
          <span className={`text-sm font-semibold w-6 text-center ${e >= 0.8 ? 'text-green-700' : 'text-red-600'}`}>
            {e >= 0.8 ? '✓' : '✗'}
          </span>
        </div>
        <span className="text-xs text-gray-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 space-y-3">
          {e < 0.8 && (
            <p className="text-xs font-semibold tabular-nums text-red-600">
              E-score: {(e * 100).toFixed(0)}%
            </p>
          )}
          <div>
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">Entity scores</p>
            <div className="space-y-0.5">
              {req.entity_scores.map((es, i) => (
                <EntityRow key={i} es={es} />
              ))}
            </div>
          </div>

          <div className="border border-gray-200 rounded overflow-hidden">
            <button
              onClick={() => setShowJson(o => !o)}
              className="w-full flex items-center justify-between px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-left"
            >
              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">Raw JSON</span>
              <span className="text-[10px] text-gray-400">{showJson ? '▲' : '▼'}</span>
            </button>
            {showJson && (
              <pre className="text-[11px] font-mono text-gray-700 bg-white px-3 py-2 overflow-x-auto leading-relaxed">
                {JSON.stringify(req, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function MappedRequirementList({ reqs }: { reqs: MappedRequirement[] }) {
  if (reqs.length === 0) return null
  return (
    <div className="space-y-2">
      {reqs.map(req => <RequirementRow key={req.req_id} req={req} />)}
    </div>
  )
}

export default function MappingResult({ result, loading }: Props) {
  const [showUnlinkedL2, setShowUnlinkedL2] = useState(false)
  const [showUnlinkedL3, setShowUnlinkedL3] = useState(false)

  if (loading && !result) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <div>
            <p className="text-sm font-semibold text-gray-900">Step 6 — Mapping entities…</p>
            <p className="text-xs text-gray-500 mt-0.5">Grounding requirements against L2/L3 inventory</p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm">
        <p className="text-sm font-semibold text-gray-900">Step 6 — Entity Mapper</p>
        <p className="text-xs text-red-600 mt-1">{result.error}</p>
      </div>
    )
  }

  const totalMapped = result.mapped.length
  const avgE = totalMapped > 0
    ? result.mapped.reduce((s, m) => s + m.e_score, 0) / totalMapped
    : 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-base font-semibold text-gray-900">Step 6 — Entity Mapper</p>
          <p className="text-sm text-gray-500 mt-0.5">
            E() scored for {totalMapped} requirement{totalMapped !== 1 ? 's' : ''} · avg {(avgE * 100).toFixed(0)}%
          </p>
        </div>
        <span className={`text-sm font-semibold tabular-nums ${eColor(avgE)}`}>
          {(avgE * 100).toFixed(0)}%
        </span>
      </div>

      {/* Requirement rows */}
      {totalMapped > 0 && (
        <div className="space-y-2">
          {result.mapped.map(req => (
            <RequirementRow key={req.req_id} req={req} />
          ))}
        </div>
      )}

      {/* Unlinked L2 advisory */}
      {result.unlinked_l2.length > 0 && (
        <div className="border border-amber-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowUnlinkedL2(o => !o)}
            className="w-full flex items-center justify-between px-3 py-2 bg-amber-50 hover:bg-amber-100 text-left"
          >
            <span className="text-xs font-semibold text-amber-800">
              {result.unlinked_l2.length} unlinked route{result.unlinked_l2.length !== 1 ? 's' : ''} (L2)
            </span>
            <span className="text-xs text-amber-600">{showUnlinkedL2 ? '▲' : '▼'}</span>
          </button>
          {showUnlinkedL2 && (
            <div className="divide-y divide-amber-100">
              {result.unlinked_l2.map((u, i) => (
                <div key={i} className="px-3 py-2 bg-white">
                  <span className="text-xs font-mono text-gray-700">{u.route}</span>
                  {u.title && <span className="text-xs text-gray-400 ml-2">{u.title}</span>}
                  <p className="text-[10px] text-gray-400 mt-0.5">{u.note}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Unlinked L3 advisory */}
      {result.unlinked_l3.length > 0 && (
        <div className="border border-amber-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowUnlinkedL3(o => !o)}
            className="w-full flex items-center justify-between px-3 py-2 bg-amber-50 hover:bg-amber-100 text-left"
          >
            <span className="text-xs font-semibold text-amber-800">
              {result.unlinked_l3.length} unlinked endpoint{result.unlinked_l3.length !== 1 ? 's' : ''} (L3)
            </span>
            <span className="text-xs text-amber-600">{showUnlinkedL3 ? '▲' : '▼'}</span>
          </button>
          {showUnlinkedL3 && (
            <div className="divide-y divide-amber-100">
              {result.unlinked_l3.map((u, i) => (
                <div key={i} className="px-3 py-2 bg-white">
                  <span className="text-xs font-mono text-gray-700">
                    {u.method && <span className="font-semibold">{u.method} </span>}
                    {u.path}
                  </span>
                  {u.handler && <span className="text-xs text-gray-400 ml-2">({u.handler})</span>}
                  <p className="text-[10px] text-gray-400 mt-0.5">{u.note}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
