import { useState } from 'react'
import type { Step3Requirement, Step3Result } from '../types'
import { PathDisplay } from './PathDisplay'

const CATEGORY_STYLES: Record<string, { label: string; style: string }> = {
  sop: { label: 'Pattern',   style: 'bg-blue-50 text-blue-700' },
  inf: { label: 'Inferred',  style: 'bg-purple-50 text-purple-700' },
}

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high:     'bg-orange-100 text-orange-700',
  medium:   'bg-blue-100 text-blue-700',
  low:      'bg-gray-100 text-gray-500',
}

function RequirementRow({ req }: { req: Step3Requirement }) {
  const [expanded, setExpanded] = useState(false)
  const cat = CATEGORY_STYLES[req.category] ?? { label: req.category, style: 'bg-gray-100 text-gray-500' }
  const confPct = Math.round(req.confidence_score * 100)

  return (
    <>
      <tr
        className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded(v => !v)}
      >
        <td className="px-4 py-2.5 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
        <td className="px-4 py-2.5">
          <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded ${cat.style}`}>
            {cat.label}
          </span>
        </td>
        <td className="px-4 py-2.5 text-sm text-gray-800">{req.description}</td>
        <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">{confPct}%</td>
        <td className="px-4 py-2.5 text-xs text-gray-400 text-right">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-t border-gray-100">
          <td colSpan={5} className="px-4 pb-3 pt-2 space-y-1.5">
            <div className="flex flex-wrap gap-1 mb-1">
              {req.functional_area && (
                <span className="inline-block text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded font-mono">
                  {req.functional_area}
                </span>
              )}
              {req.priority && (
                <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase ${PRIORITY_STYLES[req.priority] ?? PRIORITY_STYLES.medium}`}>
                  {req.priority}
                </span>
              )}
              {req.strength && (
                <span className="inline-block text-[10px] bg-yellow-50 text-yellow-700 px-1.5 py-0.5 rounded">
                  {req.strength}
                </span>
              )}
              {req.unpacks && (
                <span className="inline-block text-[10px] bg-orange-50 text-orange-600 px-1.5 py-0.5 rounded">
                  unpacks {req.unpacks}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 font-medium">Traversal path</p>
            <PathDisplay path={req.path} />
            <p className="text-xs text-gray-500 font-medium mt-1">Reasoning</p>
            <p className="text-xs text-gray-700 italic">{req.reasoning}</p>
            <p className="text-xs text-gray-500 font-medium">Confidence: {confPct}%</p>
            <p className="text-xs text-gray-700 italic">{req.confidence_reason}</p>
            {req.depends_on?.length > 0 && (
              <p className="text-xs text-gray-400">Depends on: {req.depends_on.join(', ')}</p>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function ReqTable({ reqs }: { reqs: Step3Requirement[] }) {
  if (reqs.length === 0) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
            <th className="px-4 py-2">ID</th>
            <th className="px-4 py-2">Type</th>
            <th className="px-4 py-2">Function</th>
            <th className="px-4 py-2">Confidence</th>
            <th className="px-4 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {reqs.map(r => <RequirementRow key={r.req_id} req={r} />)}
        </tbody>
      </table>
    </div>
  )
}

export default function GeneratedRequirementsResult({ result }: { result: Step3Result }) {
  const l1a = result.requirements.filter(r => r.placement === 'l1a')
  const l1b = result.requirements.filter(r => r.placement === 'l1b')

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-800">Generated Functions</h2>
        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{result.total_count} generated</span>
        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">{result.sop_count} pattern</span>
        <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full">{result.inference_count} inferred</span>
        {result.dropped_count > 0 && (
          <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">{result.dropped_count} dropped</span>
        )}
        {result.error && (
          <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">Generation error</span>
        )}
      </div>

      {result.requirements.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-gray-400">
          {result.error ? `Generation failed: ${result.error}` : 'No generated functions.'}
        </div>
      ) : (
        <>
          {l1a.length > 0 && (
            <div>
              <div className="px-5 py-2 bg-green-50 border-b border-green-100 flex items-center gap-2">
                <span className="text-xs font-semibold text-green-700">L1a Candidates</span>
                <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{l1a.length} — confidence ≥ 80%</span>
              </div>
              <ReqTable reqs={l1a} />
            </div>
          )}
          {l1b.length > 0 && (
            <div>
              <div className="px-5 py-2 bg-yellow-50 border-b border-yellow-100 flex items-center gap-2">
                <span className="text-xs font-semibold text-yellow-700">L1b Advisory</span>
                <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">{l1b.length}</span>
              </div>
              <ReqTable reqs={l1b} />
            </div>
          )}
        </>
      )}

      <div className="px-5 py-2.5 border-t border-gray-100">
        <span className="text-[10px] text-gray-400">Click a row to see traversal path, reasoning, and confidence detail</span>
      </div>
    </div>
  )
}
