import { useEffect, useMemo, useState } from 'react'
import ACResult from './ACResult'
import type {
  BehavioralRequirement,
  ConfirmedRequirement,
  Job,
  MappedRequirement,
  Step3Requirement,
} from '../types'

interface Props {
  job: Job
  onGenerateACs: (selectedIds: string[]) => Promise<void>
}

function eBarColor(e: number): string {
  if (e >= 0.8) return 'bg-green-500'
  if (e >= 0.5) return 'bg-amber-400'
  return 'bg-red-400'
}

function eTextColor(e: number): string {
  if (e >= 0.8) return 'text-green-700'
  if (e >= 0.5) return 'text-amber-600'
  return 'text-red-600'
}

function EBar({ e }: { e: number }) {
  return (
    <div className="flex items-center gap-1.5 min-w-[64px]">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${eBarColor(e)}`} style={{ width: `${Math.round(e * 100)}%` }} />
      </div>
      <span className={`text-[10px] font-semibold tabular-nums ${eTextColor(e)}`}>{Math.round(e * 100)}%</span>
    </div>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-t border-gray-50 animate-pulse">
      <div className="w-4 h-4 bg-gray-200 rounded" />
      <div className="w-20 h-3 bg-gray-200 rounded" />
      <div className="flex-1 h-3 bg-gray-100 rounded" />
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
  tag?: string
  priority?: string
  weight?: number
  eScore?: number | null
  checked: boolean
  onToggle: (id: string) => void
}

const TAG_COLORS: Record<string, string> = {
  stated:    'bg-green-100 text-green-700',
  obvious:   'bg-blue-100 text-blue-700',
  generated: 'bg-purple-100 text-purple-700',
  custom:    'bg-orange-100 text-orange-700',
  behavioral:'bg-fuchsia-100 text-fuchsia-700',
}

function ReqRow({ reqId, description, tag, priority, weight, eScore, checked, onToggle }: ReqRowProps) {
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
      {tag && (
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap flex-shrink-0 ${TAG_COLORS[tag] ?? 'bg-gray-100 text-gray-500'}`}>
          {tag}
        </span>
      )}
      {priority && (
        <span className="text-[10px] text-gray-400 flex-shrink-0">{priority}</span>
      )}
      {weight !== undefined && (
        <span className="text-[10px] text-gray-400 flex-shrink-0 w-6 text-right">{weight.toFixed(0)}</span>
      )}
      {eScore != null ? (
        <div className="flex-shrink-0 w-20">
          <EBar e={eScore} />
        </div>
      ) : (
        <div className="flex-shrink-0 w-20" />
      )}
    </label>
  )
}

export default function CorrectnessConfirmation({ job, onGenerateACs }: Props) {
  const step35 = job.step_results.step_3_5
  const step6 = job.step_results.step_6
  const step8 = job.step_results.step_8
  const step85 = job.step_results.step_8_5

  // Build e_score lookup from Step 6
  const eScoreMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of step6?.mapped ?? []) {
      map[r.req_id] = r.e_score
    }
    return map
  }, [step6])

  // Build default ticked set:
  // all L1a + every L1b with e_score >= 0.8 (green E-bar)
  const defaultSelected = useMemo(() => {
    const ids: string[] = []
    for (const r of step35?.confirmed_requirements ?? []) {
      ids.push(r.req_id)
    }
    for (const r of step35?.advisory_requirements ?? []) {
      const e = eScoreMap[r.req_id] ?? 0
      if (e >= 0.8) ids.push(r.req_id)
    }
    // Behavioral: un-ticked by default
    return new Set(ids)
  }, [step35, eScoreMap])

  const [selected, setSelected] = useState<Set<string>>(defaultSelected)
  const [generating, setGenerating] = useState(false)

  // When behavioral reqs load, keep them un-ticked (they're not in defaultSelected)
  // Re-sync if defaultSelected changes (first load or job refresh)
  useEffect(() => {
    setSelected(prev => {
      // Preserve any user changes but add new defaults that weren't there
      const next = new Set(prev)
      for (const id of defaultSelected) {
        // Add new L1a/L1b that just appeared (e.g. from a job refresh)
        next.add(id)
      }
      return next
    })
  }, [defaultSelected])

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
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
      await onGenerateACs(selectedList)
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
            Select requirements to test for correctness. Confirm to generate acceptance criteria.
          </p>
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
              tag={r.tag}
              priority={r.priority}
              weight={r.weight}
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
              const e = eScoreMap[r.req_id] ?? 0
              return (
                <ReqRow
                  key={r.req_id}
                  reqId={r.req_id}
                  description={r.description}
                  tag="generated"
                  priority={r.strength ?? undefined}
                  weight={r.weight}
                  eScore={e}
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
                tag="behavioral"
                priority={r.priority}
                weight={r.weight}
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
