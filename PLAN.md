# Software Quality Evaluator — Plan

## Overview

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM only explains results, never overrides them.

---

## Conceptual Model (4 Layers)

| Layer | Name | What it captures |
|---|---|---|
| L1a | **Explicit / Confirmed** | Requirements explicitly stated by the user (user stories, specs, README). Locked after Step 2.5. |
| L1b | **Implicit / Implied** | Functions commonly expected for this app type. Advisory only unless user confirms at Step 2.5. |
| L2 | **Exposed** | What the UI/API actually makes accessible to users |
| L3 | **Implemented** | What the code actually contains |
| L4 | **Verified** | What actually works end-to-end when executed |

**Terminology note:** L1a = Explicit = Confirmed = Obvious (User Stories are a subset). L1b = Implicit = Implied = Inferred. Extrinsic/Intrinsic are orthogonal axes — not synonyms for L1a/L1b.

---

## ISO Sub-Characteristic Formulas

### Functional Completeness — L1a vs (L2 ∪ L3)
"Are all explicitly required functions present and accessible?"

```
FC = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1a]
```

| E(L1x) | Condition |
|---|---|
| 1.0 | L1x ∈ L2 AND L1x ∈ L3 — accessible in UI/API and implemented in code |
| 0.5 | L1x ∈ L3 AND L1x ∉ L2 — implemented but not user-accessible |
| 0.4 | L1x ∈ L2 AND L1x ∉ L3 — UI visible but backend missing or broken |
| 0.25 | Partial or unclear evidence in either layer |
| 0.0 | L1x ∉ L2 AND L1x ∉ L3 — not found anywhere |

`L1Cx` = confidence weight assigned by user in Step 2.5 (default 1.0; high priority = 3, medium = 2, low = 1)

---

### Functional Appropriateness — L1b vs (L2 ∪ L3)
"Are commonly expected functions also present and accessible?"

Same formula shape as Completeness but scoped to x ∈ L1b:

```
FA = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1b]
```

**Biconditional (L1b ↔ (L2∪L3)):**
- L1b → (L2∪L3): scored above — "are implied functions present?" (necessary direction)
- (L2∪L3) → L1b: advisory only — "are there functions with no stated purpose?" (sufficient direction)

No (L2∪L3) → L1a advisory because explicit functions may be intentionally partial or in-progress.

FA is **advisory or low-weight** — more subjective than FC. Reported separately.

---

### Functional Correctness — L4 vs L1 ∩ (L2 ∪ L3)
"Do all implemented and accessible functions actually work end-to-end?"

```
S   = { x ∈ L1 | x ∈ (L2 ∪ L3) }     — eligible set (confirmed + present)
S*  = S \ { x | blocked }              — testable subset
FCo = ∑(T(L4x) × L4Cx) / ∑ L4Cx      [x ∈ S*]
L4Cx = L1Cx  (weight inherited from requirement)
```

| T(L4x) | Condition |
|---|---|
| 1.0 | E2E test passed — happy path + edge cases + persistence |
| 0.7 | Happy path only passed; edge case failed |
| 0.5 | API passed, UI failed (only if x ∈ L2; otherwise see below) |
| 0.2 | UI present, behaviour failed |
| 0.0 | Test failed completely |
| — | Blocked — exclude from both ∑T and ∑L4Cx |

T() conditioned on L2 membership:
- x ∈ L3 only (no UI): API pass → 1.0, API fail → 0.0
- x ∈ L2 only (no backend): full UI pass → 1.0, UI fail → 0.2

`CP = |blocked| / |L4|` — confidence penalty, reported separately alongside score.

---

## Final Scoring Model

```
Functional Suitability Score = 0.50 × Functional Completeness
                              + 0.50 × Functional Correctness

Functional Appropriateness = Advisory only (reported separately)
```

Completeness and Correctness are weighted equally because both are backed by hard, formula-derived evidence. Appropriateness is advisory because it depends on UX judgement and is harder to measure objectively.

---

## Pipeline Steps

| Step | Name | Layers | Role |
|---|---|---|---|
| -1 | User Input | — | User uploads `.zip` + requirements text |
| 0 | Project Type & Scope Classifier | L3 context | Determines project type and test strategy |
| 1 | Repo Parser | L2, L3 | Extracts code structure and surface-level UI/API |
| 2 | Explicit Requirement Extractor | L1a | Builds L1a from user input / README / specs |
| 2.5 | Human Requirement Confirmation | L1a | Validates and locks L1a before scoring |
| 3 | Acceptance Criteria Generator | L1a | Converts L1a into testable Given/When/Then criteria |
| 4 | UI/API Inventory Generator | L2 | Static parsing + Playwright dynamic crawl |
| 5 | AI-Implied Function Generator | L1b | Advisory list of commonly expected functions |
| 6 | Requirement-to-UI/API/Code Mapper | L1→L2,L3 | Traceability matrix |
| 7 | Functional Completeness Scorer | L1a vs (L2+L3) | Formula-based completeness score |
| 8 | Test Case Generator | L1a→L4 prep | Generates tests from acceptance criteria |
| 9 | Test Oracle Validator | L4 prep | Validates tests are strong enough |
| 10 | Test Execution Sandbox | L4 | Docker sandbox — produces raw pass/fail/blocked |
| 11 | Behaviour Evidence Collector | L4 | Screenshots, traces, logs, API responses |
| 12 | Functional Correctness Scorer | L4 vs L1∩(L2+L3) | Formula-based correctness score |
| 13 | Functional Appropriateness Analyser | L1b vs L2 | Advisory UI/UX analysis |
| 14 | Evidence Pack Builder | All | Aggregates all layer data |
| 15 | LLM ISO Evaluator | All | Explains scores; gives recommendations |
| — | Dashboard | All | Score + traceability + evidence + recommendations |

---

## Detailed Step Specifications

### Step 0: Project Type & Scope Classifier
**Status: COMPLETE**
**Tools:** Python, pathlib, LLM (Anthropic SDK, AsyncAnthropic, prompt caching)
**Logic:** Scans config files (package.json, requirements.txt, pyproject.toml, etc.), counts file extensions, sends file tree + config contents to LLM for classification.
**Output:** `step_0` in job JSON
```json
{
  "project_type": "full_stack_web_app",
  "frontend_framework": "React",
  "backend_framework": "FastAPI",
  "primary_language": "TypeScript",
  "confidence": "high",
  "reasoning": "...",
  "test_strategy": { "primary": "Playwright E2E", "secondary": "Pytest API tests" },
  "scan_summary": { "total_files": 42, "config_files_found": ["package.json", "requirements.txt"] }
}
```

### Step 1: Repo Parser
**Tools:** Python pathlib, Tree-sitter, json/yaml/toml
**Extracts:** README, frontend routes/pages, backend routes/endpoints, forms/buttons/components, API specs, package scripts, existing tests, config files, database models
**Ignores:** node_modules, .git, dist, build, .next, venv, __pycache__, coverage

### Step 2: Explicit Requirement Extractor
**Tools:** Python + LLM
**Rule:** Only extract stated requirements. No invented requirements. Every item must include its source quote.

### Step 2.5: Human Requirement Confirmation
**Tools:** React UI, FastAPI endpoint, async job queue
**This is the single biggest accuracy lever — locks L1a before any scoring begins.**
Pipeline pauses with status `waiting_for_confirmation`. Resumes when user submits confirmed list.
User can: confirm, edit, delete, reprioritise, adjust confidence weights.
AI-implied functions (L1b) shown separately — advisory only unless confirmed here.

### Step 3: Acceptance Criteria Generator
**Tools:** Python + LLM
Converts each L1a requirement into Given/When/Then criteria. Tests must target intended behaviour, not implementation details.

### Step 4: UI/API Inventory Generator
**Tools:** Tree-sitter (static), Playwright (dynamic)
- Static: routes, pages, buttons, forms, links, event handlers, API calls
- Dynamic: Playwright crawls running app — visible pages, clickable buttons, accessible forms, nav paths

### Step 5: AI-Implied Function Generator
**Tools:** Python + LLM
Advisory L1b list. Never scored unless user confirmed in Step 2.5.

### Step 6: Requirement-to-UI/API/Code Mapper
**Tools:** Tree-sitter, LLM, JSON traceability matrix (Neo4j later)
Maps each L1 requirement → UI element → API endpoint → backend function → database model → test case.

### Step 7: Functional Completeness Scorer
Formula-only. See formula section above. Output: completeness ratio + per-requirement breakdown.

### Step 8: UI-First Test Case Generator
**Tools:** LLM + Python
Tests generated from acceptance criteria (Step 3), not from code.

| Project type | Test type |
|---|---|
| React/Vue/Angular | Playwright (TypeScript) |
| Python backend/API | Pytest |
| Node/Express API | Jest / Supertest |
| Full-stack | Playwright E2E + API tests |
| CLI tool | Python subprocess tests |

### Step 9: Test Oracle Validator
**Tools:** Python (rule-based), LLM (semantic), Tree-sitter / regex
Rejects tests that: don't match the requirement, lack meaningful assertions, only check element existence, skip persistence/side effects.

### Step 10: Test Execution Sandbox
**Tools:** Docker, Python subprocess, Playwright, Pytest, Jest/Vitest
Docker boot sequence: detect package manager → install → start app → health-check → pass base URL to tests.

| Result | Meaning |
|---|---|
| Pass | Behaviour verified |
| Fail | Behaviour incorrect |
| Blocked | App could not run |
| Untestable | No accessible interface |
| Flaky | Inconsistent across runs |

Blocked ≠ Failed. Blocked lowers confidence but does not prove incorrect behaviour.

### Step 11: Behaviour Evidence Collector
Collects: screenshots, Playwright traces, console errors, network logs, API responses, DB state before/after, stack traces.

### Step 12: Functional Correctness Scorer
Formula-only. See formula section above. Output: correctness ratio + per-requirement breakdown + confidence penalty.

### Step 13: Functional Appropriateness Analyser
**Tools:** Python + Playwright trace data, LLM
Analyses: steps to complete core tasks, discoverability, label clarity, error message quality, workflow interruptions, feedback after actions.
Advisory output — not included in main score.

### Step 14: Evidence Pack Builder
Aggregates all step outputs into one structured JSON evidence package with full traceability.

### Step 15: LLM ISO Evaluator
**LLM does:** explain score, summarise evidence, identify gaps, give recommendations, state limitations.
**LLM does NOT:** override formula scores, invent features, treat L1b as confirmed, assume blocked = failed.

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
| 1 — Scaffold + Upload + Step 0 | Step 0, upload endpoint, job store, frontend | ✓ DONE |
| 2 — Repo Parser | Step 1 | Not started |
| 3 — Requirements Pipeline | Steps 2, 2.5, 3, 5 | Not started |
| 4 — Inventory + Mapping + Completeness | Steps 4, 6, 7 | Not started |
| 5 — Test Generation + Execution | Steps 8, 9, 10, 11 | Not started |
| 6 — Scoring + Dashboard | Steps 12, 13, 14, 15, Dashboard | Not started |
