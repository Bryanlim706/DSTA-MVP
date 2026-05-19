import { useState } from 'react'
import type { Step1Requirement, Step1Result } from '../types'
import { PathDisplay } from './PathDisplay'

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high:     'bg-orange-100 text-orange-700',
  medium:   'bg-blue-100 text-blue-700',
  low:      'bg-gray-100 text-gray-500',
}

function sourceLabel(source: string): string {
  return source === 'user_input' ? 'input' : source
}

function sourceBadgeStyle(source: string): string {
  return source === 'user_input'
    ? 'bg-gray-100 text-gray-500'
    : 'bg-purple-100 text-purple-600'
}

function RequirementRow({ req }: { req: Step1Requirement }) {
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
          {req.vague && (
            <span className="ml-1 inline-block text-[10px] px-1.5 py-0.5 rounded bg-orange-50 text-orange-600">
              vague
            </span>
          )}
        </td>
        <td className="px-4 py-2.5 text-sm text-gray-800">{req.description}</td>
        <td className="px-4 py-2.5 text-center">
          {req.testable
            ? <span className="text-green-500 text-xs">✓</span>
            : <span className="text-gray-300 text-xs">—</span>}
        </td>
        <td className="px-4 py-2.5">
          <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded truncate max-w-[120px] ${sourceBadgeStyle(req.source)}`}>
            {sourceLabel(req.source)}
          </span>
        </td>
        <td className="px-4 py-2.5 text-xs text-gray-400 text-right">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-t border-gray-100">
          <td colSpan={6} className="px-4 pb-3 pt-2">
            {req.functional_area && (
              <span className="inline-block text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded font-mono mb-2">
                {req.functional_area}
              </span>
            )}
            <p className="text-xs text-gray-500 font-medium mb-1">Traversal path</p>
            <PathDisplay path={req.path} />
            <p className="text-xs text-gray-500 font-medium mt-2 mb-1">Source quote</p>
            <blockquote className="text-xs text-gray-700 italic border-l-2 border-gray-300 pl-3">
              "{req.source_quote}"
            </blockquote>
          </td>
        </tr>
      )}
    </>
  )
}

export default function RequirementsResult({ result }: { result: Step1Result }) {
  const vagueCount = result.requirements.filter(r => r.vague).length

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3 flex-wrap">
        <h2 className="text-sm font-semibold text-gray-800">Stated Functions</h2>
        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
          {result.total_count} extracted
        </span>
        {vagueCount > 0 && (
          <span className="text-xs bg-orange-50 text-orange-600 px-2 py-0.5 rounded-full" title="Vague functions will be decomposed by Step 3">
            {vagueCount} vague
          </span>
        )}
        {result.docs_used.map((doc) => (
          <span key={doc} className="text-xs bg-purple-100 text-purple-600 px-2 py-0.5 rounded-full">
            {doc}
          </span>
        ))}
        {result.truncated_docs?.length > 0 && (
          <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full" title={`Truncated: ${result.truncated_docs.join(', ')}`}>
            {result.truncated_docs.length} doc{result.truncated_docs.length > 1 ? 's' : ''} truncated
          </span>
        )}
        {result.dropped_count > 0 && (
          <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">
            {result.dropped_count} unverifiable item{result.dropped_count > 1 ? 's' : ''} dropped
          </span>
        )}
        {result.error && (
          <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">
            Extraction error
          </span>
        )}
      </div>

      {result.requirements.length === 0 ? (
        <div className="px-5 py-10 text-center text-sm text-gray-400">
          {result.error
            ? `Extraction failed: ${result.error}`
            : 'No explicitly stated functional requirements found.'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Priority</th>
                <th className="px-4 py-2">Function</th>
                <th className="px-4 py-2 text-center">Testable</th>
                <th className="px-4 py-2">Source</th>
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
        <span className="text-[10px] text-gray-400">Click a row to see traversal path and source quote</span>
      </div>
    </div>
  )
}
