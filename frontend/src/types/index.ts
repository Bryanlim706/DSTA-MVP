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

export interface Step1Requirement {
  req_id: string
  description: string
  source: string
  source_quote: string
  tag: 'stated'
  priority: 'critical' | 'high' | 'medium' | 'low'
  weight: number
  testable: boolean
}

export interface Step1Result {
  requirements: Step1Requirement[]
  total_count: number
  docs_used: string[]
  truncated_docs: string[]
  llm_model: string
  dropped_count: number
  error?: string
}

export interface StepResults {
  step_0?: Step0Result
  step_1?: Step1Result
}

export type JobStatus =
  | 'created'
  | 'running'
  | 'step_1_complete'
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
