import { useState } from 'react'
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
  const [open, setOpen] = useState(false)

  if (loading && !result) {
    return (
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <div className="w-full flex items-center justify-between px-3 py-2 bg-gray-50">
          <span className="text-xs font-semibold text-gray-700">Additional codebase-grounded advisory</span>
          <div className="h-3 w-3 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="border border-red-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2 bg-red-50 hover:bg-red-100 text-left"
        >
          <span className="text-xs font-semibold text-red-800">Additional codebase-grounded advisory</span>
          <span className="text-xs text-red-600">{open ? '▲' : '▼'}</span>
        </button>
        {open && (
          <div className="px-3 py-2 bg-white">
            <p className="text-xs text-red-600">{result.error}</p>
          </div>
        )}
      </div>
    )
  }

  const count = result.suggestions.length

  if (count === 0) {
    return (
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
        >
          <span className="text-xs font-semibold text-gray-700">Additional codebase-grounded advisory</span>
          <span className="text-xs text-gray-500">{open ? '▲' : '▼'}</span>
        </button>
        {open && (
          <div className="px-3 py-2 bg-white">
            <p className="text-xs text-gray-500">No codebase-grounded suggestions identified.</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left"
      >
        <span className="text-xs font-semibold text-gray-700">
          Additional codebase-grounded advisory
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{count} suggestion{count !== 1 ? 's' : ''}</span>
          <span className="text-xs text-gray-500">{open ? '▲' : '▼'}</span>
        </div>
      </button>
      {open && (
        <div className="p-4 space-y-3 bg-white">
          {result.suggestions.map((s) => (
            <SuggestionCard key={s.suggestion_id} s={s} />
          ))}
        </div>
      )}
    </div>
  )
}
