import { useState } from 'react'
import type { ACRequirementResult, AcceptanceCriterion, Step85Result } from '../types'

interface Props {
  result: Step85Result
  loading?: boolean
}

function goalKindBadge(gk: string) {
  switch (gk) {
    case 'data':       return 'bg-red-100 text-red-700'
    case 'structural': return 'bg-blue-100 text-blue-700'
    case 'navigation': return 'bg-green-100 text-green-700'
    case 'presence':   return 'bg-sky-100 text-sky-700'
    case 'behavioral': return 'bg-fuchsia-100 text-fuchsia-700'
    default:           return 'bg-gray-100 text-gray-600'
  }
}

function typeBadge(type: string) {
  switch (type) {
    case 'l1a':       return 'bg-green-50 text-green-600'
    case 'l1b':       return 'bg-gray-100 text-gray-500'
    case 'behavioral': return 'bg-fuchsia-50 text-fuchsia-600'
    default:          return 'bg-gray-100 text-gray-500'
  }
}

function testTypeBadge(tt: string) {
  if (tt === 'api') return 'bg-amber-100 text-amber-700'
  if (tt === 'behavioral') return 'bg-fuchsia-100 text-fuchsia-600'
  return 'bg-indigo-100 text-indigo-700'  // e2e
}

function acTypeBadge(acType: string) {
  switch (acType) {
    case 'happy_path':    return 'bg-green-50 text-green-600'
    case 'persistence':   return 'bg-blue-50 text-blue-600'
    case 'edge_case':     return 'bg-amber-50 text-amber-700'
    case 'fires_when_due':  return 'bg-fuchsia-50 text-fuchsia-700'
    case 'not_before_due':  return 'bg-gray-50 text-gray-600'
    default:              return 'bg-gray-50 text-gray-500'
  }
}

function ACCard({ ac }: { ac: AcceptanceCriterion }) {
  return (
    <div className="border border-gray-100 rounded-lg p-3 space-y-2 bg-gray-50">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-mono font-semibold text-gray-400">{ac.ac_id}</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${acTypeBadge(ac.type)}`}>
          {ac.type.replace(/_/g, ' ')}
        </span>
        <span className="ml-auto text-[10px] font-semibold text-gray-500">acw {ac.acw.toFixed(2)}</span>
      </div>
      {ac.given && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Given</p>
          <p className="text-xs text-gray-700">{ac.given}</p>
        </div>
      )}
      {ac.when && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">When</p>
          <p className="text-xs text-gray-700">{ac.when}</p>
        </div>
      )}
      {ac.then && (
        <div className="space-y-1">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Then</p>
          <p className="text-xs text-gray-700">{ac.then}</p>
        </div>
      )}
    </div>
  )
}

function RequirementACCard({ item }: { item: ACRequirementResult }) {
  const [open, setOpen] = useState(false)
  const acwSum = item.acceptance_criteria.reduce((s, ac) => s + ac.acw, 0)
  const acwOk = Math.abs(acwSum - item.l1cx) < 0.01

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full px-5 py-3 flex items-center gap-2 text-left hover:bg-gray-50 transition-colors"
      >
        <span className="text-xs font-mono text-gray-400 whitespace-nowrap">{item.req_id}</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${typeBadge(item.type)}`}>
          {item.type}
        </span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${goalKindBadge(item.goal_kind)}`}>
          {item.goal_kind}
        </span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${testTypeBadge(item.test_type)}`}>
          {item.test_type}
        </span>
        <p className="flex-1 text-sm text-gray-800 font-medium min-w-0 truncate">{item.description}</p>
        <span className="text-[10px] text-gray-400 flex-shrink-0">
          {item.acceptance_criteria.length} AC{item.acceptance_criteria.length !== 1 ? 's' : ''} ·{' '}
          <span className={acwOk ? 'text-green-600' : 'text-red-500'}>
            Σacw={acwSum.toFixed(2)}
          </span>
          /{item.l1cx.toFixed(1)}
        </span>
        <span className="text-xs text-gray-400 ml-2">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-5 pb-4 space-y-3 border-t border-gray-100">
          {item.acceptance_criteria.length > 0 ? (
            item.acceptance_criteria.map(ac => (
              <ACCard key={ac.ac_id} ac={ac} />
            ))
          ) : (
            <p className="text-sm text-gray-400 py-2">No acceptance criteria generated.</p>
          )}
        </div>
      )}
    </div>
  )
}

function SkeletonCard() {
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white animate-pulse">
      <div className="px-5 py-3 flex items-center gap-3">
        <div className="w-20 h-3 bg-gray-200 rounded" />
        <div className="w-16 h-3 bg-gray-100 rounded" />
        <div className="flex-1 h-3 bg-gray-100 rounded" />
      </div>
    </div>
  )
}

export default function ACResult({ result, loading }: Props) {
  if (loading && !result.acceptance_criteria.length) {
    return (
      <div className="space-y-3">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 px-1">
        <span className="text-xs text-gray-500">
          {result.total_acs} acceptance criteria across {result.acceptance_criteria.length} requirements
        </span>
      </div>

      {result.acceptance_criteria.map(item => (
        <RequirementACCard key={item.req_id} item={item} />
      ))}

      {result.error && (
        <div className="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          Error: {result.error}
        </div>
      )}
    </div>
  )
}
