import { useEffect, useMemo, useState } from 'react'
import type { AcceptanceCriterion, ACRequirementResult, Job } from '../types'

interface Props {
  job: Job
  onGenerateACs: (selectedIds: string[], weightOverrides: Record<string, number>) => Promise<void>
}

const WEIGHT_MAP: Record<string, number> = { critical: 4.0, high: 3.0, medium: 2.0, low: 1.0 }
const PRIORITY_OPTS = ['critical', 'high', 'medium', 'low'] as const

function eBarColor(e: number) {
  return e >= 0.8 ? 'bg-green-500' : e >= 0.5 ? 'bg-amber-400' : 'bg-red-400'
}

function EBar({ e }: { e: number }) {
  return (
    <div className="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
      <div className={`h-full rounded-full ${eBarColor(e)}`} style={{ width: `${Math.round(e * 100)}%` }} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline AC display (used in confirmed view)
// ---------------------------------------------------------------------------

function ACMiniCard({ ac }: { ac: AcceptanceCriterion }) {
  const typeLabel = ac.type.replace(/_/g, ' ')
  const typeCls =
    ac.type === 'happy_path' ? 'bg-green-50 text-green-700' :
    ac.type === 'persistence' ? 'bg-blue-50 text-blue-700' :
    ac.type === 'fires_when_due' ? 'bg-fuchsia-50 text-fuchsia-700' :
    'bg-amber-50 text-amber-700'

  return (
    <div className="border border-gray-100 rounded-lg p-3 space-y-2 bg-white ml-8">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-mono text-gray-400">{ac.ac_id}</span>
        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${typeCls}`}>{typeLabel}</span>
        <span className="ml-auto text-[10px] text-gray-400">acw {ac.acw.toFixed(2)}</span>
      </div>
      {ac.given && <div className="space-y-0.5">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Given</p>
        <p className="text-xs text-gray-700">{ac.given}</p>
      </div>}
      {ac.when && <div className="space-y-0.5">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">When</p>
        <p className="text-xs text-gray-700">{ac.when}</p>
      </div>}
      {ac.then && <div className="space-y-0.5">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Then</p>
        <p className="text-xs text-gray-700">{ac.then}</p>
      </div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Row variants
// ---------------------------------------------------------------------------

interface SelectionRowProps {
  reqId: string
  description: string
  overridePriority: string
  onPriority: (id: string, p: string) => void
  eScore: number | null
  checked: boolean
  onToggle: (id: string) => void
}

function SelectionRow({ reqId, description, overridePriority, onPriority, eScore, checked, onToggle }: SelectionRowProps) {
  return (
    <label className="flex items-center gap-3 px-4 py-2.5 border-t border-gray-100 hover:bg-gray-50 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(reqId)}
        className="w-4 h-4 rounded-md text-indigo-600 accent-indigo-600 flex-shrink-0"
      />
      <span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-mono font-semibold flex-shrink-0 min-w-[72px] text-center">{reqId}</span>
      <span className="flex-1 text-sm text-gray-800 min-w-0">{description}</span>
      <div className="flex-shrink-0 w-20" onClick={e => e.preventDefault()}>
        <select
          value={overridePriority}
          onChange={e => onPriority(reqId, e.target.value)}
          onClick={e => e.stopPropagation()}
          className="w-full text-xs border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          {PRIORITY_OPTS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      {eScore != null ? <EBar e={eScore} /> : <div className="w-20 flex-shrink-0" />}
      {eScore != null
        ? <span className={`text-sm font-semibold w-6 text-center flex-shrink-0 ${eScore >= 0.8 ? 'text-green-700' : 'text-red-600'}`}>{eScore >= 0.8 ? '✓' : '✗'}</span>
        : <div className="w-6 flex-shrink-0" />}
    </label>
  )
}


interface ConfirmedRowProps {
  reqId: string
  description: string
  eScore: number | null
  acResult?: ACRequirementResult
  acGenerating: boolean
}

function ConfirmedRow({ reqId, description, eScore, acResult, acGenerating }: ConfirmedRowProps) {
  const [open, setOpen] = useState(false)
  const hasACs = (acResult?.acceptance_criteria?.length ?? 0) > 0
  const acCount = acResult?.acceptance_criteria?.length ?? 0

  return (
    <div className="border-t border-gray-100">
      <div className="flex items-center gap-3 px-4 py-2.5">
        <span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-mono font-semibold flex-shrink-0 min-w-[72px] text-center">{reqId}</span>
        <span className="flex-1 text-sm text-gray-800 min-w-0">{description}</span>
        {eScore != null ? <EBar e={eScore} /> : <div className="w-20 flex-shrink-0" />}
        {eScore != null
          ? <span className={`text-sm font-semibold w-6 text-center flex-shrink-0 ${eScore >= 0.8 ? 'text-green-700' : 'text-red-600'}`}>{eScore >= 0.8 ? '✓' : '✗'}</span>
          : <div className="w-6 flex-shrink-0" />}
        {/* AC toggle — fixed w-16 so EBar stays aligned across all rows */}
        {acGenerating && !hasACs ? (
          <div className="ml-3 w-16 h-4 bg-gray-100 rounded animate-pulse flex-shrink-0" />
        ) : hasACs ? (
          <button
            onClick={() => setOpen(o => !o)}
            className="ml-3 w-16 flex-shrink-0 flex items-center justify-end gap-1 text-[10px] text-gray-400 hover:text-gray-700 transition-colors"
          >
            <span>{acCount} AC{acCount !== 1 ? 's' : ''}</span>
            <span className={`inline-block transition-transform duration-150 ${open ? '' : '-rotate-90'}`}>▼</span>
          </button>
        ) : (
          <div className="ml-3 w-16 flex-shrink-0" />
        )}
      </div>
      {open && hasACs && (
        <div className="px-4 pb-3 space-y-2">
          {acResult!.acceptance_criteria.map(ac => <ACMiniCard key={ac.ac_id} ac={ac} />)}
        </div>
      )}
    </div>
  )
}

function SkeletonRow() {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-t border-gray-100 animate-pulse">
      <div className="w-4 h-4 bg-gray-200 rounded" />
      <div className="w-20 h-3 bg-gray-200 rounded" />
      <div className="flex-1 h-3 bg-gray-100 rounded" />
      <div className="w-20 h-5 bg-gray-100 rounded" />
      <div className="w-8 h-5 bg-gray-100 rounded" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CorrectnessConfirmation({ job, onGenerateACs }: Props) {
  const step35 = job.step_results.step_3_5
  const step6  = job.step_results.step_6
  const step8  = job.step_results.step_8
  const step85 = job.step_results.step_8_5

  const eScoreMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const r of step6?.mapped ?? []) map[r.req_id] = r.e_score
    return map
  }, [step6])

  // AC lookup by req_id for inline display
  const acMap = useMemo(() => {
    const m = new Map<string, ACRequirementResult>()
    for (const ac of step85?.acceptance_criteria ?? []) m.set(ac.req_id, ac)
    return m
  }, [step85])

  // Priority overrides
  const [priorityOverrides, setPriorityOverrides] = useState<Map<string, string>>(() => {
    const m = new Map<string, string>()
    for (const r of step35?.confirmed_requirements ?? []) m.set(r.req_id, r.priority ?? 'medium')
    for (const r of step35?.advisory_requirements ?? []) {
      const p = r.strength === 'strongly_implied' ? 'high' : r.strength === 'weak' ? 'low' : 'medium'
      m.set(r.req_id, p)
    }
    return m
  })

  useEffect(() => {
    if (!step8?.behavioral_requirements?.length) return
    setPriorityOverrides(prev => {
      const next = new Map(prev)
      let changed = false
      for (const r of step8.behavioral_requirements) {
        if (!next.has(r.req_id)) { next.set(r.req_id, r.priority ?? 'medium'); changed = true }
      }
      return changed ? next : prev
    })
  }, [step8?.behavioral_requirements])

  function setPriority(reqId: string, p: string) {
    setPriorityOverrides(prev => new Map(prev).set(reqId, p))
  }
  function getEffectivePriority(reqId: string, fallback?: string) {
    return priorityOverrides.get(reqId) ?? fallback ?? 'medium'
  }
  function getEffectiveWeight(reqId: string, fallback?: string) {
    return WEIGHT_MAP[getEffectivePriority(reqId, fallback)] ?? 2.0
  }

  // Selection state
  const defaultSelected = useMemo(() => {
    const ids: string[] = []
    for (const r of step35?.confirmed_requirements ?? []) ids.push(r.req_id)
    for (const r of step35?.advisory_requirements ?? []) {
      if ((eScoreMap[r.req_id] ?? 0) >= 0.8) ids.push(r.req_id)
    }
    return new Set(ids)
  }, [step35, eScoreMap])

  const [selected, setSelected] = useState<Set<string>>(defaultSelected)

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

  // Confirmed state — flip immediately on button click; auto-set if returning to page with ACs
  const [confirmed, setConfirmed] = useState(!!step85)
  useEffect(() => { if (step85 && !confirmed) setConfirmed(true) }, [step85])

  const [localGenerating, setLocalGenerating] = useState(false)
  const isGenerating = job.status === 'step_8_5_running'
  const behavioralLoading = job.status === 'step_8_running' || (!step8 && !job.step_results.step_8)

  const selectedList = Array.from(selected)

  async function handleConfirm() {
    if (localGenerating || isGenerating) return
    setConfirmed(true)
    setLocalGenerating(true)
    try {
      const weightOverrides: Record<string, number> = {}
      for (const id of selectedList) weightOverrides[id] = getEffectiveWeight(id)
      await onGenerateACs(selectedList, weightOverrides)
    } finally {
      setLocalGenerating(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Confirmed view — selected only, weights solid, ACs inline
  // ---------------------------------------------------------------------------
  if (confirmed) {
    const acGenerating = isGenerating || localGenerating

    // Helpers to build sections from only selected reqs
    const selL1a  = (step35?.confirmed_requirements ?? []).filter(r => selected.has(r.req_id))
    const selL1b  = (step35?.advisory_requirements ?? []).filter(r => selected.has(r.req_id))
    const selBeh  = (step8?.behavioral_requirements ?? []).filter(r => selected.has(r.req_id))

    function renderConfirmedSection(
      label: string,
      countBadgeCls: string,
      rows: { req_id: string; description: string; defaultP?: string }[],
    ) {
      if (!rows.length) return null
      return (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4 first:mt-0">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">{label}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${countBadgeCls}`}>{rows.length}</span>
          </div>
          {rows.map(r => (
            <ConfirmedRow
              key={r.req_id}
              reqId={r.req_id}
              description={r.description}
              eScore={eScoreMap[r.req_id] ?? null}
              acResult={acMap.get(r.req_id)}
              acGenerating={acGenerating}
            />
          ))}
        </div>
      )
    }

    const acError = job.status === 'step_8_5_error' ? (step85?.error ?? 'AC generation failed') : null

    return (
      <div className="min-h-screen bg-gray-50 px-4 pt-6 pb-12">
        <div className="max-w-3xl mx-auto">
          <div className="mb-5">
            <h1 className="text-lg font-semibold text-gray-900">Correctness — Acceptance Criteria</h1>
            <p className="text-sm text-gray-500 mt-1">
              {acGenerating
                ? `Generating ACs for ${selectedList.length} requirement${selectedList.length !== 1 ? 's' : ''}…`
                : `${selectedList.length} requirement${selectedList.length !== 1 ? 's' : ''} confirmed. Expand a row to view its ACs.`}
            </p>
          </div>

          {acError && (
            <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              AC generation failed: {acError}
            </div>
          )}


          {renderConfirmedSection(
            'FCom — Confirmed L1a',
            'bg-green-100 text-green-700',
            selL1a.map(r => ({ req_id: r.req_id, description: r.description, defaultP: r.priority })),
          )}
          {renderConfirmedSection(
            'FA — Advisory L1b',
            'bg-gray-100 text-gray-600',
            selL1b.map(r => ({
              req_id: r.req_id,
              description: r.description,
              defaultP: r.strength === 'strongly_implied' ? 'high' : r.strength === 'weak' ? 'low' : 'medium',
            })),
          )}
          {renderConfirmedSection(
            'Behavioral',
            'bg-fuchsia-100 text-fuchsia-700',
            selBeh.map(r => ({ req_id: r.req_id, description: r.description, defaultP: r.priority })),
          )}
        </div>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Selection view — checkboxes + priority selects
  // ---------------------------------------------------------------------------
  return (
    <div className="min-h-screen bg-gray-50 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-gray-900">Correctness — Requirement Selection</h1>
          <p className="text-sm text-gray-500 mt-1">
            Select requirements to test. Adjust priority to change acceptance criteria weight.
          </p>
        </div>

        {/* FCom L1a */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">FCom — Confirmed L1a</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              {step35?.confirmed_requirements.length ?? 0}
            </span>
          </div>
          {step35?.confirmed_requirements.map(r => (
            <SelectionRow
              key={r.req_id}
              reqId={r.req_id}
              description={r.description}
              overridePriority={getEffectivePriority(r.req_id, r.priority)}
              onPriority={setPriority}
              eScore={eScoreMap[r.req_id] ?? null}
              checked={selected.has(r.req_id)}
              onToggle={toggle}
            />
          ))}
          {!step35?.confirmed_requirements.length && (
            <p className="px-5 py-3 text-sm text-gray-400">No confirmed requirements.</p>
          )}
        </div>

        {/* FA L1b */}
        {(step35?.advisory_requirements.length ?? 0) > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4">
            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-800">FA — Advisory L1b</span>
              <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                {step35?.advisory_requirements.length}
              </span>
            </div>
            {(step35?.advisory_requirements ?? []).map(r => {
              const defaultP = r.strength === 'strongly_implied' ? 'high' : r.strength === 'weak' ? 'low' : 'medium'
              return (
                <SelectionRow
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

        {/* Behavioral */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mt-4">
          <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-800">Behavioral</span>
            {step8 && (
              <span className="text-xs bg-fuchsia-100 text-fuchsia-700 px-2 py-0.5 rounded-full">
                {step8.behavioral_requirements.length}
              </span>
            )}
          </div>
          {behavioralLoading ? (
            <><SkeletonRow /><SkeletonRow /></>
          ) : step8?.behavioral_requirements.length ? (
            step8.behavioral_requirements.map(r => (
              <SelectionRow
                key={r.req_id}
                reqId={r.req_id}
                description={r.description}
                overridePriority={getEffectivePriority(r.req_id, r.priority)}
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
        <div className="mt-6 flex items-center justify-between">
          <span className="text-xs text-gray-400">
            {selectedList.length} requirement{selectedList.length !== 1 ? 's' : ''} selected
          </span>
          <button
            onClick={handleConfirm}
            disabled={localGenerating || isGenerating || selectedList.length === 0}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            {localGenerating || isGenerating ? 'Generating…' : `Confirm & generate ACs (${selectedList.length})`}
          </button>
        </div>
      </div>
    </div>
  )
}
