import { useState } from 'react'
import type { Step2Requirement, Step2Result } from '../types'

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high:     'bg-orange-100 text-orange-700',
  medium:   'bg-blue-100 text-blue-700',
  low:      'bg-gray-100 text-gray-500',
}

function RequirementRow({ req }: { req: Step2Requirement }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-4 py-2.5 text-xs font-mono text-gray-400 whitespace-nowrap">{req.req_id}</td>
        <td className="px-4 py-2.5">
          <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${PRIORITY_STYLES[req.priority] ?? PRIORITY_STYLES.medium}`}>
            {req.priority}
          </span>
        </td>
        <td className="px-4 py-2.5 text-sm text-gray-800">{req.description}</td>
        <td className="px-4 py-2.5 text-center">
          {req.testable
            ? <span className="text-green-500 text-xs">✓</span>
            : <span className="text-gray-300 text-xs">—</span>}
        </td>
        <td className="px-4 py-2.5 text-xs text-gray-400 text-right">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-t border-gray-100">
          <td colSpan={5} className="px-4 pb-3 pt-1">
            <p className="text-xs text-gray-500 font-medium mb-1">Reasoning</p>
            <p className="text-xs text-gray-700 italic">{req.reasoning}</p>
          </td>
        </tr>
      )}
    </>
  )
}

export default function ObviousRequirementsResult({ result }: { result: Step2Result }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-800">Obvious Requirements</h2>
        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
          {result.total_count} generated
        </span>
        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
          L1a
        </span>
        {result.dropped_count > 0 && (
          <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
            {result.dropped_count} duplicate{result.dropped_count > 1 ? 's' : ''} dropped
          </span>
        )}
        {result.error && (
          <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">
            Generation error
          </span>
        )}
      </div>

      {result.requirements.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-gray-400">
          {result.error
            ? `Generation failed: ${result.error}`
            : 'No obvious requirements generated — stated requirements appear to cover all fundamentals.'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Priority</th>
                <th className="px-4 py-2">Description</th>
                <th className="px-4 py-2 text-center">Testable</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {result.requirements.map((req) => (
                <RequirementRow key={req.req_id} req={req} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-5 py-2.5 border-t border-gray-100">
        <span className="text-[10px] text-gray-400">Click a row to see reasoning</span>
      </div>
    </div>
  )
}
