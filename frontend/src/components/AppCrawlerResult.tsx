import { useState } from 'react'
import type { Step5Page, Step5Result } from '../types'

interface Props {
  result: Step5Result | null
  loading: boolean
}

const DISCOVERED_STYLES: Record<string, string> = {
  playwright: 'bg-green-100 text-green-800',
  static_fallback: 'bg-yellow-100 text-yellow-800',
}

function DiscoveredBadge({ by }: { by: string }) {
  const cls = DISCOVERED_STYLES[by] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>
      {by === 'playwright' ? 'live' : 'static'}
    </span>
  )
}

function AccessibleDot({ accessible }: { accessible: boolean | null }) {
  if (accessible === true)
    return <span className="inline-block w-2 h-2 rounded-full bg-green-500" title="Accessible" />
  if (accessible === false)
    return <span className="inline-block w-2 h-2 rounded-full bg-red-400" title="Inaccessible" />
  return <span className="inline-block w-2 h-2 rounded-full bg-gray-300" title="Unknown" />
}

function PageRow({ page }: { page: Step5Page }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 bg-white hover:bg-gray-50 text-left"
      >
        <AccessibleDot accessible={page.accessible} />
        <span className="font-mono text-xs text-gray-800 flex-1 truncate">{page.route}</span>
        {page.title && (
          <span className="text-xs text-gray-400 truncate max-w-[160px] hidden sm:block">{page.title}</span>
        )}
        <DiscoveredBadge by={page.discovered_by} />
        <span className="text-xs text-gray-400">{page.elements.length} elements</span>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 space-y-3">
          {page.elements.length > 0 ? (
            <div>
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                Interactive Elements
              </p>
              <div className="space-y-1">
                {page.elements.map((el, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="inline-block px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 font-mono text-[10px]">
                      {el.type}{el.subtype ? `[${el.subtype}]` : ''}
                    </span>
                    <span className="text-gray-700 truncate flex-1">{el.label ?? '—'}</span>
                    {el.selector && (
                      <span className="text-gray-400 font-mono text-[10px] truncate max-w-[180px] hidden md:block">
                        {el.selector}
                      </span>
                    )}
                    {el.visible === false && (
                      <span className="text-[10px] text-gray-400">hidden</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-gray-400 italic">No interactive elements found</p>
          )}

          {page.outbound_links.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                Outbound Links
              </p>
              <div className="flex flex-wrap gap-1">
                {page.outbound_links.map((link, i) => (
                  <span key={i} className="text-[10px] font-mono bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                    {link}
                  </span>
                ))}
              </div>
            </div>
          )}

          {page.api_calls_observed.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                API Calls Observed
              </p>
              <div className="space-y-0.5">
                {page.api_calls_observed.map((call, i) => (
                  <span key={i} className="block text-[10px] font-mono text-gray-500">{call}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function AppCrawlerResult({ result, loading }: Props) {
  if (loading && !result) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
          <div>
            <h2 className="text-base font-semibold text-gray-900">Step 5 — App Crawler</h2>
            <p className="text-sm text-gray-500 mt-0.5">Booting app and crawling routes with Playwright…</p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.error) {
    return (
      <div className="bg-white border border-red-200 rounded-xl p-6 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-2">Step 5 — App Crawler</h2>
        <p className="text-sm text-red-600">{result.error}</p>
      </div>
    )
  }

  const liveCount = result.pages.filter(p => p.discovered_by === 'playwright' && p.accessible).length
  const staticCount = result.pages.filter(p => p.discovered_by === 'static_fallback').length
  const unvisitableCount = result.unvisitable_routes.length
  const totalElements = result.pages.reduce((s, p) => s + p.elements.length, 0)

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Step 5 — App Crawler</h2>
          <p className="text-sm text-gray-500 mt-0.5">Runtime L2 element inventory</p>
        </div>
        <div className="flex gap-2 flex-wrap justify-end">
          {liveCount > 0 && (
            <span className="inline-block px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
              {liveCount} live
            </span>
          )}
          {staticCount > 0 && (
            <span className="inline-block px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
              {staticCount} static
            </span>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Pages', value: result.total_pages },
          { label: 'Elements', value: totalElements },
          { label: 'Unvisitable', value: unvisitableCount },
          { label: 'Live crawled', value: liveCount },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-50 rounded-lg px-4 py-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Pages */}
      {result.pages.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Pages ({result.total_pages})
          </h3>
          <div className="space-y-1.5">
            {result.pages.map((page, i) => (
              <PageRow key={i} page={page} />
            ))}
          </div>
        </div>
      )}

      {/* Unvisitable routes */}
      {unvisitableCount > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">
            Unvisitable Routes ({unvisitableCount})
          </h3>
          <div className="space-y-1">
            {result.unvisitable_routes.map((u, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span className="font-mono text-gray-700">{u.route}</span>
                <span className="text-gray-400">{u.reason.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.pages.length === 0 && (
        <p className="text-sm text-gray-400 italic">
          No pages crawled. The app may have failed to start or has no accessible routes.
        </p>
      )}
    </div>
  )
}
