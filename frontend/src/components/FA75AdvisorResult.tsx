import type { FA75Suggestion, Step75Result } from '../types'

interface Props {
  result: Step75Result | null
  loading: boolean
}

function priorityBadge(p: string) {
  if (p === 'high') return 'bg-red-100 text-red-700'
  if (p === 'low') return 'bg-gray-100 text-gray-500'
  return 'bg-amber-100 text-amber-700'
}

function SuggestionCard({ s }: { s: FA75Suggestion }) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 space-y-2 bg-white">
      <div className="flex items-start gap-2 flex-wrap">
        <span className="text-[10px] font-mono font-semibold bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded shrink-0">
          {s.suggestion_id}
        </span>
        <span
          className={`text-[10px] font-semibold px-1.5 py-0.5 rounded shrink-0 ${priorityBadge(s.priority)}`}
        >
          {s.priority}
        </span>
        <p className="text-sm text-gray-800 font-medium flex-1 min-w-0">{s.description}</p>
      </div>

      {s.grounded_in.rationale && (
        <p className="text-xs text-gray-500 leading-relaxed">{s.grounded_in.rationale}</p>
      )}

      {(s.grounded_in.models.length > 0 || s.grounded_in.endpoints.length > 0) && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {s.grounded_in.models.map((m) => (
            <span
              key={m}
              className="text-[10px] bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded"
            >
              model: {m}
            </span>
          ))}
          {s.grounded_in.endpoints.map((e) => (
            <span
              key={e}
              className="text-[10px] bg-gray-50 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-mono"
            >
              {e}
            </span>
          ))}
        </div>
      )}

      {s.l1a_connection && (
        <p className="text-[10px] text-gray-400">Extends: {s.l1a_connection}</p>
      )}
    </div>
  )
}

export default function FA75AdvisorResult({ result, loading }: Props) {
  if (loading && !result) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
          <div>
            <p className="text-sm font-semibold text-gray-900">Step 7.5 — FA Advisor</p>
            <p className="text-xs text-gray-500 mt-0.5">
              Generating codebase-grounded improvement suggestions…
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm">
        <p className="text-sm font-semibold text-gray-900">Step 7.5 — FA Advisor</p>
        <p className="text-xs text-red-600 mt-1">{result.error}</p>
      </div>
    )
  }

  if (result.suggestions.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <p className="text-sm font-semibold text-gray-900">Step 7.5 — FA Advisor</p>
        <p className="text-xs text-gray-500 mt-1">
          No codebase-grounded suggestions identified.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-4">
      <div>
        <p className="text-base font-semibold text-gray-900">Step 7.5 — FA Advisor</p>
        <p className="text-sm text-gray-500 mt-0.5">
          Codebase-grounded improvement suggestions —{' '}
          <span className="font-medium text-gray-700">{result.total_count}</span> identified
        </p>
        <p className="text-xs text-gray-400 mt-0.5">
          Type B: derived from actual schema, endpoints, and UI patterns (not generic domain inference)
        </p>
      </div>

      <div className="space-y-3">
        {result.suggestions.map((s) => (
          <SuggestionCard key={s.suggestion_id} s={s} />
        ))}
      </div>
    </div>
  )
}
