import { useEffect, useRef, useState } from 'react'
import { confirmRequirements, getJob, pollJob, triggerSandbox } from './api/client'
import ClassificationResult from './components/ClassificationResult'
import ConfirmationTable from './components/ConfirmationTable'
import GeneratedRequirementsResult from './components/GeneratedRequirementsResult'
import ObviousRequirementsResult from './components/ObviousRequirementsResult'
import AppCrawlerResult from './components/AppCrawlerResult'
import FA75AdvisorResult from './components/FA75AdvisorResult'
import SandboxResult from './components/SandboxResult'
import RepoParserResult from './components/RepoParserResult'
import ScoringResult from './components/ScoringResult'
import RequirementsResult from './components/RequirementsResult'
import Sidebar from './components/Sidebar'
import UploadPage from './pages/UploadPage'
import type { ConfirmedRequirement, Job } from './types'

type Stage = 'upload' | 'loading' | 'confirming' | 'step_3_complete' | 'error'

function LoadingView({ job }: { job: Job | null }) {
  const stepLabel =
    job?.current_step === 3
      ? 'Generating implied requirements…'
      : job?.current_step === 2
      ? 'Generating obvious requirements…'
      : job?.current_step === 1
      ? 'Extracting stated requirements…'
      : 'Classifying project type…'

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <div className="inline-block w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-sm font-medium text-gray-700">{stepLabel}</p>
        <p className="text-xs text-gray-400 mt-1">This usually takes 10–20 seconds</p>
        {job?.job_id && (
          <p className="text-[10px] text-gray-300 mt-2 font-mono">{job.job_id}</p>
        )}
      </div>
    </div>
  )
}

function EarlyResultsView({ job }: { job: Job }) {
  const step0 = job.step_results.step_0
  const step1 = job.step_results.step_1
  const step2 = job.step_results.step_2

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-gray-900">Requirements Analysis</h1>
          {job.project_name && (
            <p className="text-sm font-medium text-gray-600 mt-0.5">{job.project_name}</p>
          )}
          <p className="text-xs text-gray-400 mt-0.5">Steps 0–2 complete — generating implied requirements…</p>
          <p className="text-[10px] text-gray-300 mt-0.5 font-mono">{job.job_id}</p>
        </div>

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

        <div className="mt-6 flex items-center gap-3 px-5 py-4 bg-white rounded-xl border border-gray-200">
          <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-gray-700">Generating implied requirements…</p>
            <p className="text-xs text-gray-400 mt-0.5">This usually takes 10–15 seconds</p>
          </div>
        </div>
      </div>
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

function ResultPage({ job, onReset, onTriggerSandbox }: { job: Job; onReset: () => void; onTriggerSandbox: () => void }) {
  const step0 = job.step_results.step_0!
  const step1 = job.step_results.step_1!
  const step2 = job.step_results.step_2!
  const step3 = job.step_results.step_3
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
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Requirements Analysis</h1>
            {job.project_name && (
              <p className="text-sm font-medium text-gray-600 mt-0.5">{job.project_name}</p>
            )}
            <p className="text-xs text-gray-400 mt-0.5">
              {job.status === 'step_7_5_complete' ? 'Steps 0–7.5 complete'
            : job.status === 'step_7_complete' || job.status === 'step_7_5_running' ? 'Steps 0–7 complete'
            : job.status === 'step_6_complete' || job.status === 'step_7_running' ? 'Steps 0–6 complete'
            : job.status === 'step_5_complete' || job.status === 'step_6_running' ? 'Steps 0–5 complete'
            : job.status === 'step_4_complete' || job.status === 'step_5_running' ? 'Steps 0–4 complete'
            : 'Steps 0–3.5 complete'}
            </p>
            <p className="text-[10px] text-gray-300 mt-0.5 font-mono">{job.job_id}</p>
          </div>
          <button
            onClick={onReset}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            New analysis
          </button>
        </div>

        <ClassificationResult result={step0} />

        <div className="mt-6">
          <RequirementsResult result={step1} />
        </div>

        <div className="mt-6">
          <ObviousRequirementsResult result={step2} />
        </div>

        {step3 && (
          <div className="mt-6">
            <GeneratedRequirementsResult result={step3} />
          </div>
        )}

        {step35 && (
          <div className="mt-6 bg-green-50 border border-green-200 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-semibold text-green-800">Requirements Confirmed</span>
              {step35.skipped && (
                <span className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">skipped</span>
              )}
            </div>
            <div className="flex flex-wrap gap-3 text-xs text-green-700">
              <span><span className="font-medium">{step35.l1a_count}</span> requirements confirmed</span>
              {step35.promoted_count > 0 && (
                <span><span className="font-medium">{step35.promoted_count}</span> promoted from generated</span>
              )}
              {step35.deleted_count > 0 && (
                <span><span className="font-medium">{step35.deleted_count}</span> removed</span>
              )}
              {step35.added_count > 0 && (
                <span><span className="font-medium">{step35.added_count}</span> custom added</span>
              )}
              <span className="text-green-500">
                {new Date(step35.confirmed_at).toLocaleTimeString()}
              </span>
            </div>
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
    const jobId = window.location.hash.slice(1)
    if (!jobId) return
    getJob(jobId)
      .then((j) => {
        setJob(j)
        setStage(stageFromStatus(j.status))
      })
      .catch(() => {
        window.location.hash = ''
      })
  }, [])

  // Poll whenever stage is step_3_complete and status is non-terminal
  useEffect(() => {
    if (stage !== 'step_3_complete' || !job || pollingStep4.current) return
    const terminalStatuses = ['step_7_5_complete', 'step_7_5_error', 'step_7_error', 'step_6_error', 'step_5_error', 'step_4_error', 'step_11_complete', 'step_11_error', 'error', 'complete']
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
    window.location.hash = ''
    setStage('upload')
    setJob(null)
    setError(null)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar stage={stage} currentStep={job?.current_step} jobStatus={job?.status} />
      <main className="flex-1 overflow-y-auto">
        {stage === 'upload' && <UploadPage onUploadComplete={handleUploadComplete} />}
        {stage === 'loading' && (
          job?.step_results?.step_2
            ? <EarlyResultsView job={job} />
            : <LoadingView job={job} />
        )}
        {stage === 'confirming' && job && <ConfirmationTable job={job} onConfirm={handleConfirm} />}
        {stage === 'step_3_complete' && job && <ResultPage job={job} onReset={reset} onTriggerSandbox={handleTriggerSandbox} />}
        {stage === 'error' && <ErrorView error={error} onRetry={reset} />}
      </main>
    </div>
  )
}
