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

export interface PathEntity {
  type: 'node' | 'element' | 'edge'
  label: string
  primary: boolean
  ui_node?: string
  from?: string | null
  to?: string | null
}

export interface Step1Requirement {
  req_id: string
  description: string
  path: PathEntity[]
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
  project_summary?: string
  error?: string
}

export interface Step2Requirement {
  req_id: string
  description: string
  path: PathEntity[]
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
  path: PathEntity[]
  source: 'generated'
  tag: 'generated'
  category: 'sop' | 'inf'
  reasoning: string
  depends_on: string[]
  confidence_score: number
  confidence_reason: string
  placement: 'l1a' | 'l1b'
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

export interface ConfirmedRequirement {
  req_id: string
  description: string
  path: PathEntity[]
  tag: 'stated' | 'obvious' | 'generated' | 'custom'
  priority: 'critical' | 'high' | 'medium' | 'low'
  weight: number
  functional_area?: string
  testable: boolean
  source: string
  promoted?: boolean
  depends_on: string[]
  source_quote: string | null
}

export interface Step35Result {
  confirmed_requirements: ConfirmedRequirement[]
  advisory_requirements: Step3Requirement[]
  project_context: Record<string, unknown>
  project_summary: string | null
  confirmed_at: string
  skipped: boolean
  l1a_count: number
  promoted_count: number
  deleted_count: number
  added_count: number
}

export interface ApiEndpoint {
  method: string
  path: string
  file: string
  handler: string
}

export interface FrontendRoute {
  path: string
  dynamic: boolean
  params: string[]
}

export interface ImplementationUnit {
  kind: 'api_endpoint' | 'form_handler'
  method: string
  path: string | null
  file: string | null
  handler: string | null
}

export interface Step4Element {
  type: 'input' | 'button' | 'select' | 'textarea'
  subtype: string | null
  label: string
}

export interface Step4Result {
  languages: string[]
  frontend_routes: FrontendRoute[]
  implementation_units: ImplementationUnit[]
  route_elements: Record<string, Step4Element[]>
  navigation_graph: Record<string, string[]>
  database_models: string[]
  important_files: string[]
  existing_tests: string[]
  total_endpoints: number
  total_routes: number
  error: string | null
}

export interface Step5Element {
  type: 'input' | 'button' | 'select' | 'textarea' | 'link'
  subtype: string | null
  label: string | null
  selector: string | null
  visible: boolean | null
}

export interface Step5Page {
  route: string
  title: string | null
  discovered_by: 'playwright' | 'static_fallback'
  accessible: boolean | null
  elements: Step5Element[]
  outbound_links: string[]
  api_calls_observed: string[]
}

export interface Step5UnvisitableRoute {
  route: string
  reason: string
}

export interface Step5Result {
  pages: Step5Page[]
  unvisitable_routes: Step5UnvisitableRoute[]
  total_pages: number
  error: string | null
}

export interface Step5ElementDetail {
  type: string | null
  subtype: string | null
  label: string | null
  selector: string | null
  visible: boolean | null
}

export interface EntityScore {
  label: string
  type: 'node' | 'element' | 'edge'
  primary: boolean
  e: number | null
  evidence?: string
  matched_route?: string | null
  matched_element_label?: string | null
  matched_selector?: string | null
  match_source?: string | null
  step5_element?: Step5ElementDetail | null
  edge_kind?: 'data' | 'navigation' | 'structural'
  matched_endpoint?: string | null
  trigger_element_label?: string | null
  matched_nav_target?: string | null
  triggering_element_found?: boolean | null
}

export interface MappedRequirement {
  req_id: string
  description: string
  placement: 'l1a' | 'l1b'
  tag: string
  priority: string
  weight: number
  e_score: number
  weighted_e: number
  entity_scores: EntityScore[]
}

export interface Step6Result {
  mapped: MappedRequirement[]
  unlinked_l2: { route: string; title: string | null; note: string }[]
  unlinked_l3: { method?: string | null; path?: string | null; handler?: string | null; file?: string | null; note: string }[]
  llm_model: string | null
  error: string | null
}

export interface Step7Advisory {
  req_id: string
  description: string
  e_score: number
  weight: number
  strength?: string | null
}

export interface Step7Result {
  fcom: number
  fa: number
  fcom_detail: { numerator: number; denominator: number; requirement_count: number }
  fa_detail: { numerator: number; denominator: number; requirement_count: number }
  fcom_advisory: {
    missing_l1a: Step7Advisory[]
    unlinked_routes: Step6Result['unlinked_l2']
    unlinked_endpoints: Step6Result['unlinked_l3']
  }
  fa_advisory: { missing_l1b: Step7Advisory[] }
  error: string | null
}

export interface FA75Suggestion {
  suggestion_id: string
  description: string
  grounded_in: {
    models: string[]
    endpoints: string[]
    rationale: string
  }
  l1a_connection: string | null
  priority: 'high' | 'medium' | 'low'
}

export interface Step75Result {
  suggestions: FA75Suggestion[]
  total_count: number
  llm_model: string | null
  error: string | null
}

export interface BehavioralRequirement {
  req_id: string
  description: string
  path: PathEntity[]
  priority: 'critical' | 'high' | 'medium' | 'low'
  weight: number
  source_quote: string | null
}

export interface Step8Result {
  behavioral_requirements: BehavioralRequirement[]
  llm_model: string | null
  error: string | null
}

export interface AcceptanceCriterion {
  ac_id: string
  given: string
  when: string
  then: string
  acw: number
  type: 'happy_path' | 'persistence' | 'edge_case' | 'fires_when_due' | 'not_before_due'
}

export interface ACRequirementResult {
  req_id: string
  description: string
  type: 'l1a' | 'l1b' | 'behavioral'
  goal_kind: 'data' | 'structural' | 'navigation' | 'presence' | 'behavioral'
  l1cx: number
  test_type: 'e2e' | 'api' | 'behavioral'
  acceptance_criteria: AcceptanceCriterion[]
}

export interface Step85Result {
  acceptance_criteria: ACRequirementResult[]
  selected_ids: string[]
  total_acs: number
  llm_model: string | null
  error: string | null
}

export interface Step11TestResult {
  req_id: string
  ac_id: string
  result: 'pass' | 'fail' | 'blocked' | 'untestable' | 'flaky'
  reason: string | null
  duration_ms: number | null
}

export interface Step11Result {
  boot_status: 'success' | 'partial' | 'boot_failed'
  backend_url: string | null
  frontend_url: string | null
  backend_accessible: boolean
  frontend_accessible: boolean
  spring_profile_used: string | null
  h2_dep_found: boolean
  db_type: 'mysql' | 'postgresql' | 'mariadb' | null
  build_tool: 'maven' | 'gradle' | null
  frontend_type: 'vite' | 'cra' | 'angular' | 'nextjs' | 'generic' | null
  build_time_s: number | null
  boot_time_s: number | null
  test_results: Step11TestResult[]
  sandbox_warnings: string[]
  error: string | null
}

export interface StepResults {
  step_0?: Step0Result
  step_1?: Step1Result
  step_2?: Step2Result
  step_3?: Step3Result
  step_3_5?: Step35Result
  step_4?: Step4Result
  step_5?: Step5Result
  step_6?: Step6Result
  step_7?: Step7Result
  step_7_5?: Step75Result
  step_8?: Step8Result
  step_8_5?: Step85Result
  step_11?: Step11Result
}

export type JobStatus =
  | 'created'
  | 'running'
  | 'step_2_complete'
  | 'step_3_complete'
  | 'waiting_for_confirmation'
  | 'confirmed'
  | 'step_4_running'
  | 'step_4_complete'
  | 'step_4_error'
  | 'step_5_running'
  | 'step_5_complete'
  | 'step_5_error'
  | 'step_6_running'
  | 'step_6_complete'
  | 'step_6_error'
  | 'step_7_running'
  | 'step_7_complete'
  | 'step_7_error'
  | 'step_7_5_running'
  | 'step_7_5_complete'
  | 'step_7_5_error'
  | 'step_8_running'
  | 'step_8_complete'
  | 'step_8_error'
  | 'step_8_5_running'
  | 'step_8_5_complete'
  | 'step_8_5_error'
  | 'step_11_running'
  | 'step_11_complete'
  | 'step_11_error'
  | 'complete'
  | 'error'
  | 'terminated'

export interface Job {
  job_id: string
  status: JobStatus
  current_step: number
  step_results: StepResults
  errors: string[]
  created_at: string
  updated_at: string
  requirements_text?: string
  project_name?: string
}
