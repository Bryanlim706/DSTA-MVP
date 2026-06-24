import type { ConfirmedRequirement, Job } from '../types'

const API_BASE = 'http://localhost:8000/api'

export async function uploadProject(
  zipFile: File,
  requirements: string,
  sources: { useRequirementsBox: boolean; useReadme: boolean; useSpecFiles: boolean } = {
    useRequirementsBox: true,
    useReadme: true,
    useSpecFiles: false,
  },
): Promise<string> {
  const form = new FormData()
  form.append('project_zip', zipFile)
  form.append('requirements', requirements)
  form.append('use_requirements_box', String(sources.useRequirementsBox))
  form.append('use_readme', String(sources.useReadme))
  form.append('use_spec_files', String(sources.useSpecFiles))

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
      job.status === 'complete' ||
      job.status === 'terminated'
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

export async function triggerSandbox(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/sandbox`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Sandbox trigger failed')
  }
}

export async function terminateJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/terminate`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Terminate failed')
  }
}

export async function stopSandbox(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/sandbox/stop`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Sandbox stop failed')
  }
}

export async function confirmRequirements(
  jobId: string,
  requirements: ConfirmedRequirement[],
  skipped = false,
): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requirements, skipped }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Confirmation failed')
  }
}
