import { useState } from 'react'
import type { ConfirmedRequirement, Job, Step3Requirement } from '../types'

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

const CATEGORY_LABELS: Record<string, string> = {
  sop_a: 'Rule · New page',
  sop_b: 'Rule · Element',
  inf_c: 'Inferred · New page',
  inf_d: 'Inferred · Element',
  inf_e: 'Inferred · Edge',
  structural_edge: 'Nav gap',
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
  req: { req_id: string; description: string; tag: string; priority?: string; weight: number; functional_area?: string; testable?: boolean; source?: string },
  promoted = false,
): ConfirmedRequirement {
  const priority = (req.priority ?? 'medium') as ConfirmedRequirement['priority']
  return {
    req_id: req.req_id,
    description: req.description,
    tag: req.tag as ConfirmedRequirement['tag'],
    priority,
    weight: WEIGHT_MAP[priority] ?? req.weight,
    functional_area: req.functional_area,
    testable: req.testable ?? true,
    source: req.source ?? req.tag,
    promoted,
  }
}

export default function ConfirmationTable({ job, onConfirm }: Props) {
  const step1Reqs = job.step_results.step_1?.requirements ?? []
  const step2Reqs = job.step_results.step_2?.requirements ?? []
  const step3Reqs = job.step_results.step_3?.requirements ?? []

  const step3L1a = step3Reqs.filter(r => r.l1_recommendation === 'l1a')
  const step3L1b = step3Reqs.filter(r => r.l1_recommendation === 'l1b')

  // Section 1: requirements currently included in L1a, keyed by req_id
  const [included, setIncluded] = useState<Map<string, ConfirmedRequirement>>(() => {
    const m = new Map<string, ConfirmedRequirement>()
    step1Reqs.forEach(r => m.set(r.req_id, toConfirmed(r)))
    step2Reqs.forEach(r => m.set(r.req_id, toConfirmed(r)))
    step3L1a.forEach(r => m.set(r.req_id, toConfirmed(r, false)))
    return m
  })

  // Section 2: L1b items not yet promoted — track which ones the user demoted back here
  const [advisory, setAdvisory] = useState<Map<string, Step3Requirement>>(() => {
    const m = new Map<string, Step3Requirement>()
    step3L1b.forEach(r => m.set(r.req_id, r))
    return m
  })

  // Custom requirement form state
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
    setIncluded(prev => {
      const next = new Map(prev)
      next.delete(reqId)
      return next
    })
  }

  function demoteToAdvisory(reqId: string) {
    const req = step3L1a.find(r => r.req_id === reqId)
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
      tag: 'custom',
      priority: newPriority,
      weight: WEIGHT_MAP[newPriority],
      functional_area: newArea.trim() || undefined,
      testable: true,
      source: 'user_added',
    }
    setIncluded(prev => new Map(prev).set(id, req))
    setNewDesc('')
    setNewArea('')
    setNewPriority('medium')
  }

  async function handleConfirm() {
    setSubmitting(true)
    onConfirm(Array.from(included.values()), false)
  }

  async function handleSkip() {
    setSubmitting(true)
    const skipReqs = [
      ...step1Reqs.map(r => toConfirmed(r)),
      ...step2Reqs.map(r => toConfirmed(r)),
    ]
    onConfirm(skipReqs, true)
  }

  const includedArr = Array.from(included.values())
  const advisoryArr = Array.from(advisory.values())

  // Separate included items by origin for section display
  const includedStated = includedArr.filter(r => r.tag === 'stated')
  const includedObvious = includedArr.filter(r => r.tag === 'obvious')
  const includedGenerated = includedArr.filter(r => r.tag === 'generated' || r.tag === 'custom')

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-10">
      <div className="max-w-4xl mx-auto">

        {/* Header */}
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Step 3.5 — Review Requirements</h1>
          <p className="text-sm text-gray-500 mt-1">
            Confirm what goes into the L1a scoring pool. Edit priorities, remove items, promote generated suggestions, or add your own.
          </p>
          <p className="text-[10px] text-gray-300 mt-1 font-mono">{job.job_id}</p>
        </div>

        {/* Section 1: L1a */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-4">
          <div className="px-5 py-3 border-b border-gray-100 bg-green-50 flex items-center gap-3">
            <span className="text-sm font-semibold text-green-800">In Score (L1a)</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{included.size} requirements</span>
          </div>

          {included.size === 0 ? (
            <p className="px-5 py-6 text-sm text-gray-400 text-center">No requirements in score. Add some below.</p>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Description</th>
                  <th className="px-4 py-2">Tag</th>
                  <th className="px-4 py-2">Area</th>
                  <th className="px-4 py-2">Priority</th>
                  <th className="px-4 py-2 text-right">Wt</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {[...includedStated, ...includedObvious, ...includedGenerated].map(req => {
                  const isGen = req.tag === 'generated' || req.tag === 'custom'
                  const isL1aGen = req.tag === 'generated' && step3L1a.some(r => r.req_id === req.req_id)
                  return (
                    <tr key={req.req_id} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
                      <td className="px-4 py-2 text-sm text-gray-800 max-w-xs">{req.description}</td>
                      <td className="px-4 py-2">
                        <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${TAG_STYLES[req.tag] ?? 'bg-gray-100 text-gray-500'}`}>
                          {req.tag}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        {req.functional_area && (
                          <span className="text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded font-mono">
                            {req.functional_area}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <select
                          value={req.priority}
                          onChange={e => updatePriority(req.req_id, e.target.value as ConfirmedRequirement['priority'])}
                          className="text-xs border border-gray-200 rounded px-1.5 py-0.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                        >
                          {PRIORITY_OPTS.map(p => (
                            <option key={p} value={p}>{p}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-500 text-right whitespace-nowrap">{req.weight.toFixed(1)}</td>
                      <td className="px-4 py-2 text-right whitespace-nowrap">
                        {isL1aGen && (
                          <button
                            onClick={() => demoteToAdvisory(req.req_id)}
                            className="text-[10px] text-yellow-600 hover:text-yellow-800 mr-2"
                            title="Move to advisory"
                          >
                            ↓ advisory
                          </button>
                        )}
                        {(!isGen || req.tag === 'custom') && (
                          <button
                            onClick={() => deleteFromL1a(req.req_id)}
                            className="text-[10px] text-red-400 hover:text-red-600"
                            title="Remove"
                          >
                            ×
                          </button>
                        )}
                        {isL1aGen && (
                          <button
                            onClick={() => deleteFromL1a(req.req_id)}
                            className="text-[10px] text-red-400 hover:text-red-600"
                            title="Remove"
                          >
                            ×
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Section 2: L1b Advisory */}
        {advisoryArr.length > 0 && (
          <div className="bg-white rounded-xl border border-yellow-200 overflow-hidden mb-4">
            <div className="px-5 py-3 border-b border-yellow-100 bg-yellow-50 flex items-center gap-3">
              <span className="text-sm font-semibold text-yellow-800">Advisory (L1b — not in score)</span>
              <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">{advisoryArr.length}</span>
            </div>
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-yellow-100">
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Description</th>
                  <th className="px-4 py-2">Category</th>
                  <th className="px-4 py-2">Confidence</th>
                  <th className="px-4 py-2">Strength</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {advisoryArr.map(req => (
                  <tr key={req.req_id} className="border-t border-yellow-50 hover:bg-yellow-50">
                    <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
                    <td className="px-4 py-2 text-sm text-gray-700 max-w-xs">{req.description}</td>
                    <td className="px-4 py-2">
                      <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                        {CATEGORY_LABELS[req.category] ?? req.category}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
                      {Math.round(req.confidence_score * 100)}%
                    </td>
                    <td className="px-4 py-2">
                      {req.strength && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${STRENGTH_STYLES[req.strength] ?? ''}`}>
                          {req.strength}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => promoteToL1a(req.req_id)}
                        className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
                      >
                        + Promote
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Section 3: Add custom requirement */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden mb-6">
          <div className="px-5 py-3 border-b border-gray-100">
            <span className="text-sm font-semibold text-gray-700">Add Custom Requirement</span>
          </div>
          <div className="px-5 py-4 flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[240px]">
              <label className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1">Description</label>
              <input
                type="text"
                placeholder="System must provide…"
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
