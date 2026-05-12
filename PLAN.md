# Functional Suitability Evaluator (ISO 25010) — Implementation Plan

## Overview

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM explains results, never overrides them.

---

## Conceptual Model (4 Layers)

| Layer | Name | What it captures |
|---|---|---|
| L1a | **Confirmed** | Stated (Step 1) + obvious (Step 2) requirements, locked after Step 3.5 |
| L1b | **Implied** | Enhancement functions — advisory only unless promoted at Step 3.5 |
| L2 | **Exposed** | What the UI/API actually makes accessible to users |
| L3 | **Implemented** | What the code actually contains |
| L4 | **Verified** | What actually works end-to-end when executed |

**L1a = Stated (Step 1) + Obvious (Step 2), confirmed at Step 3.5**
**L1b = Implied enhancements (Step 3), advisory only**

---

## ISO Sub-Characteristic Formulas

### Functional Completeness (FC) — L1a vs (L2 ∪ L3)

```
FC = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1a]
```

| E(L1x) | Condition |
|---|---|
| 1.0 | x ∈ L2 AND x ∈ L3 — accessible and implemented |
| 0.5 | x ∈ L3 only — implemented but not accessible |
| 0.4 | x ∈ L2 only — UI visible, backend missing/broken |
| 0.25 | Partial or unclear evidence in either layer |
| 0.0 | Not found anywhere |

`L1Cx` = confidence weight (high = 3, medium = 2, low = 1; default 1.0)

### Functional Appropriateness (FA) — L1b vs (L2 ∪ L3)

**ISO 25010 clause 3.1.3:** *"A product provides the necessary and sufficient steps to complete a task, excluding any unnecessary steps."*

This grounds the biconditional:
- L1b → (L2∪L3): *necessary direction* — are implied functions present? → scored
- (L2∪L3) → L1b: *sufficient/unnecessary direction* — are there functions with no stated purpose? → advisory only

The (L2∪L3) → L1b direction is advisory only because "unnecessary steps" has complex relationships with intentional redundancy for UI intuitiveness and roadmap decisions.

```
FA = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1b]
```

`L1Cx` for L1b items = weight derived from LLM-assigned strength:

| Strength | L1Cx weight |
|---|---|
| strongly_implied | 3 |
| medium | 2 |
| weak | 1 |

FA is **advisory only**. The weighted formula means a missing `strongly_implied` function penalises FA more than a missing `weak` one — mirroring how L1a priority weights FC.

### Functional Correctness (FCo) — L4 vs L1a ∩ L3

AC-level scoring. Each requirement has multiple acceptance criteria; sub-weights sum to L1Cx.

```
S   = { x ∈ L1a | x ∈ L3 }              — eligible set (backend implemented)
S*  = S \ { x | all ACs blocked }        — testable subset

FCo = ∑(pass_i × ACw_i) / ∑ ACw_i       [i ∈ ACs of requirements in S*]
CP  = ∑_blocked_L1Cx / ∑_all_L1Cx
```

**Why L3 only, not (L2 ∪ L3):** Requirements where E()=0.4 (UI stub, no backend) would trivially fail correctness tests — FC already penalises them. Scoping to L3 avoids double punishment.

| E() | In S? | Test type |
|---|---|---|
| 1.0 (L2 ∧ L3) | Yes | E2E — Playwright + API |
| 0.5 (L3 only) | Yes | API only — no Playwright |
| 0.4 (L2 only) | No | Excluded — FC already penalises |
| 0.25 / 0.0 | No | Excluded |

| pass_i | Condition |
|---|---|
| 1.0 | AC passed |
| passes/3 | Flaky — run 3×, score = fraction passed |
| 0.0 | AC failed |
| — | Fully blocked — excluded from S*, weight added to CP |

`CP` = confidence penalty, reported separately alongside FCo.

### Final Score

```
Functional Suitability = 0.50 × FC + 0.50 × FCo
Functional Appropriateness = Advisory only (reported separately)
```

Alternative (if all three sub-characteristics must be numerically scored): 40% FC + 45% FCo + 15% FA. Preferred option is 50/50 because FC and FCo are backed by harder evidence.

---

## Pipeline Steps

### Step −1: User Input
**Input requirements:**
- Uploaded codebase as a `.zip` file
- Requirements document or plain-text description (required — software with no requirements cannot be meaningfully evaluated)
- Software must be functionally purposeful — a skeleton or toy project will produce a low-signal score

---

### Step 0: Project Type & Scope Classifier
**Status: COMPLETE**
**Phase: FCom setup**
**Tools:** Python, pathlib, json/yaml/toml, LLM (AsyncAnthropic, prompt caching)
**Input:** File tree + config file contents from uploaded zip
**Logic:** Rule-based first — scans config files (package.json, requirements.txt, pyproject.toml, etc.), counts file extensions. LLM only called when file inspection is inconclusive.
**Output:**
```json
{
  "project_type": "full_stack_web_app",
  "frontend_framework": "React",
  "backend_framework": "FastAPI",
  "confidence": "high",
  "reasoning": "...",
  "test_strategy": { "primary": "Playwright E2E", "secondary": "Pytest API tests" },
  "config_files_found": ["package.json", "requirements.txt"],
  "llm_used": false,
  "llm_model": null
}
```
Note: `primary_language` is not in Step 0 output. Step 4 produces the authoritative `languages` array from source parsing.

---

### Step 1: Stated Requirement Extractor
**Phase: FCom setup — builds L1a (stated)**
**Tools:** Python, LLM (AsyncAnthropic, prompt caching)
**Input:** Requirements text provided by user + README (read directly from zip) + any uploaded specification documents
**Rule:** Only extract requirements that are **explicitly stated**. No inference. No invention. Every item must include its source quote.
**Decomposition rule:** General/meta requirements decomposed into atomic testable items, each retaining a reference to its parent.
**Tag:** `stated`
**Output:**
```json
[
  {
    "req_id": "REQ-001",
    "description": "User can register an account",
    "source": "user_input",
    "source_quote": "users should be able to register and log in",
    "tag": "stated",
    "priority": "high",
    "weight": 3.0,
    "testable": true
  }
]
```

---

### Step 2: Obvious Requirement Generator
**Phase: FCom setup — builds L1a (obvious)**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** Step 0 (project_type, framework) + Step 1 (stated requirements list)
**Logic:** LLM generates obvious functional requirements that any user of this app type would naturally expect — so fundamental a user would never write them down, yet surprised to find missing.
**Deduplication:** Step 1 stated requirements passed as context; LLM must not regenerate items already stated.
**ISO 25010 rationale:** Completeness covers "all specified tasks and user objectives." Obvious requirements are user objectives implied by the app's purpose even when not explicitly written.
**Tag:** `obvious` | **Default weight:** 1.0 (user can override at Step 3.5)
**Output:**
```json
[
  {
    "req_id": "OBV-001",
    "description": "User can delete a task",
    "source": "obvious",
    "reasoning": "Any task management app user expects to be able to delete tasks",
    "tag": "obvious",
    "priority": "medium",
    "weight": 1.0,
    "testable": true
  }
]
```

**Combined L1a pool:** Step 1 (stated) + Step 2 (obvious) → forms the initial L1a before Step 3.5 confirmation.

---

### Step 3: L1b Implied Enhancement Generator
**Phase: FCom setup — builds L1b**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** Step 0 (project type) + Step 1 + Step 2 (combined L1a)
**Logic:** Generates advisory enhancements beyond L1a. LLM assigns a **strength rating** to each item, which maps directly to its FA weight.

| Strength | FA weight (L1Cx) |
|---|---|
| strongly_implied | 3 |
| medium | 2 |
| weak | 1 |

**Key distinction from Step 2:** Step 2 generates what a user *expects* to be present (obvious = "of course it has delete"). Step 3 generates what a user *might want* but wouldn't be surprised to find missing (implied = "it would be nice if it had bulk delete").
**Advisory only:** Not scored unless promoted to L1a at Step 3.5. `strongly_implied` items auto-surfaced at Step 3.5 as promotion candidates.
**Tag:** `implied`
**Output:**
```json
[
  {
    "req_id": "L1B-001",
    "description": "User can filter tasks by status",
    "source": "implied",
    "reasoning": "Common in task managers; improves usability at scale",
    "tag": "implied",
    "strength": "strongly_implied",
    "weight": 3.0,
    "priority": "medium",
    "testable": true
  },
  {
    "req_id": "L1B-002",
    "description": "User can bulk-delete multiple tasks",
    "source": "implied",
    "reasoning": "Power user feature; not expected by default",
    "tag": "implied",
    "strength": "weak",
    "weight": 1.0,
    "priority": "low",
    "testable": true
  }
]
```

---

### Step 3.5: Human Requirement Confirmation *(optional)*
**Phase: FCom setup — locks L1a**
**Tools:** React UI, FastAPI endpoint, async job queue
**Input:** Step 1 (stated) + Step 2 (obvious) + Step 3 (L1b with strength and weights)
**Architecture:** Pipeline pauses with status `waiting_for_confirmation`. Resumes when user submits confirmed list.

**User can:**
- Confirm, edit, delete, reprioritise any L1a item
- Adjust confidence weights (high=3, medium=2, low=1)
- Promote L1b items to L1a (adds them to FC and FCo scoring)
- Add entirely new requirements

**Display format:**
| Requirement | Tag | In score? | Priority | Weight |
|---|---|---|---|---|
| User can register | stated | Yes (L1a) | High | 3 |
| User can delete a task | obvious | Yes (L1a) | Medium | 1 |
| User can filter tasks | implied — strongly_implied | Advisory | Medium | 3 |
| User can bulk-delete | implied — weak | Advisory | Low | 1 |

`strongly_implied` L1b items are highlighted with a "+ Add to requirements" prompt. Medium and weak items are listed below without auto-prompting.

**After confirmation:** L1a is locked. Pipeline resumes.
**If skipped:** All stated + obvious items treated as L1a at default weights. L1b remains advisory.

---

### Step 4: Repo Parser
**Phase: FCom setup**
**Tools:** Python (zipfile, pathlib), Tree-sitter, json/yaml/toml
**Input:** Uploaded zip file
**Extracts:** README, frontend routes/pages, backend routes/endpoints, forms/buttons/components, API specs, package scripts, existing tests, config files, database models
**Ignores:** node_modules, .git, dist, build, .next, venv, __pycache__, coverage
**Output:**
```json
{
  "languages": ["TypeScript", "Python"],
  "frontend_routes": ["/login", "/dashboard", "/tasks"],
  "api_endpoints": [
    { "method": "POST", "path": "/api/login", "file": "backend/routes/auth.py", "handler": "login_user" }
  ],
  "database_models": ["User", "Task"],
  "important_files": ["src/pages/Login.tsx", "backend/routes/auth.py"],
  "existing_tests": ["tests/test_auth.py"]
}
```

---

### Step 5: UI/API Inventory Generator (L2)
**Phase: FCom — builds L2**
**Tools:** Tree-sitter (static), Playwright (dynamic), LLM (summarization), Python
**Input:** Uploaded zip + Step 0 (project type for strategy selection)

**Three-pass process:**
1. **Static analysis (Tree-sitter):** Extracts raw UI elements — routes, pages, buttons, forms, links, input fields, event handlers, API calls
2. **Dynamic analysis (Playwright):** Crawls running app — discovers visible pages, clickable buttons, accessible forms, nav paths, modals, error messages. Extracts real CSS selectors and data-testid attributes.
3. **LLM summarization:** Takes raw elements from passes 1 and 2 and groups them into named user-facing functions. Without this pass, Step 5 outputs "Email input, Password input, Login button" but cannot identify these as "User can log in." The LLM converts low-level elements → interpretable named functions, making Step 6 mapping significantly more accurate.

**Output:**
```json
[
  {
    "function_id": "L2-001",
    "function": "User can log in",
    "route": "/login",
    "ui_evidence": ["Email input", "Password input", "Login button"],
    "api_calls": ["POST /api/login"],
    "selectors": {
      "email_input": "[data-testid='email-input']",
      "password_input": "[data-testid='password-input']",
      "submit_button": "[data-testid='login-button']"
    },
    "discovered_by": "static"
  }
]
```

**Key value:** Dynamic crawl catches features in code not accessible in the UI. LLM summarization makes L2 functions mappable. Selectors feed directly into Step 9 test generation.

---

### Step 6: Requirement-to-UI/API/Code Mapper
**Phase: FCom — cross-links L1 → L2, L3**
**Tools:** Tree-sitter, LLM (AsyncAnthropic), JSON traceability matrix
**Input:** Step 1+2 (L1a) + Step 3 (L1b) + Step 5 (L2) + Step 4 (L3 skeleton)
**Logic:** Maps each L1a and L1b requirement → L2 named functions → API endpoints → backend functions → database models. Produces E() score for each L1a item.
**Unlinked detection:**
```python
l2_unlinked = set(step5_all_ids) - set(step6_matched_l2_ids)
l3_unlinked = set(step4_endpoint_ids) - set(step6_matched_l3_ids)
```
**Output:**
```json
{
  "mapped": [
    {
      "req_id": "REQ-001",
      "description": "User can log in",
      "l2_match": { "function_id": "L2-001", "confidence": "high" },
      "l3_match": { "endpoint": "POST /api/login", "handler": "login_user", "file": "backend/routes/auth.py" },
      "e_score": 1.0
    }
  ],
  "unlinked_l2": [
    { "function_id": "L2-007", "function": "Admin panel", "route": "/admin", "note": "No requirement points to this" }
  ],
  "unlinked_l3": [
    { "endpoint": "DELETE /api/users/:id", "handler": "delete_user", "note": "No requirement points to this" }
  ]
}
```

---

### Step 7: Functional Completeness + Appropriateness Scorer
**Phase: FCom — numeric scoring**
**Tools:** Python (formula only — no LLM for numeric scoring)
**Input:** Step 6 (traceability matrix with E() scores) + Step 1+2 (L1a weights) + Step 3 (L1b with strength-derived weights)
**Computes in one pass:**
1. **FC numeric:** `∑(E × weight) / ∑weight` for all L1a, where weight = user-assigned priority
2. **FA numeric:** `∑(E × weight) / ∑weight` for all L1b, where weight = strength-derived (3/2/1)
3. **FC advisory — missing L1a:** L1a items with E()=0.0 or low E(), listed with gap description
4. **FC advisory — unlinked functions:** L2_unlinked and L3_unlinked from Step 6
5. **FA advisory — missing L1b:** L1b items with E()=0.0, weighted by strength
6. **FA advisory — unlinked functions:** same L2/L3 unlinked list (functions with no stated purpose, per ISO 3.1.3 "unnecessary steps")

**Output:**
```json
{
  "functional_completeness": {
    "score": 0.84,
    "per_requirement": [
      { "req_id": "REQ-001", "description": "User can log in", "e_score": 1.0, "weight": 3.0, "contribution": 3.0 }
    ],
    "advisory": {
      "missing_l1a": [
        { "req_id": "OBV-003", "description": "User can edit a task", "e_score": 0.0, "gap": "Not found in L2 or L3" }
      ],
      "unlinked_functions": [
        { "function_id": "L2-007", "function": "Admin panel", "route": "/admin", "note": "No requirement points to this" }
      ]
    }
  },
  "functional_appropriateness": {
    "score": 0.71,
    "per_implied": [
      { "req_id": "L1B-001", "description": "User can filter tasks", "e_score": 1.0, "weight": 3.0, "contribution": 3.0 },
      { "req_id": "L1B-002", "description": "User can bulk-delete tasks", "e_score": 0.0, "weight": 1.0, "contribution": 0.0 }
    ],
    "advisory": {
      "missing_l1b": [
        { "req_id": "L1B-002", "description": "User can bulk-delete tasks", "e_score": 0.0, "strength": "weak" }
      ]
    }
  }
}
```

**Dashboard checkpoint:** FC numeric + FA numeric + all advisories displayed together in the coverage view. First deliverable milestone — no test execution required.

---

### Step 8: Acceptance Criteria Generator
**Phase: FCor setup**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** L1a requirement list as finalised after Step 3.5 (or directly from Step 1+2 if Step 3.5 was skipped), including locked L1Cx per requirement
**Scope:** Only generates ACs for requirements in S = { x ∈ L1a | x ∈ L3 }. Requirements with E()=0.4, 0.25, or 0.0 are skipped — their gaps are already captured in FC advisory.
**Logic:** Converts each eligible L1a requirement into Given/When/Then ACs. LLM assigns sub-weights per AC that **sum to the requirement's L1Cx**. Persistence and edge cases are ACs of L1a requirements — not separate L1b items.
**Output:**
```json
{
  "req_id": "REQ-003",
  "l1cx": 2.0,
  "acceptance_criteria": [
    { "ac_id": "AC-003-1", "given": "User is logged in", "when": "User enters valid task title and clicks Add", "then": "New task appears in the list", "acw": 0.8, "type": "happy_path" },
    { "ac_id": "AC-003-2", "given": "User has created a task", "when": "Page is refreshed", "then": "Task remains visible", "acw": 0.8, "type": "persistence" },
    { "ac_id": "AC-003-3", "given": "User is logged in", "when": "User submits empty task title", "then": "Validation error shown, no task created", "acw": 0.4, "type": "edge_case" }
  ]
}
```
Sub-weights: 0.8 + 0.8 + 0.4 = 2.0 = L1Cx ✓

---

### Step 9: Test Case Generator
**Phase: FCor setup**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** Step 8 acceptance criteria + **Step 5 L2 selectors (required)**
**Critical dependency:** Step 9 **explicitly depends on Step 5's selector-level L2 output**. Tests use real selectors (`[data-testid='login-button']`) from Step 5 — not invented guesses.
**Test type by E() score:**
- E()=1.0: Playwright E2E + API tests
- E()=0.5: API tests only (no UI to drive)

| Project type | Test type |
|---|---|
| React/Vue/Angular | Playwright (TypeScript) |
| Python backend/API | Pytest |
| Node/Express API | Jest / Supertest |
| Full-stack | Playwright E2E + API tests |
| CLI tool | Python subprocess tests |

---

### Step 10: Test Oracle Validator
**Phase: FCor setup**
**Tools:** Python (rule-based), LLM (semantic), Tree-sitter/regex
**Input:** Step 9 generated tests + Step 8 acceptance criteria
**Rejects tests that:** don't match the requirement or AC, lack meaningful assertions, only check element existence, skip persistence/side effects when required, cover only happy path when edge case ACs exist
**Output:** Validated test suite + rejection log with reasons

---

### Step 11: Test Execution Sandbox
**Phase: FCor — produces L4**
**Tools:** Docker, Python subprocess, Playwright, Pytest, Jest/Vitest
**Docker boot sequence:**
1. Detect package manager (npm/pip/poetry/cargo)
2. Install dependencies
3. Start app
4. Health-check until ready
5. Pass base URL to Playwright/Pytest

| Result | Meaning |
|---|---|
| Pass | Behaviour verified |
| Fail | Behaviour incorrect |
| Blocked | App could not run |
| Untestable | No accessible interface |
| Flaky | Inconsistent across runs (run 3×, pass_i = passes/3) |

**Blocked ≠ Failed.** Blocked lowers CP but does not prove incorrect behaviour.

---

### Step 12: Behaviour Evidence Collector
**Phase: FCor — enriches L4**
**Tools:** Python, Playwright trace API, Docker logs
**Collects:** Screenshots, Playwright traces, console errors, network logs, API responses, DB state before/after, stack traces
**Output:**
```json
{
  "req_id": "REQ-003",
  "ac_id": "AC-003-1",
  "result": "fail",
  "reason": "POST /api/tasks returned 500",
  "network_error": "Missing user_id field",
  "screenshot": "artifacts/REQ-003-AC-003-1-failure.png"
}
```

---

### Step 13: Functional Correctness Scorer
**Phase: FCor — numeric scoring**
**Tools:** Python (formula only)
**Formula:**
```
S   = { x ∈ L1a | x ∈ L3 }
S*  = S \ { x | all ACs blocked }

FCo = ∑(pass_i × ACw_i) / ∑ ACw_i      [i ∈ ACs of requirements in S*]
CP  = ∑_blocked_L1Cx / ∑_all_L1Cx
```
Requirements excluded from S (E()=0.4, 0.25, 0.0) do not appear in FCo — their gaps are captured in FC.
**Output:** FCo ratio + per-requirement AC breakdown + CP confidence penalty

---

### Step 14: Functional Appropriateness — Workflow Friction Analyser
**Phase: FA advisory**
**Tools:** Python, Playwright trace data, LLM (AsyncAnthropic)
**Input:** Step 5 dynamic crawl data + Step 12 Playwright traces + Step 8 ACs
**Analyses:** Steps to complete core tasks, discoverability, label clarity, error message quality, workflow interruptions, feedback after actions.
**Note:** Step 7 covers structural FA (are implied functions present, weighted by strength?). Step 14 covers experiential FA (does the UI help users accomplish their goals efficiently?). Together they form the full FA advisory.
**Advisory only — not included in main score**
**Output:**
```json
{
  "appropriateness_risk": "medium",
  "confidence": 0.68,
  "findings": [
    "Task creation accessible from dashboard in 2 steps — good",
    "Task editing hidden behind unclear icon — poor discoverability",
    "Failed login shows generic error — poor feedback"
  ]
}
```

---

### Step 15: Evidence Pack Builder
**Phase: Output**
**Tools:** Python, JSON, HTML report generator
**Input:** All step outputs (−1 through 14)
**Aggregates** all layer data into one structured, auditable evidence package. Every score is traceable: FCo → AC results → test logs → L4; FC → E() scores → L2/L3 evidence → L1a requirements.

---

### Step 16: LLM ISO Evaluator
**Phase: Output**
**Tools:** Python, Anthropic SDK (claude-sonnet-4-6), prompt caching on system prompt
**Input:** Step 15 evidence pack
**LLM does:** Explain scores, summarise strongest/weakest evidence, identify gaps, give recommendations, state limitations and confidence flags.
**LLM does NOT:** Override formula scores, invent features, treat L1b as confirmed, assume blocked = failed.
**Output:**
```json
{
  "final_score": 3.95,
  "summary": "The software implements most core requirements, but task deletion is only partially exposed and task editing failed one edge-case test.",
  "recommendations": [
    "Expose task deletion through the UI if intended to be user-facing.",
    "Fix edit-task validation failure for empty task titles.",
    "Add E2E tests for all high-priority user flows."
  ],
  "limitations": [
    "Bulk delete was AI-implied and not included in the main score.",
    "Some tests were blocked because environment variables were missing."
  ]
}
```

---

### Step 17: Dashboard
**Phase: Output**
**Tools:** React + TypeScript, FastAPI (data served from evidence pack)
**Input:** Step 15 evidence pack + Step 16 LLM evaluation
**Shows:**
- Final Functional Suitability Score (0–5)
- FC score + FA advisory with data layer comparison labels
- FCo score + CP confidence penalty
- Requirement traceability matrix (interactive, per-row status)
- Layer gap summary (L1 count → L2 exposed → L3 implemented → L4 verified)
- Test results with screenshots and logs
- Recommendations from Step 16
- Limitations and confidence flags

**Example traceability matrix:**
| Requirement | UI evidence | API/code evidence | Test result | Status |
|---|---|---|---|---|
| User can register | Register page | POST /api/register | Pass | Verified |
| User can create task | Add Task form | POST /api/tasks | Pass | Verified |
| User can delete task | Not found | DELETE /api/tasks/:id | Untestable via UI | Partial |
| User can edit task | Edit button | PUT /api/tasks/:id | Partial fail | Partial |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Frontend | React + TypeScript + Vite + Tailwind CSS |
| Backend API | Python + FastAPI |
| Job storage | JSON files per job (SQLite/PostgreSQL later) |
| File parsing | Python zipfile, pathlib |
| Code parsing | Tree-sitter (Python bindings) |
| UI crawling | Playwright (Python) |
| LLM calls | Anthropic Python SDK — AsyncAnthropic, prompt caching |
| Test execution | Docker + Python subprocess |
| Reports | JSON + HTML |

---

## Build Status

| Milestone | Steps | Status |
|---|---|---|
| 1 — Scaffold + Upload + Step 0 | Steps −1, 0, upload endpoint, job store, frontend | ✓ DONE |
| 2 — Requirements Pipeline | Steps 1, 2, 3, 3.5 | Not started |
| 3 — Repo Parser | Step 4 | Not started |
| 4 — Inventory + Mapping + Completeness | Steps 5, 6, 7 | Not started |
| 5 — AC Generation + Test Execution | Steps 8, 9, 10, 11, 12 | Not started |
| 6 — Scoring + Dashboard | Steps 13, 14, 15, 16, 17 | Not started |
