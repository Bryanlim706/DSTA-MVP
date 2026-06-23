import { useState } from 'react'
import type { Step4Result, ImplementationUnit, Step4Element } from '../types'

interface Props {
  result: Step4Result | null
  loading: boolean
}

const METHOD_STYLES: Record<string, string> = {
  GET: 'bg-green-100 text-green-800',
  POST: 'bg-blue-100 text-blue-800',
  PUT: 'bg-yellow-100 text-yellow-800',
  PATCH: 'bg-orange-100 text-orange-800',
  DELETE: 'bg-red-100 text-red-800',
}

function MethodBadge({ method }: { method: string }) {
  const cls = METHOD_STYLES[method.toUpperCase()] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-mono font-semibold ${cls}`}>
      {method.toUpperCase()}
    </span>
  )
}

function EndpointList({ units }: { units: ImplementationUnit[] }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? units : units.slice(0, 8)
  return (
    <div>
      <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 overflow-hidden">
        {shown.map((u, i) => (
          <div key={i} className="flex items-center gap-3 px-3 py-2 bg-white hover:bg-gray-50">
            <MethodBadge method={u.method} />
            <span className="font-mono text-xs text-gray-800 flex-1 truncate">{u.path}</span>
            {u.handler && (
              <span className="text-xs text-gray-400 truncate max-w-[140px]">{u.handler}()</span>
            )}
            {u.file && (
              <span className="text-xs text-gray-400 truncate max-w-[180px] hidden md:block">
                {u.file}
              </span>
            )}
          </div>
        ))}
      </div>
      {units.length > 8 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 text-xs text-blue-600 hover:underline"
        >
          {expanded ? 'Show less' : `Show ${units.length - 8} more`}
        </button>
      )}
    </div>
  )
}

function FileList({ files, label }: { files: string[]; label: string }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? files : files.slice(0, 6)
  return (
    <div>
      <ul className="text-xs text-gray-600 font-mono space-y-0.5">
        {shown.map((f, i) => (
          <li key={i} className="truncate">{f}</li>
        ))}
      </ul>
      {files.length > 6 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1 text-xs text-blue-600 hover:underline"
        >
          {expanded ? 'Show less' : `+${files.length - 6} more ${label}`}
        </button>
      )}
    </div>
  )
}

export default function RepoParserResult({ result, loading }: Props) {
  if (loading && !result) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <div>
            <h2 className="text-base font-semibold text-gray-900">Repo Parser</h2>
            <p className="text-sm text-gray-500 mt-0.5">Analysing codebase with Tree-sitter…</p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-2">Repo Parser</h2>
        <p className="text-sm text-red-600">{result.error}</p>
      </div>
    )
  }

  const hasEndpoints = result.implementation_units.length > 0
  const hasRoutes = result.frontend_routes.length > 0
  const hasModels = result.database_models.length > 0
  const hasTests = result.existing_tests.length > 0
  const hasImportant = result.important_files.length > 0

  const totalElements = Object.values(result.route_elements ?? {}).reduce((s, els) => s + els.length, 0)
  const hasElements = totalElements > 0
  const hasNavGraph = Object.keys(result.navigation_graph ?? {}).length > 0

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Repo Parser</h2>
          <p className="text-sm text-gray-500 mt-0.5">Static L3 inventory extracted from source</p>
        </div>
        <div className="flex gap-2 flex-wrap justify-end">
          {result.languages.map((lang) => (
            <span
              key={lang}
              className="inline-block px-2.5 py-1 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800"
            >
              {lang}
            </span>
          ))}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
        {[
          { label: 'Endpoints', value: result.total_endpoints },
          { label: 'Routes', value: result.total_routes },
          { label: 'Elements (L3)', value: totalElements },
          { label: 'Nav links (L3)', value: Object.values(result.navigation_graph ?? {}).reduce((s, ts) => s + ts.length, 0) },
          { label: 'Models', value: result.database_models.length },
          { label: 'Test files', value: result.existing_tests.length },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-50 rounded-lg px-3 py-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Backend Action Units */}
      {hasEndpoints && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Backend Actions ({result.total_endpoints})
          </h3>
          <EndpointList units={result.implementation_units} />
        </div>
      )}

      {/* Frontend Routes */}
      {hasRoutes && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Frontend Routes ({result.total_routes})
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {result.frontend_routes.map((r) => (
              <span
                key={r.path}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-xs font-mono"
              >
                {r.path}
                {r.dynamic && (
                  <span className="px-1 rounded bg-amber-100 text-amber-700 text-[10px] font-sans font-medium">
                    dynamic
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Navigation Graph (L3) */}
      {hasNavGraph && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Navigation Graph (L3)</h3>
          <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 overflow-hidden">
            {Object.entries(result.navigation_graph).map(([route, targets]) => (
              <div key={route} className="flex items-center gap-2 px-3 py-2 bg-white text-xs">
                <span className="font-mono text-gray-800 shrink-0">{route}</span>
                <span className="text-gray-400">→</span>
                <div className="flex flex-wrap gap-1">
                  {targets.map(t => (
                    <span key={t} className="px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 font-mono">{t}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Route Elements (L3) */}
      {hasElements && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Elements per Route (L3)</h3>
          <div className="divide-y divide-gray-100 rounded-lg border border-gray-200 overflow-hidden">
            {Object.entries(result.route_elements).map(([route, els]) => (
              <div key={route} className="px-3 py-2 bg-white">
                <div className="font-mono text-xs text-gray-700 mb-1">{route}</div>
                <div className="flex flex-wrap gap-1">
                  {(els as Step4Element[]).map((el, i) => (
                    <span key={i} className="px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 text-[11px] font-mono">
                      {el.type}{el.subtype ? `[${el.subtype}]` : ''}: {el.label}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Database Models */}
      {hasModels && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Database Models ({result.database_models.length})
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {result.database_models.map((m) => (
              <span
                key={m}
                className="inline-block px-2.5 py-1 rounded-full bg-purple-100 text-purple-800 text-xs font-medium"
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Important Files + Test Files */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        {hasImportant && (
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">Key Files</h3>
            <FileList files={result.important_files} label="files" />
          </div>
        )}
        {hasTests && (
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">
              Test Files ({result.existing_tests.length})
            </h3>
            <FileList files={result.existing_tests} label="test files" />
          </div>
        )}
      </div>

      {/* Empty state */}
      {!hasEndpoints && !hasRoutes && !hasModels && (
        <p className="text-sm text-gray-400 italic">
          No actions, routes, or models detected. The codebase may use an unsupported framework
          or the project is a skeleton.
        </p>
      )}
    </div>
  )
}
