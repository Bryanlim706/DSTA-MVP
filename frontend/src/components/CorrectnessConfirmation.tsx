import { useEffect, useMemo, useState } from 'react'
import ACResult from './ACResult'
import type {
  ConfirmedRequirement,
  Job,
} from '../types'

interface Props {
  job: Job
  onGenerateACs: (selectedIds: string[], weightOverrides: Record<string, number>) => Promise<void>
}

const WEIGHT_MAP: Record<string, number> = {
  critical: 4.0, high: 3.0, medium: 2.0, low: 1.0,
}
const PRIORITY_OPTS = ['critical', 'high', 'medium', 'low'] as const

function eBarColor(e: number): string {
  if (e >= 0.8) return 'bg-green-500'
  if (e >= 0.5) return 'bg-amber-400'
  return 'bg-red-400'
}

function EBar({ e }: { e: number }) {
  return (
    <div className="w-14 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
      <div className={`h-full rounded-full ${eBarColor(e)}`} style={{ width: `${Math.round(e * 100)}%` }} />
    </div>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-t border-gray-50 animate-pulse">
      <div className="w-4 h-4 bg-gray-200 rounded" />
      <div className="w-20 h-3 bg-gray-200 rounded" />
      <div className="flex-1 h-3 bg-gray-100 rounded" />
      <div className="w-20 h-5 bg-gray-100 rounded" />
      <div className="w-8 h-5 bg-gray-100 rounded" />
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-6">
      <div className="px-5 py-3 border-b border-gray-100">
        <div className="w-40 h-3 bg-gray-200 rounded animate-pulse" />
      </div>
      {[1, 2].map(i => <SkeletonRow key={i} />)}
    </div>
  )
}

interface ReqRowProps {
  reqId: string
  description: string
  overridePriority: string
  overrideWeight: number
  onPriority: (id: string, p: string) => void
  eScore?: number | null
  checked: boolean
  onToggle: (id: string) => void
}

function ReqRow({ reqId, description, overridePriority, overrideWeight, onPriority, eScore, checked, onToggle }: ReqRowProps) {
  return (
    <label className="flex items-center gap-3 px-4 py-2.5 border-t border-gray-50 hover:bg-gray-50 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(reqId)}
        className="w-4 h-4 rounded text-indigo-600 accent-indigo-600 flex-shrink-0"
      />
      <span className="text-xs font-mono text-gray-400 whitespace-nowrap w-24 flex-shrink-0">{reqId}</span>
      <span className="flex-1 text-sm text-gray-800 min-w-0">{description}</span>
      {/* Priority select — stopPropagation so label doesn't double-toggle checkbox */}
      <div className="flex-shrink-0" onClick={e => e.preventDefault()}>
        <select
          value={overridePriority}
          onChange={e => onPriority(reqId, e.target.value)}
          onClick={e => e.stopPropagation()}
          className="text-xs border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          {PRIORITY_OPTS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      {/* Weight chip */}
      <span className="text-[10px] font-medium text-gray-500 bg-gray-100 rounded px-1.5 py-0.5 flex-shrink-0 min-w-[2rem] text-center">
        {overrideWeight.toFixed(1)}
      </span>
      {/* E bar (no numeric label) */}
      {eScore != null ? (
        <EBar e={eScore} />
      ) : (
        <div className="w-14 flex-shrink-0" />
      )}
    </label>
  )
}

export default function CorrectnessConfirmation({ job, onGenerateACs }: Props) {
  const step35 = job.step_results.step_3_5
  const step6  = job.step_results.step_6
  const step8  = job.step_results.step_8
  const step85 = job.step_results.step_8_5

  // Build e_score lookup from Step 6
  const eScoreMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of step6?.mapped ?? []) map[r.req_id] = r.e_score
    return map
  }, [step6])

  // Priority overrides — initialised from step_3_5 data; user can change live
  const [priorityOverrides, setPriorityOverrides] = useState<Map<string, string>>(() => {
    const m = new Map<string, string>()
    for (const r of step35?.confirmed_requirements ?? []) {
      m.set(r.req_id, r.priority ?? 'medium')
    }
    for (const r of step35?.advisory_requirements ?? []) {
      const p = r.strength === 'strongly_implied' ? 'high'
              : r.strength === 'weak' ? 'low'
              : 'medium'
      m.set(r.req_id, p)
    }
    return m
  })

  // When behavioral reqs load, add their priorities without overriding user changes
  useEffect(() => {
    if (!step8?.behavioral_requirements?.length) return
    setPriorityOverrides(prev => {
      const next = new Map(prev)
      let changed = false
      for (const r of step8.behavioral_requirements) {
        if (!next.has(r.req_id)) {
          next.set(r.req_id, r.priority ?? 'medium')
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [step8?.behavioral_requirements])

  function setPriority(reqId: string, p: string) {
    setPriorityOverrides(prev => new Map(prev).set(reqId, p))
  }

  function getEffectivePriority(reqId: string, fallback?: string): string {
    return priorityOverrides.get(reqId) ?? fallback ?? 'medium'
  }

  function getEffectiveWeight(reqId: string, fallback?: string): number {
    return WEIGHT_MAP[getEffectivePriority(reqId, fallback)] ?? 2.0
  }

  // Default selected set: all L1a + L1b with green E-bar (≥0.8)
  const defaultSelected = useMemo(() => {
    const ids: string[] = []
    for (const r of step35?.confirmed_requirements ?? []) ids.push(r.req_id)
    for (const r of step35?.advisory_requirements ?? []) {
      if ((eScoreMap[r.req_id] ?? 0) >= 0.8) ids.push(r.req_id)
    }
    return new Set(ids)
  }, [step35, eScoreMap])

  const [selected, setSelected] = useState<Set<string>>(defaultSelected)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    setSelected(prev => {
      const next = new Set(prev)
      for (const id of defaultSelected) next.add(id)
      return next
    })
  }, [defaultSelected])

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectedList = Array.from(selected)
  const isGenerating = job.status === 'step_8_5_running'
  const acsReady = !!step85

  async function handleConfirm() {
    if (generating || isGenerating) return
    setGenerating(true)
    try {
      const weightOverrides: Record<string, number> = {}
      for (const id of selectedList) weightOverrides[id] = getEffectiveWeight(id)
      await onGenerateACs(selectedList, weightOverrides)
    } finally {
      setGenerating(false)
    }
  }

  const behavioralLoading = job.status === 'step_8_running' || (!step8 && !job.step_results.step_8)

  return (
    <div className="min-h-screen bg-gray-50 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">

        {/* Header */}
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-gray-900">Correctness — Requirement Selection</h1>
          <p className="text-sm text-gray-500 mt-1">
            Select requirements to test. Adjust priority to change acceptance criteria weight.
          </p>
        </div>

        {/* Column headers */}
        <div className="flex items-center gap-3 px-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
          <div className="w-4 flex-shrink-0" />
          <div className="w-24 flex-shrink-0">ID</div>
          <div className="flex-1">Description</div>
          <div className="flex-shrink-0 w-[5.5rem] text-center">Priority</div>
          <div className="flex-shrink-0 min-w-[2rem] text-center">W</div>
          <div className="flex-shrink-0 w-14 text-center">E</div>
        </div>

        {/* FCom L1a section */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">FCom — Confirmed L1a</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              {step35?.confirmed_requirements.length ?? 0}
            </span>
            <span className="ml-auto text-[10px] text-gray-400">All pre-ticked</span>
          </div>
          {step35?.confirmed_requirements.map(r => (
            <ReqRow
              key={r.req_id}
              reqId={r.req_id}
              description={r.description}
              overridePriority={getEffectivePriority(r.req_id, r.priority)}
              overrideWeight={getEffectiveWeight(r.req_id, r.priority)}
              onPriority={setPriority}
              eScore={eScoreMap[r.req_id] ?? null}
              checked={selected.has(r.req_id)}
              onToggle={toggle}
            />
          ))}
          {(!step35?.confirmed_requirements.length) && (
            <p className="px-5 py-3 text-sm text-gray-400">No confirmed requirements.</p>
          )}
        </div>

        {/* FA L1b section */}
        {(step35?.advisory_requirements.length ?? 0) > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-800">FA — Advisory L1b</span>
              <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                {step35?.advisory_requirements.length}
              </span>
              <span className="ml-auto text-[10px] text-gray-400">Green E-bar pre-ticked</span>
            </div>
            {(step35?.advisory_requirements ?? []).map(r => {
              const defaultP = r.strength === 'strongly_implied' ? 'high'
                             : r.strength === 'weak' ? 'low'
                             : 'medium'
              return (
                <ReqRow
                  key={r.req_id}
                  reqId={r.req_id}
                  description={r.description}
                  overridePriority={getEffectivePriority(r.req_id, defaultP)}
                  overrideWeight={getEffectiveWeight(r.req_id, defaultP)}
                  onPriority={setPriority}
                  eScore={eScoreMap[r.req_id] ?? null}
                  checked={selected.has(r.req_id)}
                  onToggle={toggle}
                />
              )
            })}
          </div>
        )}

        {/* Behavioral section */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">Behavioral</span>
            {step8 && (
              <span className="text-xs bg-fuchsia-100 text-fuchsia-700 px-2 py-0.5 rounded-full">
                {step8.behavioral_requirements.length}
              </span>
            )}
            <span className="ml-auto text-[10px] text-gray-400">Un-ticked by default</span>
          </div>

          {behavioralLoading ? (
            <>
              <SkeletonRow />
              <SkeletonRow />
            </>
          ) : step8?.behavioral_requirements.length ? (
            step8.behavioral_requirements.map(r => (
              <ReqRow
                key={r.req_id}
                reqId={r.req_id}
                description={r.description}
                overridePriority={getEffectivePriority(r.req_id, r.priority)}
                overrideWeight={getEffectiveWeight(r.req_id, r.priority)}
                onPriority={setPriority}
                eScore={null}
                checked={selected.has(r.req_id)}
                onToggle={toggle}
              />
            ))
          ) : (
            <p className="px-5 py-3 text-sm text-gray-400">
              No autonomous behavioral requirements detected in the requirements text.
            </p>
          )}
        </div>

        {/* Confirm button */}
        {!acsReady && (
          <div className="mt-6 flex items-center justify-between">
            <span className="text-xs text-gray-400">{selectedList.length} requirement{selectedList.length !== 1 ? 's' : ''} selected</span>
            <button
              onClick={handleConfirm}
              disabled={generating || isGenerating || selectedList.length === 0}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
            >
              {generating || isGenerating
                ? 'Generating…'
                : `Confirm & generate ACs (${selectedList.length})`}
            </button>
          </div>
        )}

        {/* AC Results */}
        {(isGenerating || acsReady) && (
          <div className="mt-8">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Acceptance Criteria</h2>
            {isGenerating && !acsReady && (
              <>
                <LoadingSkeleton />
                <LoadingSkeleton />
              </>
            )}
            {acsReady && step85 && (
              <ACResult result={step85} loading={isGenerating} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
