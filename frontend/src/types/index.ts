export interface TestStrategy {
  primary: string
  secondary: string | null
}

export interface Step0Result {
  project_type: string
  frontend_framework: string | null
  frontend_tooling: string | null
  backend_framework: string | null
  template_engine: string | null
  service_layout: string
  server_routes_detected: boolean
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  test_strategy: TestStrategy
  config_files_found: string[]
  llm_used: boolean
  llm_model: string | null
  runtime?: string
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
  functional_area?: string
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

export interface Step2Requirement {
  req_id: string
  description: string
  source: 'obvious'
  reasoning: string
  tag: 'obvious'
  priority: 'critical' | 'high' | 'medium' | 'low'
  weight: number
  testable: boolean
  functional_area?: string
  depends_on?: string[]
}

export interface Step2Result {
  requirements: Step2Requirement[]
  total_count: number
  llm_model: string
  dropped_count: number
  error?: string
}

export interface Step3Requirement {
  req_id: string
  description: string
  source: 'generated'
  tag: 'generated'
  category: 'sop_a' | 'sop_b' | 'inf_c' | 'inf_d' | 'inf_e' | 'structural_edge'
  reasoning: string
  depends_on: string[]
  confidence_score: number
  confidence_reason: string
  l1_recommendation: 'l1a' | 'l1b'
  priority?: 'critical' | 'high' | 'medium' | 'low'
  strength?: 'strongly_implied' | 'medium' | 'weak' | null
  weight: number
  testable: boolean
  functional_area?: string
}

export interface Step3Result {
  requirements: Step3Requirement[]
  total_count: number
  sop_count: number
  inference_count: number
  llm_model: string | null
  dropped_count: number
  error?: string | null
}

export interface StepResults {
  step_0?: Step0Result
  step_1?: Step1Result
  step_2?: Step2Result
  step_3?: Step3Result
}

export type JobStatus =
  | 'created'
  | 'running'
  | 'step_2_complete'
  | 'step_3_complete'
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
