import { useEffect, useRef, useState } from 'react'
import { confirmRequirements, getJob, pollJob, terminateJob, triggerSandbox } from './api/client'
import ClassificationResult from './components/ClassificationResult'
import ConfirmationTable from './components/ConfirmationTable'
import ObviousRequirementsResult from './components/ObviousRequirementsResult'
import AppCrawlerResult from './components/AppCrawlerResult'
import FA75AdvisorResult from './components/FA75AdvisorResult'
import SandboxResult from './components/SandboxResult'
import RepoParserResult from './components/RepoParserResult'
import ScoringResult from './components/ScoringResult'
import RequirementsResult from './components/RequirementsResult'
import Sidebar from './components/Sidebar'
import UploadPage from './pages/UploadPage'
import type { ConfirmedRequirement, Job, Step3Requirement } from './types'

type Stage = 'upload' | 'loading' | 'confirming' | 'step_3_complete' | 'error'

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

  const statusText = isTerminated
    ? step2 ? 'Steps 0–2 complete — pipeline terminated'
    : step1 ? 'Steps 0–1 complete — pipeline terminated'
    : step0 ? 'Step 0 complete — pipeline terminated'
    : 'Pipeline terminated'
    : step2 ? 'Steps 0–2 complete'
    : step1 ? 'Steps 0–1 complete'
    : step0 ? 'Step 0 complete'
    : ''

  return (
    <div className="min-h-screen bg-gray-50 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">
        {statusText && (
          <div className="mb-4">
            <p className="text-xs font-semibold text-gray-500 text-center">{statusText}</p>
          </div>
        )}

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

function L1aPanel({ reqs }: { reqs: ConfirmedRequirement[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        className="w-full px-5 py-3 flex items-center gap-3 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-sm font-semibold text-gray-800">L1a — Confirmed Functions</span>
        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{reqs.length}</span>
        <span className="ml-auto text-xs text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <table className="w-full text-left border-t border-gray-100">
          <thead>
            <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
              <th className="px-4 py-2">ID</th>
              <th className="px-4 py-2">Function</th>
              <th className="px-4 py-2">Tag</th>
              <th className="px-4 py-2 text-right">Priority</th>
              <th className="px-4 py-2 text-right">Wt</th>
            </tr>
          </thead>
          <tbody>
            {reqs.map(r => (
              <tr key={r.req_id} className="border-t border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{r.req_id}</td>
                <td className="px-4 py-2 text-sm text-gray-800">{r.description}</td>
                <td className="px-4 py-2">
                  <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${TAG_STYLES[r.tag] ?? 'bg-gray-100 text-gray-500'}`}>{r.tag}</span>
                </td>
                <td className="px-4 py-2 text-xs text-gray-500 text-right whitespace-nowrap">{r.priority}</td>
                <td className="px-4 py-2 text-xs text-gray-500 text-right">{r.weight.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function L1bPanel({ reqs }: { reqs: Step3Requirement[] }) {
  const [open, setOpen] = useState(false)
  if (reqs.length === 0) return null
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        className="w-full px-5 py-3 flex items-center gap-3 text-left hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-sm font-semibold text-gray-800">L1b — Advisory Functions</span>
        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{reqs.length}</span>
        <span className="ml-auto text-xs text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <table className="w-full text-left border-t border-gray-100">
          <thead>
            <tr className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-100">
              <th className="px-4 py-2">ID</th>
              <th className="px-4 py-2">Function</th>
              <th className="px-4 py-2">Category</th>
            </tr>
          </thead>
          <tbody>
            {reqs.map(r => (
              <tr key={r.req_id} className="border-t border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-2 text-xs font-mono text-gray-400 whitespace-nowrap">{r.req_id}</td>
                <td className="px-4 py-2 text-sm text-gray-700">{r.description}</td>
                <td className="px-4 py-2">
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${r.category === 'sop' ? 'bg-blue-50 text-blue-500' : 'bg-purple-50 text-purple-500'}`}>{r.category?.toUpperCase()}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ErrorView({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
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
          <span className="text-sm font-medium text-gray-800">{projectName}</span>
        )}
        {jobId && (
          <span className="text-[10px] font-mono text-gray-300">{jobId}</span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={onTerminate}
          disabled={!canTerminate || isTerminated}
          className={
            isTerminated
              ? 'text-sm font-medium px-3 py-1.5 rounded-lg border text-gray-400 border-gray-200 bg-gray-50 cursor-not-allowed opacity-60'
              : 'text-sm font-medium px-3 py-1.5 rounded-lg border text-red-800 border-red-500 bg-red-100 hover:bg-red-200 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-red-100'
          }
        >
          {isTerminated ? 'Terminated' : 'Terminate job'}
        </button>
        <button
          onClick={onNewSession}
          className="text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
        >
          New session
        </button>
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

  const showSandboxButton = job.status === 'step_7_5_complete' && !job.step_results.step_11
  const showSandbox = job.status === 'step_11_running' || !!job.step_results.step_11

  return (
    <div className="min-h-screen bg-gray-50 px-4 pt-6 pb-12">
      <div className="max-w-3xl mx-auto">
        <div className="mb-4">
          <p className="text-xs font-semibold text-gray-500 text-center">
            {job.status === 'step_7_5_complete' ? 'Steps 0–7.5 complete'
          : job.status === 'step_7_complete' || job.status === 'step_7_5_running' ? 'Steps 0–7 complete'
          : job.status === 'step_6_complete' || job.status === 'step_7_running' ? 'Steps 0–6 complete'
          : job.status === 'step_5_complete' || job.status === 'step_6_running' ? 'Steps 0–5 complete'
          : job.status === 'step_4_complete' || job.status === 'step_5_running' ? 'Steps 0–4 complete'
          : job.status === 'terminated' && job.step_results?.step_7_5 ? 'Steps 0–7.5 complete — terminated'
          : job.status === 'terminated' && job.step_results?.step_7   ? 'Steps 0–7 complete — terminated'
          : job.status === 'terminated' && job.step_results?.step_6   ? 'Steps 0–6 complete — terminated'
          : job.status === 'terminated' && job.step_results?.step_5   ? 'Steps 0–5 complete — terminated'
          : job.status === 'terminated' && job.step_results?.step_4   ? 'Steps 0–4 complete — terminated'
          : 'Steps 0–3.5 complete'}
          </p>
        </div>

        <ClassificationResult result={step0} />

        {step35 && (
          <>
            <div className="mt-4">
              <L1aPanel reqs={step35.confirmed_requirements} />
            </div>
            <div className="mt-3">
              <L1bPanel reqs={step35.advisory_requirements} />
            </div>
          </>
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
    const jobId = window.location.hash.slice(1)
    if (!jobId) return
    getJob(jobId)
      .then((j) => {
        setJob(j)
        // Terminated without step_3_5 → stay in loading so LoadingView/EarlyResultsView
        // shows the terminated state. Terminated with step_3_5 → show results normally.
        if (j.status === 'terminated' && !j.step_results?.step_3_5) {
          setStage('loading')
        } else {
          setStage(stageFromStatus(j.status))
        }
      })
      .catch(() => {
        window.location.hash = ''
      })
  }, [])

  // Poll whenever stage is step_3_complete and status is non-terminal
  useEffect(() => {
    if (stage !== 'step_3_complete' || !job || pollingStep4.current) return
    const terminalStatuses = ['step_7_5_complete', 'step_7_5_error', 'step_7_error', 'step_6_error', 'step_5_error', 'step_4_error', 'step_11_complete', 'step_11_error', 'error', 'complete', 'terminated']
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

  async function handleUploadComplete(jobId: string) {
    window.location.hash = jobId
    setStage('loading')
    try {
      const completed = await pollJob(jobId, (j) => setJob(j))
      setJob(completed)
      if (completed.status === 'waiting_for_confirmation') {
        setStage('confirming')
      } else if (completed.status === 'terminated') {
        // Stay in loading — LoadingView/EarlyResultsView renders the terminated state
        // without requiring all step results to be present.
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
      /* best-effort — still reflect terminated state locally */
    }
    try {
      const updated = await getJob(job.job_id)
      setJob(updated)
      // Intentionally NOT transitioning away from 'confirming' here.
      // ConfirmationTable renders with job.status === 'terminated' and replaces
      // the action bar with a terminated notice — user stays on the page they
      // were reviewing (steps 0–3) rather than landing on an empty ResultPage.
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

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
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
        {stage !== 'upload' && <Sidebar stage={stage} currentStep={job?.current_step} jobStatus={job?.status} />}
        <main className="flex-1 overflow-y-auto">
          {stage === 'upload' && <UploadPage onUploadComplete={handleUploadComplete} />}
          {stage === 'loading' && <EarlyResultsView job={job} isTerminated={isTerminated} />}
          {stage === 'confirming' && job && <ConfirmationTable job={job} onConfirm={handleConfirm} />}
          {stage === 'step_3_complete' && job && <ResultPage job={job} onTriggerSandbox={handleTriggerSandbox} />}
          {stage === 'error' && <ErrorView error={error} onRetry={reset} />}
        </main>
      </div>
    </div>
  )
}
