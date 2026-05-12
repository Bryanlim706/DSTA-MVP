export interface TestStrategy {
  primary: string
  secondary: string | null
}

export interface Step0Result {
  project_type: string
  frontend_framework: string | null
  backend_framework: string | null
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  test_strategy: TestStrategy
  config_files_found: string[]
  llm_used: boolean
  llm_model: string | null
}

export interface StepResults {
  step_0?: Step0Result
}

export type JobStatus =
  | 'created'
  | 'running'
  | 'step_0_complete'
  | 'waiting_for_confirmation'
  | 'complete'
  | 'error'

export interface Job {
  job_id: string
  status: JobStatus
  current_step: number
  step_results: StepResults
  errors: string[]
  created_at: string
  updated_at: string
  requirements_text?: string
}
