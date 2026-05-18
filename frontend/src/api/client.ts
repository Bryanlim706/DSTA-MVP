import type { Job } from '../types'

const API_BASE = 'http://localhost:8000/api'

export async function uploadProject(zipFile: File, requirements: string): Promise<string> {
  const form = new FormData()
  form.append('project_zip', zipFile)
  form.append('requirements', requirements)

  const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Upload failed')
  }
  const data = await res.json()
  return data.job_id as string
}

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`)
  if (!res.ok) throw new Error(`Failed to fetch job: ${res.statusText}`)
  return res.json()
}

export async function pollJob(
  jobId: string,
  onUpdate: (job: Job) => void,
  intervalMs = 2000,
  timeoutMs = 300_000,
): Promise<Job> {
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    const job = await getJob(jobId)
    onUpdate(job)

    if (
      job.status === 'step_2_complete' ||
      job.status === 'step_3_complete' ||
      job.status === 'waiting_for_confirmation' ||
      job.status === 'complete'
    ) {
      return job
    }

    if (job.status === 'error') {
      throw new Error(job.errors[0] ?? 'Pipeline failed')
    }

    await new Promise((r) => setTimeout(r, intervalMs))
  }

  throw new Error('Timed out waiting for analysis to complete')
}
