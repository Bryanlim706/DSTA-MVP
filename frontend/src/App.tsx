import { useState } from 'react'
import { pollJob } from './api/client'
import ClassificationResult from './components/ClassificationResult'
import UploadPage from './pages/UploadPage'
import type { Job } from './types'

type Stage = 'upload' | 'loading' | 'step_0_complete' | 'error'

function LoadingView({ job }: { job: Job | null }) {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <div className="inline-block w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="text-sm font-medium text-gray-700">
          {job?.status === 'running' ? 'Step 0 — Classifying project type…' : 'Starting analysis…'}
        </p>
        <p className="text-xs text-gray-400 mt-1">This usually takes 5–10 seconds</p>
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
  const result = job.step_results.step_0!
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-12">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Project Classification</h1>
            <p className="text-xs text-gray-400 mt-0.5">Step 0 complete — ready to proceed</p>
          </div>
          <button
            onClick={onReset}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 hover:border-gray-400 px-3 py-1.5 rounded-lg transition-colors"
          >
            New analysis
          </button>
        </div>

        <ClassificationResult result={result} />

        <div className="mt-6 bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm text-blue-700">
          <span className="font-medium">Next:</span> Step 1 — Parse repository structure (coming soon)
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [stage, setStage] = useState<Stage>('upload')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleUploadComplete(jobId: string) {
    setStage('loading')
    try {
      const completed = await pollJob(jobId, (j) => setJob(j))
      setJob(completed)
      setStage('step_0_complete')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
      setStage('error')
    }
  }

  function reset() {
    setStage('upload')
    setJob(null)
    setError(null)
  }

  if (stage === 'upload') return <UploadPage onUploadComplete={handleUploadComplete} />
  if (stage === 'loading') return <LoadingView job={job} />
  if (stage === 'step_0_complete' && job) return <ResultPage job={job} onReset={reset} />
  if (stage === 'error') return <ErrorView error={error} onRetry={reset} />
  return null
}
