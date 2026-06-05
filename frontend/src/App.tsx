import { useEffect, useRef, useState } from 'react'
import { confirmRequirements, getJob, pollJob } from './api/client'
import ClassificationResult from './components/ClassificationResult'
import ConfirmationTable from './components/ConfirmationTable'
import GeneratedRequirementsResult from './components/GeneratedRequirementsResult'
import ObviousRequirementsResult from './components/ObviousRequirementsResult'
import AppCrawlerResult from './components/AppCrawlerResult'
import FA75AdvisorResult from './components/FA75AdvisorResult'
import MappingResult from './components/MappingResult'
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
      ? 'Step 3 — Generating implied requirements…'
      : job?.current_step === 2
      ? 'Step 2 — Generating obvious requirements…'
      : job?.current_step === 1
      ? 'Step 1 — Extracting stated requirements…'
      : 'Step 0 — Classifying project type…'

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

function ResultPage({ job, onReset }: { job: Job; onReset: () => void }) {
  const step0 = job.step_results.step_0!
  const step1 = job.step_results.step_1!
  const step2 = job.step_results.step_2!
  const step3 = job.step_results.step_3
  const step35 = job.step_results.step_3_5
  const step4 = job.step_results.step_4
  const step5 = job.step_results.step_5

  const step4Loading = job.status === 'step_4_running' || job.status === 'confirmed'
  const step5Loading = job.status === 'step_5_running' || job.status === 'step_4_complete'
  const step6Loading = job.status === 'step_6_running' || job.status === 'step_5_complete'
  const step7Loading = job.status === 'step_7_running' || job.status === 'step_6_complete'
  const step75Loading = job.status === 'step_7_5_running' || job.status === 'step_7_complete'

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Requirements Analysis</h1>
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
              <span className="text-sm font-semibold text-green-800">Step 3.5 — L1a Locked</span>
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
          <MappingResult result={job.step_results.step_6 ?? null} loading={step6Loading} />
        </div>

        <div className="mt-6">
          <ScoringResult result={job.step_results.step_7 ?? null} loading={step7Loading} />
        </div>

        <div className="mt-6">
          <FA75AdvisorResult result={job.step_results.step_7_5 ?? null} loading={step75Loading} />
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [stage, setStage] = useState<Stage>('upload')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollingStep4 = useRef(false)

  // Poll for step_4_complete after entering result view
  useEffect(() => {
    if (stage !== 'step_3_complete' || !job || pollingStep4.current) return
    const terminalStatuses = ['step_7_5_complete', 'step_7_5_error', 'step_7_error', 'step_6_error', 'step_5_error', 'step_4_error', 'error', 'complete']
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
  }, [stage])

  async function handleUploadComplete(jobId: string) {
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

  function reset() {
    setStage('upload')
    setJob(null)
    setError(null)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar stage={stage} currentStep={job?.current_step} jobStatus={job?.status} />
      <main className="flex-1 overflow-y-auto">
        {stage === 'upload' && <UploadPage onUploadComplete={handleUploadComplete} />}
        {stage === 'loading' && <LoadingView job={job} />}
        {stage === 'confirming' && job && <ConfirmationTable job={job} onConfirm={handleConfirm} />}
        {stage === 'step_3_complete' && job && <ResultPage job={job} onReset={reset} />}
        {stage === 'error' && <ErrorView error={error} onRetry={reset} />}
      </main>
    </div>
  )
}
