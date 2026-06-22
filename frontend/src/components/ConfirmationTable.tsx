import { useState } from 'react'
import type { ConfirmedRequirement, Job, PathEntity, Step3Requirement } from '../types'
import { PathDisplay } from './PathDisplay'

const WEIGHT_MAP: Record<string, number> = {
  critical: 4.0, high: 3.0, medium: 2.0, low: 1.0,
}

const PRIORITY_OPTS = ['critical', 'high', 'medium', 'low'] as const

const TAG_STYLES: Record<string, string> = {
  stated:    'bg-green-100 text-green-700',
  obvious:   'bg-blue-100 text-blue-700',
  generated: 'bg-purple-100 text-purple-700',
  custom:    'bg-orange-100 text-orange-700',
}

const STRENGTH_STYLES: Record<string, string> = {
  strongly_implied: 'bg-yellow-100 text-yellow-700',
  medium:           'bg-gray-100 text-gray-600',
  weak:             'bg-gray-100 text-gray-400',
}

interface Props {
  job: Job
  onConfirm: (requirements: ConfirmedRequirement[], skipped: boolean) => void
}

function toConfirmed(
  req: {
    req_id: string
    description: string
    path?: PathEntity[]
    vague?: boolean
    tag: string
    priority?: string
    weight: number
    functional_area?: string
    testable?: boolean
    source?: string
    unpacks?: string | null
    source_quote?: string | null
  },
  promoted = false,
): ConfirmedRequirement {
  const priority = (req.priority ?? 'medium') as ConfirmedRequirement['priority']
  return {
    req_id: req.req_id,
    description: req.description,
    path: req.path ?? [],
    vague: req.vague ?? false,
    tag: req.tag as ConfirmedRequirement['tag'],
    priority,
    weight: WEIGHT_MAP[priority] ?? req.weight,
    functional_area: req.functional_area,
    testable: req.testable ?? true,
    source: req.source ?? req.tag,
    promoted,
    unpacks: req.unpacks ?? null,
    depends_on: [],
    source_quote: req.source_quote ?? null,
  }
}

function IncludedRow({
  req,
  isGen,
  isL1aGen,
  isVagueChild,
  category,
  onPriority,
  onDemote,
  onDelete,
}: {
  req: ConfirmedRequirement
  isGen: boolean
  isL1aGen: boolean
  isVagueChild: boolean
  category?: 'sop' | 'inf'
  onPriority: (id: string, p: ConfirmedRequirement['priority']) => void
  onDemote?: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded(v => !v)}
      >
        <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
        <td className="px-4 py-2 text-sm text-gray-800 max-w-xs">
          {req.description}
          {req.vague && (
            <span className="ml-1 inline-block text-[10px] bg-orange-50 text-orange-600 px-1 py-0.5 rounded">vague</span>
          )}
          {isVagueChild && (
            <span className="ml-1 inline-block text-[10px] bg-orange-100 text-orange-700 px-1 py-0.5 rounded">vague child</span>
          )}
          {isGen && category && (
            <span className={`ml-1 inline-block text-[10px] font-semibold px-1 py-0.5 rounded ${category === 'sop' ? 'bg-blue-50 text-blue-500' : 'bg-purple-50 text-purple-500'}`}>
              {category.toUpperCase()}
            </span>
          )}
        </td>
        <td className="px-4 py-2">
          <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${TAG_STYLES[req.tag] ?? 'bg-gray-100 text-gray-500'}`}>
            {req.tag}
          </span>
        </td>
        <td className="px-4 py-2" onClick={e => e.stopPropagation()}>
          <select
            value={req.priority}
            onChange={e => onPriority(req.req_id, e.target.value as ConfirmedRequirement['priority'])}
            className="text-xs border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {PRIORITY_OPTS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </td>
        <td className="px-4 py-2 text-xs text-gray-500 text-right whitespace-nowrap">{req.weight.toFixed(1)}</td>
        <td className="px-4 py-2 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
          {isL1aGen && onDemote && (
            <button onClick={() => onDemote(req.req_id)} className="text-[10px] text-yellow-600 hover:text-yellow-800 mr-2">
              ↓ advisory
            </button>
          )}
          <button onClick={() => onDelete(req.req_id)} className="text-[10px] text-red-400 hover:text-red-600">×</button>
        </td>
        <td className="px-4 py-2 text-xs text-gray-400 text-right">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (req.path.length > 0 || req.source_quote) && (
        <tr className="bg-gray-50 border-t border-gray-100">
          <td colSpan={7} className="px-4 pb-3 pt-1 space-y-2">
            {req.path.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-1">Traversal path</p>
                <PathDisplay path={req.path} />
              </div>
            )}
            {req.source_quote && (
              <div>
                <p className="text-xs text-gray-500 font-medium mb-0.5">Source quote</p>
                <blockquote className="text-xs text-gray-600 italic border-l-2 border-gray-300 pl-2 leading-relaxed">
                  "{req.source_quote}"
                </blockquote>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function AdvisoryRow({
  req,
  onPromote,
}: {
  req: Step3Requirement
  onPromote: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const confPct = Math.round(req.confidence_score * 100)

  return (
    <>
      <tr className="border-t border-yellow-50 hover:bg-yellow-50 cursor-pointer" onClick={() => setExpanded(v => !v)}>
        <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
        <td className="px-4 py-2 text-sm text-gray-700 max-w-xs">
          {req.description}
          {req.unpacks && (
            <span className="ml-1 text-[10px] bg-orange-50 text-orange-600 px-1 py-0.5 rounded">unpacks {req.unpacks}</span>
          )}
        </td>
        <td className="px-4 py-2">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${req.category === 'sop' ? 'bg-blue-50 text-blue-500' : 'bg-purple-50 text-purple-500'}`}>
            {req.category.toUpperCase()}
          </span>
        </td>
        <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{confPct}%</td>
        <td className="px-4 py-2">
          {req.strength && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${STRENGTH_STYLES[req.strength] ?? ''}`}>
              {req.strength}
            </span>
          )}
        </td>
        <td className="px-4 py-2 text-right" onClick={e => e.stopPropagation()}>
          <button onClick={() => onPromote(req.req_id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap">
            + Promote
          </button>
        </td>
        <td className="px-4 py-2 text-xs text-gray-400 text-right">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="bg-yellow-50 border-t border-yellow-100">
          <td colSpan={7} className="px-4 pb-3 pt-1 space-y-1.5">
            <p className="text-xs text-gray-500 font-medium mb-1">Traversal path</p>
            <PathDisplay path={req.path} />
            <p className="text-xs text-gray-500 font-medium mt-1.5">Reasoning</p>
            <p className="text-xs text-gray-700 italic">{req.reasoning}</p>
            <p className="text-xs text-gray-400">{req.confidence_reason}</p>
          </td>
        </tr>
      )}
    </>
  )
}

export default function ConfirmationTable({ job, onConfirm }: Props) {
  const step1Reqs = job.step_results.step_1?.requirements ?? []
  const step2Reqs = job.step_results.step_2?.requirements ?? []
  const step3Reqs = job.step_results.step_3?.requirements ?? []

  // Vague Step 1 req_ids — these are replaced by their Step 3 children
  const vagueIds = new Set(step1Reqs.filter(r => r.vague).map(r => r.req_id))

  const step3L1a = step3Reqs.filter(r => r.placement === 'l1a')
  const step3L1b = step3Reqs.filter(r => r.placement === 'l1b')

  const [included, setIncluded] = useState<Map<string, ConfirmedRequirement>>(() => {
    const m = new Map<string, ConfirmedRequirement>()
    // Non-vague Step 1 functions
    step1Reqs.filter(r => !r.vague).forEach(r => m.set(r.req_id, toConfirmed(r)))
    step2Reqs.forEach(r => m.set(r.req_id, toConfirmed(r)))
    // Step 3 l1a — includes children of vague parents (auto-replacement)
    step3L1a.forEach(r => m.set(r.req_id, toConfirmed(r, false)))
    // Step 3 l1b children that unpack a vague parent — surface all for review
    step3L1b
      .filter(r => r.unpacks != null && vagueIds.has(r.unpacks))
      .forEach(r => m.set(r.req_id, toConfirmed(r, false)))
    return m
  })

  const [advisory, setAdvisory] = useState<Map<string, Step3Requirement>>(() => {
    const m = new Map<string, Step3Requirement>()
    // Exclude l1b items already promoted to included via vague-child rule
    step3L1b
      .filter(r => !(r.unpacks != null && vagueIds.has(r.unpacks)))
      .forEach(r => m.set(r.req_id, r))
    return m
  })

  const [advisoryOpen, setAdvisoryOpen] = useState(false)
  const [customCount, setCustomCount] = useState(0)
  const [newDesc, setNewDesc] = useState('')
  const [newArea, setNewArea] = useState('')
  const [newPriority, setNewPriority] = useState<ConfirmedRequirement['priority']>('medium')
  const [submitting, setSubmitting] = useState(false)

  function updatePriority(reqId: string, priority: ConfirmedRequirement['priority']) {
    setIncluded(prev => {
      const next = new Map(prev)
      const req = next.get(reqId)
      if (req) next.set(reqId, { ...req, priority, weight: WEIGHT_MAP[priority] })
      return next
    })
  }

  function deleteFromL1a(reqId: string) {
    setIncluded(prev => { const next = new Map(prev); next.delete(reqId); return next })
  }

  function demoteToAdvisory(reqId: string) {
    const req = step3Reqs.find(r => r.req_id === reqId)
    if (!req) return
    setIncluded(prev => { const next = new Map(prev); next.delete(reqId); return next })
    setAdvisory(prev => new Map(prev).set(reqId, req))
  }

  function promoteToL1a(reqId: string) {
    const req = advisory.get(reqId)
    if (!req) return
    setAdvisory(prev => { const next = new Map(prev); next.delete(reqId); return next })
    setIncluded(prev => new Map(prev).set(reqId, toConfirmed(req, true)))
  }

  function addCustom() {
    if (!newDesc.trim()) return
    const n = customCount + 1
    setCustomCount(n)
    const id = `CUSTOM-${String(n).padStart(3, '0')}`
    const req: ConfirmedRequirement = {
      req_id: id,
      description: newDesc.trim(),
      path: [{ type: 'node', label: 'TBD', primary: true }],
      vague: false,
      tag: 'custom',
      priority: newPriority,
      weight: WEIGHT_MAP[newPriority],
      functional_area: newArea.trim() || undefined,
      testable: true,
      source: 'user_added',
      depends_on: [],
      source_quote: null,
    }
    setIncluded(prev => new Map(prev).set(id, req))
    setNewDesc('')
    setNewArea('')
    setNewPriority('medium')
  }

  function handleConfirm() {
    setSubmitting(true)
    onConfirm(Array.from(included.values()), false)
  }

  function handleSkip() {
    setSubmitting(true)
    const skipReqs = [
      ...step1Reqs.filter(r => !r.vague).map(r => toConfirmed(r)),
      ...step2Reqs.map(r => toConfirmed(r)),
    ]
    onConfirm(skipReqs, true)
  }

  const includedArr = Array.from(included.values())
  const advisoryArr = Array.from(advisory.values())

  const includedStated  = includedArr.filter(r => r.tag === 'stated')
  const includedObvious = includedArr.filter(r => r.tag === 'obvious')
  const includedGen     = includedArr.filter(r => r.tag === 'generated' || r.tag === 'custom')

  const orderedIncluded = [...includedStated, ...includedObvious, ...includedGen]

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-10">
      <div className="max-w-4xl mx-auto">

        <div className="mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Step 3.5 — Review Functions</h1>
          {job.project_name && (
            <p className="text-sm font-medium text-gray-600 mt-0.5">{job.project_name}</p>
          )}
          <p className="text-sm text-gray-500 mt-1">
            Confirm what goes into the L1a scoring pool. Edit priorities, remove items, promote generated suggestions, or add your own.
          </p>
          {vagueIds.size > 0 && (
            <p className="text-xs text-orange-600 mt-1">
              {vagueIds.size} vague stated function{vagueIds.size > 1 ? 's were' : ' was'} auto-replaced by their Step 3 children — all children shown in L1a for review.
            </p>
          )}
          <p className="text-[10px] text-gray-300 mt-1 font-mono">{job.job_id}</p>
        </div>

        {/* Section 1: L1a */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-gray-100 bg-green-50 flex items-center gap-3">
            <span className="text-sm font-semibold text-green-800">In Score (L1a)</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{included.size} functions</span>
          </div>

          {included.size === 0 ? (
            <p className="px-5 py-6 text-sm text-gray-400 text-center">No functions in score. Add some below.</p>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Function</th>
                  <th className="px-4 py-2">Tag</th>
                  <th className="px-4 py-2">Priority</th>
                  <th className="px-4 py-2 text-right">Wt</th>
                  <th className="px-4 py-2"></th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {orderedIncluded.map(req => {
                  const step3Source = step3Reqs.find(r => r.req_id === req.req_id)
                  const isL1aGen = req.tag === 'generated' && step3Reqs.some(r => r.req_id === req.req_id)
                  const isVagueChild = req.tag === 'generated' && req.unpacks != null && vagueIds.has(req.unpacks)
                  return (
                    <IncludedRow
                      key={req.req_id}
                      req={req}
                      isGen={req.tag === 'generated'}
                      isL1aGen={isL1aGen}
                      isVagueChild={isVagueChild}
                      category={step3Source?.category}
                      onPriority={updatePriority}
                      onDemote={isL1aGen ? demoteToAdvisory : undefined}
                      onDelete={deleteFromL1a}
                    />
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Section 2: L1b Advisory */}
        {advisoryArr.length > 0 && (
          <div className="bg-white rounded-xl border border-yellow-200 overflow-hidden mb-4">
            <button
              className="w-full px-5 py-3 border-b border-yellow-100 bg-yellow-50 flex items-center gap-3 text-left hover:bg-yellow-100 transition-colors"
              onClick={() => setAdvisoryOpen(v => !v)}
            >
              <span className="text-sm font-semibold text-yellow-800">Advisory (L1b — not in score)</span>
              <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">{advisoryArr.length}</span>
              <span className="ml-auto text-xs text-yellow-600">{advisoryOpen ? '▲' : '▼'}</span>
            </button>
            {advisoryOpen && (
              <table className="w-full text-left">
                <thead>
                  <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-yellow-100">
                    <th className="px-4 py-2">ID</th>
                    <th className="px-4 py-2">Function</th>
                    <th className="px-4 py-2">Category</th>
                    <th className="px-4 py-2">Confidence</th>
                    <th className="px-4 py-2">Strength</th>
                    <th className="px-4 py-2"></th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {advisoryArr.map(req => (
                    <AdvisoryRow key={req.req_id} req={req} onPromote={promoteToL1a} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Section 3: Add custom */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">
          <div className="px-5 py-3 border-b border-gray-100">
            <span className="text-sm font-semibold text-gray-700">Add Custom Function</span>
          </div>
          <div className="px-5 py-4 flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[240px]">
              <label className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1">Description</label>
              <input
                type="text"
                placeholder="User can…"
                value={newDesc}
                onChange={e => setNewDesc(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addCustom()}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
            <div className="w-36">
              <label className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1">Functional Area</label>
              <input
                type="text"
                placeholder="e.g. auth"
                value={newArea}
                onChange={e => setNewArea(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
            <div className="w-28">
              <label className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1">Priority</label>
              <select
                value={newPriority}
                onChange={e => setNewPriority(e.target.value as ConfirmedRequirement['priority'])}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                {PRIORITY_OPTS.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <button
              onClick={addCustom}
              disabled={!newDesc.trim()}
              className="px-4 py-2 text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors disabled:opacity-40"
            >
              Add
            </button>
          </div>
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between">
          <button
            onClick={handleSkip}
            disabled={submitting}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 hover:border-gray-400 px-4 py-2 rounded-lg transition-colors disabled:opacity-40"
          >
            Skip — use stated + obvious only
          </button>
          <button
            onClick={handleConfirm}
            disabled={submitting || included.size === 0}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-6 py-2 rounded-lg transition-colors disabled:opacity-40"
          >
            {submitting ? 'Confirming…' : `Confirm (${included.size} in score)`}
          </button>
        </div>

      </div>
    </div>
  )
}
