import type { PathEntity } from '../types'

const ENTITY_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  node:    { bg: 'bg-sky-50',    text: 'text-sky-700',    label: 'page' },
  element: { bg: 'bg-violet-50', text: 'text-violet-700', label: 'ctrl' },
  edge:    { bg: 'bg-amber-50',  text: 'text-amber-700',  label: 'nav'  },
}

function entityDetail(entity: PathEntity): string {
  if (entity.type === 'edge') {
    const from = entity.from ?? '?'
    const to   = entity.to   ?? '?'
    if (from === 'null' || from === '?') return `→ ${to}`
    if (to   === 'null' || to   === '?') return `${from} →`
    return `${from} → ${to}`
  }
  if (entity.type === 'element' && entity.ui_node) return entity.ui_node
  return ''
}

export function PathDisplay({ path }: { path: PathEntity[] }) {
  if (!path || path.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 mt-2">
      {path.map((entity, i) => {
        const style = ENTITY_STYLES[entity.type] ?? ENTITY_STYLES.node
        const isPrimary = entity.primary !== false
        const detail = entityDetail(entity)
        return (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <span className="text-gray-300 select-none">›</span>}
            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${style.bg} ${style.text} ${!isPrimary ? 'opacity-40' : ''}`}>
              <span className="text-[9px] opacity-50 uppercase tracking-wide font-semibold">{style.label}</span>
              <span className="font-medium">{entity.label}</span>
              {detail && <span className="text-[9px] opacity-50">{detail}</span>}
            </span>
          </span>
        )
      })}
    </div>
  )
}
