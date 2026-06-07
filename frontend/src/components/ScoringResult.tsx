import { useState } from 'react'
import type { Step6Result, Step7Advisory, Step7Result } from '../types'

interface Props {
  result: Step7Result | null
  loading: boolean
}

function scoreColor(s: number): string {
  if (s >= 0.8) return 'text-green-700'
  if (s >= 0.5) return 'text-amber-600'
  return 'text-red-600'
}

function barColor(s: number): string {
  if (s >= 0.8) return 'bg-green-500'
  if (s >= 0.5) return 'bg-amber-400'
  return 'bg-red-400'
}

function ScorePanel({
  label,
  score,
  detail,
}: {
  label: string
  score: number
  detail: { numerator: number; denominator: number; requirement_count: number }
}) {
  return (
    <div className="flex-1 bg-gray-50 rounded-xl p-5 text-center">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">{label}</p>
      <p className={`text-4xl font-bold tabular-nums ${scoreColor(score)}`}>
        {(score * 100).toFixed(0)}%
      </p>
      <div className="mt-3 h-2 rounded-full bg-gray-200 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor(score)}`}
          style={{ width: `${Math.round(score * 100)}%` }}
        />
      </div>
      <p className="text-[10px] text-gray-400 mt-2">
        {detail.requirement_count} requirement{detail.requirement_count !== 1 ? 's' : ''} ·{' '}
        {detail.numerator.toFixed(2)} / {detail.denominator.toFixed(2)} weighted
      </p>
    </div>
  )
}

function AdvisoryTable({ items, label }: { items: Step7Advisory[]; label: string }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">{label}</p>
      <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 overflow-hidden">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2 bg-white">
            <span className="inline-block px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-mono font-semibold shrink-0">
              {item.req_id}
            </span>
            <span className="flex-1 text-xs text-gray-700 truncate">{item.description}</span>
            {item.strength && (
              <span className="text-[10px] text-gray-400">{item.strength}</span>
            )}
            <span className={`text-xs font-semibold tabular-nums ${scoreColor(item.e_score)}`}>
              {(item.e_score * 100).toFixed(0)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function UnlinkedSection({
  routes,
  endpoints,
}: {
  routes: Step6Result['unlinked_l2']
  endpoints: Step6Result['unlinked_l3']
}) {
  const [open, setOpen] = useState(false)
  const total = routes.length + endpoints.length
  if (total === 0) return null

  return (
    <div className="border border-amber-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-amber-50 hover:bg-amber-100 text-left"
      >
        <span className="text-xs font-semibold text-amber-800">
          {total} unlinked item{total !== 1 ? 's' : ''} (routes + endpoints without L1a match)
        </span>
        <span className="text-xs text-amber-600">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="divide-y divide-amber-100">
          {routes.map((u, i) => (
            <div key={`r${i}`} className="px-3 py-2 bg-white">
              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mr-2">Route</span>
              <span className="text-xs font-mono text-gray-700">{u.route}</span>
              {u.title && <span className="text-xs text-gray-400 ml-2">{u.title}</span>}
            </div>
          ))}
          {endpoints.map((u, i) => (
            <div key={`e${i}`} className="px-3 py-2 bg-white">
              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mr-2">Endpoint</span>
              <span className="text-xs font-mono text-gray-700">
                {u.method && <span className="font-semibold">{u.method} </span>}
                {u.path}
              </span>
              {u.handler && <span className="text-xs text-gray-400 ml-2">({u.handler})</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ScoringResult({ result, loading }: Props) {
  const [showFcomAdvisory, setShowFcomAdvisory] = useState(false)
  const [showFaAdvisory, setShowFaAdvisory] = useState(false)

  if (loading && !result) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <div>
            <p className="text-sm font-semibold text-gray-900">Step 7 — Computing scores…</p>
            <p className="text-xs text-gray-500 mt-0.5">Calculating FCom and FA from entity evidence</p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm">
        <p className="text-sm font-semibold text-gray-900">Step 7 — Scorer</p>
        <p className="text-xs text-red-600 mt-1">{result.error}</p>
      </div>
    )
  }

  const hasFcomAdvisory =
    result.fcom_advisory.missing_l1a.length > 0 ||
    result.fcom_advisory.unlinked_routes.length > 0 ||
    result.fcom_advisory.unlinked_endpoints.length > 0
  const hasFaAdvisory = result.fa_advisory.missing_l1b.length > 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-5">
      <div>
        <p className="text-base font-semibold text-gray-900">Step 7 — Functional Scores</p>
        <p className="text-sm text-gray-500 mt-0.5">
          ISO 25010 Functional Suitability — Completeness & Appropriateness
        </p>
      </div>

      {/* Score panels */}
      <div className="flex gap-4">
        <ScorePanel label="Functional Completeness" score={result.fcom} detail={result.fcom_detail} />
      </div>

      {/* FCom advisory */}
      {hasFcomAdvisory && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowFcomAdvisory(o => !o)}
            className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
          >
            <span className="text-xs font-semibold text-gray-700">FCom advisory</span>
            <span className="text-xs text-gray-400">{showFcomAdvisory ? '▲' : '▼'}</span>
          </button>
          {showFcomAdvisory && (
            <div className="px-4 py-4 space-y-4">
              <AdvisoryTable items={result.fcom_advisory.missing_l1a} label="Missing L1a (E < 50%)" />
              <UnlinkedSection
                routes={result.fcom_advisory.unlinked_routes}
                endpoints={result.fcom_advisory.unlinked_endpoints}
              />
            </div>
          )}
        </div>
      )}

      {/* FA advisory — contains the FA score */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setShowFaAdvisory(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
        >
          <span className="text-xs font-semibold text-gray-700">Functional Appropriateness</span>
          <span className="text-xs text-gray-400">{showFaAdvisory ? '▲' : '▼'}</span>
        </button>
        {showFaAdvisory && (
          <div className="px-4 py-4 space-y-4">
            {/* FA score inline */}
            <div className="bg-gray-50 rounded-lg p-4">
              <p className={`text-3xl font-bold tabular-nums ${scoreColor(result.fa)}`}>
                {(result.fa * 100).toFixed(0)}%
              </p>
              <div className="mt-2 h-2 rounded-full bg-gray-200 overflow-hidden">
                <div
                  className={`h-full rounded-full ${barColor(result.fa)}`}
                  style={{ width: `${Math.round(result.fa * 100)}%` }}
                />
              </div>
              <p className="text-[10px] text-gray-400 mt-1">
                {result.fa_detail.requirement_count} requirement{result.fa_detail.requirement_count !== 1 ? 's' : ''} ·{' '}
                {result.fa_detail.numerator.toFixed(2)} / {result.fa_detail.denominator.toFixed(2)} weighted
              </p>
            </div>
            {hasFaAdvisory && (
              <AdvisoryTable items={result.fa_advisory.missing_l1b} label="Missing L1b implied functions (E < 50%)" />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
