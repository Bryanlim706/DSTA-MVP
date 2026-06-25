import type { Step0Result } from '../types'

interface Props {
  result: Step0Result
}

const CONFIDENCE_STYLES = {
  high: 'bg-green-100 text-green-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-red-100 text-red-800',
}

const PROJECT_TYPE_LABELS: Record<string, string> = {
  full_stack_web_app: 'Full-stack web app',
  full_stack_js: 'Full-stack JS',
  frontend_only: 'Frontend only',
  backend_api_only: 'Backend / API only',
  cli_tool: 'CLI tool',
  library: 'Library',
  static_site: 'Static site',
  monorepo: 'Monorepo',
  electron_app: 'Desktop (Electron)',
  mobile_app: 'Mobile app',
  unknown: 'Unknown',
}

const SERVICE_LAYOUT_LABELS: Record<string, string> = {
  single_project: 'Single project',
  single_project_ssr: 'SSR',
  separate_frontend_backend: 'Separate frontend + backend',
  monorepo: 'Monorepo',
  unknown: '',
}

function Pill({ label, muted }: { label: string; muted?: boolean }) {
  return (
    <span
      className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full ${
        muted ? 'bg-gray-100 text-gray-600' : 'bg-blue-100 text-blue-800'
      }`}
    >
      {label}
    </span>
  )
}

export default function ClassificationResult({ result }: Props) {
  const typeLabel = PROJECT_TYPE_LABELS[result.project_type] ?? result.project_type
  const layoutLabel = SERVICE_LAYOUT_LABELS[result.service_layout] ?? result.service_layout

  const frontendLabel = result.frontend_framework
    ? result.frontend_tooling
      ? `${result.frontend_framework} · ${result.frontend_tooling}`
      : result.frontend_framework
    : null

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Main */}
      <div className="p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{typeLabel}</h2>
            {layoutLabel && (
              <span className="text-xs text-gray-500 mt-0.5 block">{layoutLabel}</span>
            )}
          </div>
          <span
            className={`text-xs font-medium px-2.5 py-1 rounded-full capitalize ${CONFIDENCE_STYLES[result.confidence]}`}
          >
            {result.confidence} confidence
          </span>
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          {frontendLabel && <Pill label={frontendLabel} />}
          {result.backend_framework && <Pill label={result.backend_framework} />}
          {result.template_engine && <Pill label={`${result.template_engine} templates`} muted />}
          {result.runtime && <Pill label={result.runtime} muted />}
          {result.server_routes_detected && (
            <Pill label="Server routes detected" muted />
          )}
        </div>

        <p className="text-sm text-gray-600 leading-relaxed">{result.reasoning}</p>
      </div>

      {/* Test strategy */}
      <div className="border-t border-gray-100 px-6 py-4">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Test strategy</h3>
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400 w-16">Primary</span>
            <span className="text-sm text-gray-800 font-medium">{result.test_strategy.primary}</span>
          </div>
          {result.test_strategy.secondary && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-400 w-16">Secondary</span>
              <span className="text-sm text-gray-800">{result.test_strategy.secondary}</span>
            </div>
          )}
        </div>
      </div>

      {/* Config files */}
      <div className="border-t border-gray-100 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Config files found</h3>
          {result.llm_used && (
            <span className="text-xs text-gray-400">AI-assisted</span>
          )}
        </div>
        {result.config_files_found.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {result.config_files_found.map((f) => (
              <span key={f} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-mono">
                {f}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-400">None found</p>
        )}
      </div>
    </div>
  )
}
