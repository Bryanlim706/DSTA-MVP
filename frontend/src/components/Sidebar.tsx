import { useState } from 'react'

type Stage = 'upload' | 'loading' | 'confirming' | 'step_3_complete' | 'correctness' | 'error'

type Step = { id: number; label: string; sub?: boolean }

const GROUPS: { id: string; label: string; steps: Step[] }[] = [
  {
    id: 'fcom_fa',
    label: 'Completeness & Appropriateness',
    steps: [
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
      { id: 7.5, label: 'FA Advisor', sub: true },
    ],
  },
  {
    id: 'fcor',
    label: 'Correctness',
    steps: [
      { id: 8,   label: 'Requirement Confirmation' },
      { id: 8.5, label: 'AC Generation', sub: true },
      { id: 9,   label: 'Test Generator' },
      { id: 10,  label: 'Oracle Validator' },
      { id: 11,  label: 'Test Sandbox' },
      { id: 12,  label: 'Evidence Collector' },
      { id: 13,  label: 'Correctness Score' },
      { id: 14,  label: 'Workflow Friction' },
      { id: 15,  label: 'Evidence Pack' },
      { id: 16,  label: 'LLM Evaluator' },
      { id: 17,  label: 'Dashboard' },
    ],
  },
]

const BUILT = new Set([-1, 0, 1, 2, 3, 3.5, 4, 5, 6, 7, 7.5, 8, 8.5, 11])

// Ordered pipeline statuses — a step is "complete" when the job status is at or past it
const STATUS_ORDER = [
  'confirmed',
  'step_4_running', 'step_4_complete', 'step_4_error',
  'step_5_running', 'step_5_complete', 'step_5_error',
  'step_6_running', 'step_6_complete', 'step_6_error',
  'step_7_running', 'step_7_complete', 'step_7_error',
  'step_7_5_running', 'step_7_5_complete', 'step_7_5_error',
  'step_8_running', 'step_8_complete', 'step_8_error',
  'step_8_5_running', 'step_8_5_complete', 'step_8_5_error',
  'step_11_running', 'step_11_complete', 'step_11_error',
]

function statusIndex(s?: string): number {
  return s ? STATUS_ORDER.indexOf(s) : -1
}

function activeStepId(stage: Stage, currentStep?: number, jobStatus?: string): number {
  if (stage === 'upload') return -1
  if (stage === 'loading') {
    if (jobStatus === 'terminated') return -99
    return currentStep ?? 0
  }
  if (stage === 'confirming') return 3.5
  if (stage === 'correctness') {
    if (jobStatus === 'step_8_running') return 8
    if (jobStatus === 'step_8_5_running') return 8.5
    return 8
  }
  if (stage !== 'step_3_complete') return -99
  if (jobStatus === 'step_4_running') return 4
  if (jobStatus === 'step_5_running') return 5
  if (jobStatus === 'step_6_running') return 6
  if (jobStatus === 'step_7_running') return 7
  if (jobStatus === 'step_7_5_running') return 7.5
  if (jobStatus === 'step_11_running')  return 11
  return -99
}

function isComplete(id: number, stage: Stage, currentStep?: number, jobStatus?: string): boolean {
  if (stage === 'confirming') return id === -1 || id === 0 || id === 1 || id === 2 || id === 3
  if (stage === 'loading')    return id === -1 || (id >= 0 && id < (currentStep ?? 0))
  if (stage === 'correctness') {
    if (id === -1 || id === 0 || id === 1 || id === 2 || id === 3 || id === 3.5) return true
    const si = statusIndex(jobStatus)
    if (id === 4)   return si >= statusIndex('step_4_complete')
    if (id === 5)   return si >= statusIndex('step_5_complete')
    if (id === 6)   return si >= statusIndex('step_6_complete')
    if (id === 7)   return si >= statusIndex('step_7_complete')
    if (id === 7.5) return si >= statusIndex('step_7_5_complete')
    if (id === 8)   return si >= statusIndex('step_8_complete')
    if (id === 8.5) return si >= statusIndex('step_8_5_complete')
    return false
  }
  if (stage !== 'step_3_complete') return false

  // Steps 0–3.5 always complete once we reach results stage
  if (id === -1 || id === 0 || id === 1 || id === 2 || id === 3 || id === 3.5) return true

  const si = statusIndex(jobStatus)
  if (id === 4)   return si >= statusIndex('step_4_complete')
  if (id === 5)   return si >= statusIndex('step_5_complete')
  if (id === 6)   return si >= statusIndex('step_6_complete')
  if (id === 7)   return si >= statusIndex('step_7_complete')
  if (id === 7.5) return si >= statusIndex('step_7_5_complete')
  if (id === 8)   return si >= statusIndex('step_8_complete')
  if (id === 8.5) return si >= statusIndex('step_8_5_complete')
  if (id === 11)  return si >= statusIndex('step_11_complete')
  return false
}

function stepNumLabel(id: number): string {
  if (id === -1) return '↑'
  return String(id)
}

interface SidebarProps {
  stage: Stage
  currentStep?: number
  jobStatus?: string
  canRunCorrectness?: boolean
  onNavPresence?: () => void
  onNavCorrectness?: () => void
}

export default function Sidebar({
  stage,
  currentStep,
  jobStatus,
  canRunCorrectness,
  onNavPresence,
  onNavCorrectness,
}: SidebarProps) {
  const active = activeStepId(stage, currentStep, jobStatus)
  const [collapsed, setCollapsed] = useState(false)
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    new Set(stage === 'correctness' ? ['fcor'] : ['fcom_fa'])
  )

  function toggleGroup(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setOpenGroups(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function handleGroupHeaderClick(groupId: string) {
    if (groupId === 'fcom_fa' && onNavPresence && stage === 'correctness') {
      onNavPresence()
    } else if (groupId === 'fcor' && onNavCorrectness && canRunCorrectness && stage === 'step_3_complete') {
      onNavCorrectness()
    }
  }

  return (
    <aside className={`flex-shrink-0 ${collapsed ? 'w-10' : 'w-52'} h-full bg-white border-r border-gray-200 flex flex-col overflow-hidden transition-all duration-200`}>
      {/* Collapse toggle */}
      <div className={`flex ${collapsed ? 'justify-center' : 'justify-end'} px-2 py-2 border-b border-gray-100`}>
        <button
          onClick={() => setCollapsed(c => !c)}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="1" y="1" width="2" height="12" rx="1" fill="currentColor" />
            <rect x="4.5" y="1" width="8.5" height="12" rx="2" stroke="currentColor" strokeWidth="1.25" />
          </svg>
        </button>
      </div>

      {!collapsed && (
        <nav className="flex-1 overflow-y-auto py-2">
          {GROUPS.map(group => {
            const open = openGroups.has(group.id)
            const isCorrectnessGroup = group.id === 'fcor'
            const isFcomGroup = group.id === 'fcom_fa'
            const glowing = isCorrectnessGroup && canRunCorrectness && stage !== 'correctness'
            const navClickable = (isFcomGroup && stage === 'correctness' && !!onNavPresence)
              || (isCorrectnessGroup && canRunCorrectness && stage === 'step_3_complete' && !!onNavCorrectness)

            return (
              <div key={group.id}>
                <div className="px-2 pt-2 pb-0.5 flex items-center gap-1">
                  {/* Group header — always button-shaped; state changes colour */}
                  <button
                    onClick={() => handleGroupHeaderClick(group.id)}
                    disabled={!navClickable && !glowing}
                    title={
                      glowing ? 'Test for correctness' :
                      isFcomGroup && stage === 'correctness' ? 'Back to completeness results' :
                      undefined
                    }
                    className={[
                      'flex-1 px-3 py-1.5 rounded-lg text-[10px] font-semibold uppercase tracking-wider transition-colors text-left leading-tight',
                      glowing
                        ? 'bg-indigo-600 text-white hover:bg-indigo-700 cursor-pointer animate-pulse'
                        : navClickable
                        ? 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 cursor-pointer'
                        : 'bg-gray-50 border border-gray-100 text-gray-400 cursor-default',
                    ].join(' ')}
                  >
                    {group.label}
                  </button>
                  {/* Chevron toggle — separate hitbox */}
                  <button
                    onClick={(e) => toggleGroup(group.id, e)}
                    className="w-6 h-6 flex items-center justify-center text-gray-300 hover:text-gray-500 hover:bg-gray-50 rounded transition-colors flex-shrink-0"
                  >
                    <span className={`inline-block transition-transform duration-150 text-[10px] ${open ? '' : '-rotate-90'}`}>▼</span>
                  </button>
                </div>

                {open && group.steps.map(step => {
                  const done = isComplete(step.id, stage, currentStep, jobStatus)
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
              </div>
            )
          })}
        </nav>
      )}
    </aside>
  )
}
