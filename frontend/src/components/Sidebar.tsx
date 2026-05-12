type Stage = 'upload' | 'loading' | 'step_0_complete' | 'error'

const STEPS: { id: number; label: string; sub?: boolean }[] = [
  { id: -1,  label: 'Upload' },
  { id: 0,   label: 'Classifier' },
  { id: 1,   label: 'Stated Requirements' },
  { id: 2,   label: 'Obvious Requirements' },
  { id: 3,   label: 'Implied Functions' },
  { id: 3.5, label: 'Requirement Review', sub: true },
  { id: 4,   label: 'Repo Parser' },
  { id: 5,   label: 'UI/API Inventory' },
  { id: 6,   label: 'Mapper' },
  { id: 7,   label: 'Completeness + Appropriateness' },
  { id: 8,   label: 'AC Generator' },
  { id: 9,   label: 'Test Generator' },
  { id: 10,  label: 'Oracle Validator' },
  { id: 11,  label: 'Test Sandbox' },
  { id: 12,  label: 'Evidence Collector' },
  { id: 13,  label: 'Correctness Score' },
  { id: 14,  label: 'Workflow Friction' },
  { id: 15,  label: 'Evidence Pack' },
  { id: 16,  label: 'LLM Evaluator' },
  { id: 17,  label: 'Dashboard' },
]

const BUILT = new Set([-1, 0])

function activeStepId(stage: Stage): number {
  if (stage === 'upload') return -1
  if (stage === 'loading') return 0
  if (stage === 'step_0_complete') return 0
  return -1
}

function isComplete(id: number, stage: Stage): boolean {
  if (id === -1) return stage === 'loading' || stage === 'step_0_complete'
  if (id === 0) return stage === 'step_0_complete'
  return false
}

function stepNumLabel(id: number): string {
  if (id === -1) return '↑'
  return String(id)
}

export default function Sidebar({ stage }: { stage: Stage }) {
  const active = activeStepId(stage)

  return (
    <aside className="flex-shrink-0 w-52 h-screen bg-white border-r border-gray-200 flex flex-col overflow-hidden">
      <div className="px-4 py-4 border-b border-gray-100">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">ISO 25010</p>
        <p className="text-sm font-medium text-gray-800 mt-0.5">Pipeline</p>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {STEPS.map((step) => {
          const done = isComplete(step.id, stage)
          const current = step.id === active && stage !== 'error'
          const built = BUILT.has(step.id)

          return (
            <div
              key={step.id}
              className={`flex items-center gap-2.5 px-4 py-1.5 text-xs ${step.sub ? 'pl-7' : ''} ${
                current
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : done
                  ? 'text-gray-700'
                  : built
                  ? 'text-gray-500'
                  : 'text-gray-300'
              }`}
            >
              <div
                className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center font-medium leading-none ${
                  step.sub ? 'text-[9px]' : 'text-[10px]'
                } ${
                  done
                    ? 'bg-green-100 text-green-600'
                    : current
                    ? 'bg-blue-600 text-white'
                    : built
                    ? 'bg-gray-100 text-gray-500'
                    : 'bg-gray-50 text-gray-300'
                }`}
              >
                {done ? '✓' : stepNumLabel(step.id)}
              </div>
              <span className="truncate">{step.label}</span>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
