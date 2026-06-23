import { useState } from 'react'
import type { Step11Result } from '../types'
import { stopSandbox } from '../api/client'

const BOOT_STATUS_CONFIG = {
  success:    { label: 'Booted successfully', cls: 'bg-green-100 text-green-700 border-green-200' },
  partial:    { label: 'Partial boot',        cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  boot_failed:{ label: 'Boot failed',         cls: 'bg-red-100   text-red-700   border-red-200'   },
} as const

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${color}`}>
      {label}
    </span>
  )
}

function ServiceRow({ name, url, accessible }: { name: string; url: string | null; accessible: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
      <span className="text-xs font-medium text-gray-600 w-20">{name}</span>
      <div className="flex items-center gap-2 flex-1">
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:underline font-mono"
          >
            {url}
          </a>
        ) : (
          <span className="text-xs text-gray-400 font-mono">—</span>
        )}
      </div>
      <Chip
        label={accessible ? 'accessible' : 'unreachable'}
        color={accessible ? 'bg-green-50 text-green-600 border-green-200' : 'bg-red-50 text-red-500 border-red-200'}
      />
    </div>
  )
}

export default function SandboxResult({
  result,
  loading,
  jobId,
  onRetry,
}: {
  result: Step11Result | null
  loading: boolean
  jobId: string
  onRetry?: () => void
}) {
  const [tearingDown, setTearingDown] = useState(false)
  const [tornDown, setTornDown] = useState(false)
  const [retrying, setRetrying] = useState(false)

  const handleRetry = async () => {
    if (!onRetry) return
    setRetrying(true)
    setTornDown(false)
    try {
      await onRetry()
    } finally {
      setRetrying(false)
    }
  }

  const handleTearDown = async () => {
    setTearingDown(true)
    try {
      await stopSandbox(jobId)
      setTornDown(true)
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Tear down failed')
    } finally {
      setTearingDown(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <div className="flex items-center gap-3">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span className="text-sm text-gray-500">Booting app in Docker…</span>
        </div>
        <p className="text-xs text-gray-400 mt-2 ml-7">
          First run downloads Docker base images and Maven dependencies — this can take 3–8 minutes.
        </p>
      </div>
    )
  }

  if (!result) return null

  const statusCfg = BOOT_STATUS_CONFIG[result.boot_status] ?? BOOT_STATUS_CONFIG.boot_failed

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Test Sandbox</h3>
          <p className="text-xs text-gray-400 mt-0.5">Docker boot · Spring Boot + React (Vite / CRA / Angular / Next.js)</p>
        </div>
        <div className="flex items-center gap-2">
          <Chip label={statusCfg.label} color={statusCfg.cls} />
          {result.boot_status === 'boot_failed' && onRetry && (
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="px-3 py-1 text-xs font-medium rounded border border-indigo-200 text-indigo-600 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {retrying ? 'Starting…' : 'Try Again'}
            </button>
          )}
          {result.boot_status !== 'boot_failed' && !tornDown && (
            <button
              onClick={handleTearDown}
              disabled={tearingDown}
              className="px-3 py-1 text-xs font-medium rounded border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {tearingDown ? 'Stopping…' : 'Tear Down'}
            </button>
          )}
          {tornDown && onRetry && (
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="px-3 py-1 text-xs font-medium rounded border border-indigo-200 text-indigo-600 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {retrying ? 'Starting…' : 'Run Again'}
            </button>
          )}
        </div>
      </div>

      <div className="px-5 py-4 space-y-4">
        {/* Build info chips */}
        <div className="flex flex-wrap gap-2">
          {result.build_tool && (
            <Chip
              label={result.build_tool === 'maven' ? 'Maven' : 'Gradle'}
              color="bg-gray-100 text-gray-600 border-gray-200"
            />
          )}
          {result.frontend_type && (
            <Chip
              label={{ vite: 'Vite', cra: 'CRA', angular: 'Angular', nextjs: 'Next.js', generic: 'Node' }[result.frontend_type] ?? result.frontend_type}
              color="bg-purple-50 text-purple-600 border-purple-200"
            />
          )}
          {result.db_type ? (
            <Chip
              label={{ mysql: 'MySQL', postgresql: 'PostgreSQL', mariadb: 'MariaDB' }[result.db_type] ?? result.db_type}
              color="bg-sky-50 text-sky-600 border-sky-200"
            />
          ) : result.spring_profile_used ? (
            <Chip
              label={`profile: ${result.spring_profile_used}`}
              color="bg-blue-50 text-blue-600 border-blue-200"
            />
          ) : result.h2_dep_found ? (
            <Chip label="H2 in-memory" color="bg-amber-50 text-amber-600 border-amber-200" />
          ) : null}
          {result.build_time_s != null && (
            <Chip label={`build ${result.build_time_s}s`} color="bg-gray-50 text-gray-500 border-gray-200" />
          )}
          {result.boot_time_s != null && (
            <Chip label={`boot ${result.boot_time_s}s`} color="bg-gray-50 text-gray-500 border-gray-200" />
          )}
        </div>

        {/* Service accessibility */}
        {result.boot_status !== 'boot_failed' && (
          <div className="border border-gray-100 rounded-lg px-4 py-1">
            <ServiceRow name="Backend"  url={result.backend_url}  accessible={result.backend_accessible} />
            <ServiceRow name="Frontend" url={result.frontend_url} accessible={result.frontend_accessible} />
          </div>
        )}

        {/* Sandbox warnings — patches applied to make the app boot */}
        {(result.sandbox_warnings ?? []).length > 0 && (
          <div className="border border-amber-200 rounded-lg bg-amber-50 px-4 py-3 space-y-2">
            <p className="text-xs font-semibold text-amber-700">Sandbox patches applied</p>
            <p className="text-[11px] text-amber-600 leading-relaxed">
              The sandbox automatically fixed the following issues to allow the app to boot.
              These represent real defects in the submission that would cause failures in any
              other environment.
            </p>
            <ul className="space-y-1">
              {(result.sandbox_warnings ?? []).map((w, i) => (
                <li key={i} className="text-[11px] text-amber-700 flex gap-2">
                  <span className="mt-0.5 flex-shrink-0">⚠</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Error details */}
        {result.error && (
          <details className="group">
            <summary className="text-xs text-red-500 cursor-pointer select-none hover:text-red-700">
              Error details
            </summary>
            <pre className="mt-2 text-[10px] text-red-600 bg-red-50 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words">
              {result.error}
            </pre>
          </details>
        )}

        {/* Test results */}
        <div>
          <p className="text-xs font-medium text-gray-700 mb-2">Test Results</p>
          {(result.test_results ?? []).length === 0 ? (
            <p className="text-xs text-gray-400 italic">
              No test scripts — Steps 8 (AC Generator) and 9 (Test Generator) not yet built.
            </p>
          ) : (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1.5 pr-3 text-gray-500 font-medium">Req</th>
                  <th className="text-left py-1.5 pr-3 text-gray-500 font-medium">AC</th>
                  <th className="text-left py-1.5 pr-3 text-gray-500 font-medium">Result</th>
                  <th className="text-left py-1.5 text-gray-500 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {(result.test_results ?? []).map((t, i) => (
                  <tr key={i} className="border-b border-gray-100 last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-gray-600">{t.req_id}</td>
                    <td className="py-1.5 pr-3 font-mono text-gray-600">{t.ac_id}</td>
                    <td className="py-1.5 pr-3">
                      <Chip
                        label={t.result}
                        color={
                          t.result === 'pass'      ? 'bg-green-50 text-green-600 border-green-200' :
                          t.result === 'fail'      ? 'bg-red-50 text-red-500 border-red-200' :
                          t.result === 'flaky'     ? 'bg-amber-50 text-amber-600 border-amber-200' :
                                                     'bg-gray-100 text-gray-500 border-gray-200'
                        }
                      />
                    </td>
                    <td className="py-1.5 text-gray-500">{t.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
