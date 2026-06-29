import { useEffect, useRef, useState } from 'react'
import {
  confirmRequirements,
  generateACs,
  generateBehavioral,
  getJob,
  pollJob,
  terminateJob,
  triggerSandbox,
} from './api/client'
import ACResult from './components/ACResult'
import AppCrawlerResult from './components/AppCrawlerResult'
import ClassificationResult from './components/ClassificationResult'
import ConfirmationTable from './components/ConfirmationTable'
import CorrectnessConfirmation from './components/CorrectnessConfirmation'
import FA75AdvisorResult from './components/FA75AdvisorResult'
import ObviousRequirementsResult from './components/ObviousRequirementsResult'
import RepoParserResult from './components/RepoParserResult'
import RequirementsResult from './components/RequirementsResult'
import SandboxResult from './components/SandboxResult'
import ScoringResult from './components/ScoringResult'
import Sidebar from './components/Sidebar'
import UploadPage from './pages/UploadPage'
import type { ConfirmedRequirement, Job, Step3Requirement } from './types'

type Stage = 'upload' | 'loading' | 'confirming' | 'step_3_complete' | 'correctness' | 'error'

// ---------------------------------------------------------------------------
// Hash helpers — "#<jobId>" vs "#<jobId>/correctness"
// ---------------------------------------------------------------------------

function parseHash(): { jobId: string; view: 'presence' | 'correctness' } {
  const hash = window.location.hash.slice(1)
  const [jobId, view] = hash.split('/')
  return { jobId: jobId ?? '', view: view === 'correctness' ? 'correctness' : 'presence' }
}

function setHashView(jobId: string, view: 'presence' | 'correctness') {
  const next = view === 'correctness' ? `#${jobId}/correctness` : `#${jobId}`
  history.replaceState(null, '', next)
}

// ---------------------------------------------------------------------------
// Early results view (steps 0–3)
// ---------------------------------------------------------------------------

function EarlyResultsView({ job, isTerminated }: { job: Job | null; isTerminated?: boolean }) {
  const step0 = job?.step_results?.step_0
  const step1 = job?.step_results?.step_1
  const step2 = job?.step_results?.step_2

  const loadingLabel = step2
    ? 'Generating implied requirements…'
    : step1
    ? 'Generating obvious requirements…'
    : step0
    ? 'Extracting stated requirements…'
    : 'Classifying project type…'

  return (
    <div className="min-h-screen bg-gray-100 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">
        {step0 && <ClassificationResult result={step0} />}
        {step1 && (
          <div className="mt-6">
            <RequirementsResult result={step1} />
          </div>
        )}
        {step2 && (
          <div className="mt-6">
            <ObviousRequirementsResult result={step2} />
          </div>
        )}

        {!isTerminated && (
          <div className="mt-6 flex items-center gap-3 px-5 py-4 bg-white rounded-xl border border-gray-200">
            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <div>
              <p className="text-sm font-medium text-gray-700">{loadingLabel}</p>
              <p className="text-xs text-gray-400 mt-0.5">This usually takes 10–20 seconds</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const TAG_STYLES: Record<string, string> = {
  stated:    'bg-green-100 text-green-700',
  obvious:   'bg-blue-100 text-blue-700',
  generated: 'bg-purple-100 text-purple-700',
  custom:    'bg-orange-100 text-orange-700',
}

function RequirementsPanel({ l1a, l1b }: { l1a: ConfirmedRequirement[]; l1b: Step3Requirement[] }) {
  const [l1aOpen, setL1aOpen] = useState(false)
  const [l1bOpen, setL1bOpen] = useState(false)
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3">
        <span className="text-sm font-semibold text-gray-800">Requirements</span>
        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{l1a.length + l1b.length} total</span>
      </div>

      {/* L1a — In Score */}
      <div className="mx-3 mt-2 mb-2 rounded-lg overflow-hidden border border-green-200">
        <button
          className="w-full px-4 py-2 bg-green-50 flex items-center gap-3 text-left hover:bg-green-100 transition-colors"
          onClick={() => setL1aOpen(v => !v)}
        >
          <span className="text-xs font-semibold text-green-800">In Score (L1a)</span>
          <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{l1a.length} requirements</span>
          <span className="ml-auto text-xs text-green-600">{l1aOpen ? '▲' : '▼'}</span>
        </button>
        {l1aOpen && (
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-t border-green-100 border-b border-green-100 bg-white">
                <th className="px-4 py-2">ID</th>
                <th className="px-4 py-2">Function</th>
                <th className="px-4 py-2">
                  <span className="flex items-center gap-1">
                    Priority
                    <span className="relative group">
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-200 text-gray-500 text-xs font-bold cursor-default select-none">?</span>
                      <div className="absolute left-1/2 -translate-x-1/2 top-full mt-1.5 hidden group-hover:flex flex-col gap-1 bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 z-50 min-w-max">
                        {([
                          { label: 'critical', weight: 4.0, color: 'bg-red-50 text-red-600' },
                          { label: 'high',     weight: 3.0, color: 'bg-orange-50 text-orange-600' },
                          { label: 'medium',   weight: 2.0, color: 'bg-yellow-50 text-yellow-700' },
                          { label: 'low',      weight: 1.0, color: 'bg-gray-100 text-gray-500' },
                        ] as const).map(({ label, weight, color }) => (
                          <span key={label} className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${color}`}>
                            {label} = {weight.toFixed(1)}
                          </span>
                        ))}
                      </div>
                    </span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {l1a.map(r => (
                <tr key={r.req_id} className="border-t border-gray-50 hover:bg-gray-100">
                  <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{r.req_id}</td>
                  <td className="px-4 py-2 text-sm text-gray-800">{r.description}</td>
                  <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{r.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* L1b — Advisory */}
      {l1b.length > 0 && (
        <div className="mx-3 mb-3 rounded-lg overflow-hidden border border-yellow-200">
          <button
            className="w-full px-4 py-2 bg-yellow-50 flex items-center gap-3 text-left hover:bg-yellow-100 transition-colors"
            onClick={() => setL1bOpen(v => !v)}
          >
            <span className="text-xs font-semibold text-yellow-800">Advisory (L1b — not in score)</span>
            <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded-full">{l1b.length} requirements</span>
            <span className="ml-auto text-xs text-yellow-600">{l1bOpen ? '▲' : '▼'}</span>
          </button>
          {l1bOpen && (
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-yellow-100">
                  <th className="px-4 py-2">ID</th>
                  <th className="px-4 py-2">Function</th>
                  <th className="px-4 py-2">Category</th>
                  <th className="px-4 py-2">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {l1b.map(r => (
                  <tr key={r.req_id} className="border-t border-yellow-50 hover:bg-yellow-50">
                    <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{r.req_id}</td>
                    <td className="px-4 py-2 text-sm text-gray-700">{r.description}</td>
                    <td className="px-4 py-2">
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${r.category === 'sop' ? 'bg-blue-50 text-blue-500' : 'bg-purple-50 text-purple-500'}`}>
                        {r.category?.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{Math.round(r.confidence_score * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function ErrorView({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center px-4">
      <div className="max-w-md text-center">
        <div className="text-4xl mb-4">⚠️</div>
        <h2 className="text-lg font-semibold text-gray-900 mb-2">Analysis failed</h2>
        <p className="text-sm text-gray-500 mb-6">{error ?? 'An unexpected error occurred'}</p>
        <button
          onClick={onRetry}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  )
}

function TopBar({
  canTerminate,
  isTerminated,
  onTerminate,
  onNewSession,
  projectName,
  jobId,
}: {
  canTerminate: boolean
  isTerminated: boolean
  onTerminate: () => void
  onNewSession: () => void
  projectName?: string
  jobId?: string
}) {
  return (
    <div className="relative flex items-center px-4 py-2 bg-red-50 border-b border-red-200 z-20">
      <div className="absolute left-1/2 -translate-x-1/2 flex flex-col items-center">
        {projectName && (
          <span className="text-sm font-medium text-gray-800 max-w-xs truncate" title={projectName}>{projectName}</span>
        )}
        {jobId && (
          <span className="text-[10px] font-mono text-gray-300">{jobId}</span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {isTerminated ? (
          <button
            onClick={onNewSession}
            className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-100 transition-colors"
          >
            New session
          </button>
        ) : (
          <button
            onClick={onTerminate}
            disabled={!canTerminate}
            className="text-sm font-medium px-3 py-1.5 rounded-lg border text-red-800 border-red-500 bg-red-100 hover:bg-red-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-red-100"
          >
            Terminate job
          </button>
        )}
      </div>
    </div>
  )
}


function ResultPage({ job, onTriggerSandbox }: { job: Job; onTriggerSandbox: () => void }) {
  const step0 = job.step_results.step_0!
  const step35 = job.step_results.step_3_5
  const step4 = job.step_results.step_4
  const step5 = job.step_results.step_5

  const step4Loading  = job.status === 'step_4_running' || job.status === 'confirmed'
  const step5Loading  = job.status === 'step_5_running' || job.status === 'step_4_complete'
  const step6Loading  = job.status === 'step_6_running' || job.status === 'step_5_complete'
  const step7Loading  = job.status === 'step_7_running' || job.status === 'step_6_complete'
  const step67Loading = step6Loading || step7Loading
  const step75Loading = job.status === 'step_7_5_running' || job.status === 'step_7_complete'

  const l1aIds = new Set(step35?.confirmed_requirements.map(r => r.req_id) ?? [])
  const step11Loading = job.status === 'step_11_running'

  const showSandboxButton = !!job.step_results.step_7_5 && !job.step_results.step_11 && job.status !== 'step_11_running'
  const showSandbox = job.status === 'step_11_running' || !!job.step_results.step_11

  return (
    <div className="min-h-screen bg-gray-100 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">
        <ClassificationResult result={step0} />

        {step35 && (
          <div className="mt-4">
            <RequirementsPanel l1a={step35.confirmed_requirements} l1b={step35.advisory_requirements} />
          </div>
        )}

        <div className="mt-6">
          <RepoParserResult result={step4 ?? null} loading={step4Loading} />
        </div>

        <div className="mt-6">
          <AppCrawlerResult result={step5 ?? null} loading={step5Loading} />
        </div>

        <div className="mt-6">
          <ScoringResult
            result={job.step_results.step_7 ?? null}
            loading={step67Loading}
            step6Result={job.step_results.step_6 ?? null}
            l1aIds={l1aIds}
          />
        </div>

        <div className="mt-6">
          <FA75AdvisorResult result={job.step_results.step_7_5 ?? null} loading={step75Loading} />
        </div>

        {showSandboxButton && (
          <div className="mt-6 flex justify-center">
            <button
              onClick={onTriggerSandbox}
              className="bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
            >
              Run Sandbox
            </button>
          </div>
        )}

        {showSandbox && (
          <div className="mt-6">
            <SandboxResult result={job.step_results.step_11 ?? null} loading={step11Loading} jobId={job.job_id} onRetry={onTriggerSandbox} />
          </div>
        )}
      </div>
    </div>
  )
}

function stageFromStatus(status: string): Stage {
  if (status === 'waiting_for_confirmation') return 'confirming'
  if (['running', 'step_0_complete', 'step_1_complete', 'step_2_complete', 'step_3_running'].includes(status)) return 'loading'
  return 'step_3_complete'
}

export default function App() {
  const [stage, setStage] = useState<Stage>('upload')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollingStep4 = useRef(false)

  // On mount: restore job from URL hash if present
  useEffect(() => {
    const { jobId, view } = parseHash()
    if (!jobId) return
    getJob(jobId)
      .then((j) => {
        setJob(j)
        if (j.status === 'terminated' && !j.step_results?.step_3_5) {
          setStage('loading')
        } else if (view === 'correctness' && j.step_results?.step_7_5) {
          setStage('correctness')
        } else {
          setStage(stageFromStatus(j.status))
        }
      })
      .catch(() => {
        history.replaceState(null, '', window.location.pathname)
      })
  }, [])

  // Poll whenever stage is step_3_complete and status is non-terminal
  useEffect(() => {
    if (stage !== 'step_3_complete' || !job || pollingStep4.current) return
    const terminalStatuses = [
      'step_7_5_complete', 'step_7_5_error', 'step_7_error', 'step_6_error',
      'step_5_error', 'step_4_error', 'step_11_complete', 'step_11_error',
      'error', 'complete', 'terminated',
    ]
    if (terminalStatuses.includes(job.status)) return

    pollingStep4.current = true
    let cancelled = false
    const jobId = job.job_id

    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 2000))
        if (cancelled) break
        try {
          const updated = await getJob(jobId)
          if (!cancelled) setJob(updated)
          if (!cancelled && terminalStatuses.includes(updated.status)) break
        } catch {
          break
        }
      }
      pollingStep4.current = false
    }
    poll()
    return () => { cancelled = true; pollingStep4.current = false }
  }, [stage, job?.status])

  // Poll during correctness stage while step_8 or step_8_5 is running
  useEffect(() => {
    if (stage !== 'correctness' || !job) return
    const terminalStatuses = [
      'step_8_complete', 'step_8_error', 'step_8_5_complete', 'step_8_5_error',
      'step_7_5_complete', 'terminated', 'error',
    ]
    if (terminalStatuses.includes(job.status) &&
        job.status !== 'step_8_running' && job.status !== 'step_8_5_running') return

    let cancelled = false
    const jobId = job.job_id

    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 2000))
        if (cancelled) break
        try {
          const updated = await getJob(jobId)
          if (!cancelled) setJob(updated)
          if (!cancelled && updated.status !== 'step_8_running' && updated.status !== 'step_8_5_running') break
        } catch {
          break
        }
      }
    }

    if (job.status === 'step_8_running' || job.status === 'step_8_5_running') {
      poll()
    }
    return () => { cancelled = true }
  }, [stage, job?.status])

  async function handleUploadComplete(jobId: string) {
    window.location.hash = jobId
    setStage('loading')
    try {
      const completed = await pollJob(jobId, (j) => setJob(j))
      setJob(completed)
      if (completed.status === 'waiting_for_confirmation') {
        setStage('confirming')
      } else if (completed.status === 'terminated') {
        // Stay in loading
      } else {
        setStage('step_3_complete')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
      setStage('error')
    }
  }

  async function handleConfirm(requirements: ConfirmedRequirement[], skipped: boolean) {
    if (!job) return
    try {
      await confirmRequirements(job.job_id, requirements, skipped)
      const updated = await getJob(job.job_id)
      setJob(updated)
      setStage('step_3_complete')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirmation failed')
      setStage('error')
    }
  }

  async function handleTriggerSandbox() {
    if (!job) return
    try {
      await triggerSandbox(job.job_id)
      const updated = await getJob(job.job_id)
      setJob(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sandbox trigger failed')
      setStage('error')
    }
  }

  async function handleNavCorrectness() {
    if (!job) return
    setHashView(job.job_id, 'correctness')
    setStage('correctness')
    // Trigger behavioral generation (cached on second call)
    try {
      await generateBehavioral(job.job_id)
      const updated = await getJob(job.job_id)
      setJob(updated)
    } catch {
      // Non-fatal — screen shows the skeleton while polling
    }
  }

  function handleNavPresence() {
    if (!job) return
    setHashView(job.job_id, 'presence')
    setStage('step_3_complete')
  }

  async function handleGenerateACs(selectedIds: string[], weightOverrides: Record<string, number>) {
    if (!job) return
    await generateACs(job.job_id, selectedIds, weightOverrides)
    const updated = await getJob(job.job_id)
    setJob(updated)
  }

  function reset() {
    history.replaceState(null, '', window.location.pathname)
    setStage('upload')
    setJob(null)
    setError(null)
  }

  async function handleTerminate() {
    if (!job) return
    try {
      await terminateJob(job.job_id)
    } catch {
      /* best-effort */
    }
    try {
      const updated = await getJob(job.job_id)
      setJob(updated)
    } catch {
      /* ignore */
    }
  }

  async function handleNewSession() {
    if (job && job.status !== 'terminated') {
      try {
        await terminateJob(job.job_id)
      } catch {
        /* best-effort */
      }
    }
    reset()
  }

  const isTerminated = job?.status === 'terminated'
  const canRunCorrectness = !!(job?.step_results?.step_7_5)

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-100">
      {stage !== 'upload' && (
        <TopBar
          canTerminate={!!job && !isTerminated}
          isTerminated={isTerminated}
          onTerminate={handleTerminate}
          onNewSession={handleNewSession}
          projectName={job?.project_name}
          jobId={job?.job_id}
        />
      )}
      <div className="flex flex-1 overflow-hidden">
        {stage !== 'upload' && (
          <Sidebar
            stage={stage}
            currentStep={job?.current_step}
            jobStatus={job?.status}
            canRunCorrectness={canRunCorrectness}
            onNavPresence={handleNavPresence}
            onNavCorrectness={handleNavCorrectness}
          />
        )}
        <div className="flex-1 overflow-hidden relative">
          <main className="h-full overflow-y-auto">
            {stage === 'upload' && <UploadPage onUploadComplete={handleUploadComplete} />}
            {(stage === 'loading' || stage === 'confirming') && <EarlyResultsView job={job} isTerminated={isTerminated} />}
            {stage === 'step_3_complete' && job && <ResultPage job={job} onTriggerSandbox={handleTriggerSandbox} />}
            {stage === 'correctness' && job && (
              <CorrectnessConfirmation job={job} onGenerateACs={handleGenerateACs} />
            )}
            {stage === 'error' && <ErrorView error={error} onRetry={reset} />}
          </main>

          {/* Confirmation modal — centered over main content only */}
          {stage === 'confirming' && job && (
            <div className="absolute inset-0 z-50 flex items-center justify-center p-6 bg-black/50 backdrop-blur-sm">
              <div className="rounded-2xl overflow-hidden shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
                <div className="overflow-y-auto bg-white">
                  <ConfirmationTable job={job} onConfirm={handleConfirm} />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
