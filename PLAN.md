# Functional Suitability Evaluator (ISO 25010) — Implementation Plan

## Overview

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM explains results, never overrides them.

---

## Conceptual Model (4 Layers)

| Layer | Name | What it captures |
|---|---|---|
| L1a | **Confirmed** | Requirements confirmed at review to be scored — scored under FCom. Origin can be stated, obvious, or implied |
| L1b | **Advisory** | Requirements confirmed at review to be advisory — scored under FA. Primarily implied items, but stated/obvious items can be demoted to here too |
| L2 | **Exposed** | What the UI/API actually makes accessible to users |
| L3 | **Implemented** | What the code actually contains |
| L4 | **Verified** | What actually works end-to-end when executed |

---

## ISO Sub-Characteristic Formulas

### Functional Completeness (FCom) — L1a vs (L2 ∪ L3)

```
FCom = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1a]
```

**E(L1x) is function-level** — aggregated from the path entities of function x:

```
E(L1x) = α × [∑ E(primary_i) / P] + (1−α) × [∑ E(secondary_j) / S]
```

where α = 0.7, P = count of primary entities, S = count of secondary entities. If S = 0, weight is 100% primary (α = 1.0).

Per-entity E() values:

| E(entity) | Condition |
|---|---|
| 1.0 | entity ∈ L2 AND entity ∈ L3 — accessible and implemented |
| 0.5 | entity ∈ L3 only — implemented but not UI-accessible |
| 0.4 | entity ∈ L2 only — UI visible, backend missing/broken |
| 0.25 | Partial or unclear evidence in either layer |
| 0.0 | Not found anywhere |

`L1Cx` = `weight` on each requirement. Derives from two separate sources depending on layer:

- **L1a (`confirmed_requirements`):** `priority` label → weight. critical=4.0, high=3.0, medium=2.0, low=1.0. User can override priority at Step 3.5; the locked weight is what FCom reads.
- **L1b (`advisory_requirements`):** `confidence_score` (Step 3 LLM, 0.0–1.0) → `strength` label → weight. The confidence_score drives two one-time decisions at Step 3 generation time: (1) placement — ≥0.80 → `"l1a"` candidate, <0.80 → `"l1b"`; (2) strength — 0.60–0.79 → `strongly_implied` (weight 3.0), 0.40–0.59 → `medium` (weight 2.0), <0.40 → `weak` (weight 1.0). After these decisions, `confidence_score` is not used in any formula — `weight` is.

**Both FCom and FA output 0–1.** Both are weighted averages (∑(E×w)/∑w) — dividing by ∑weight normalises to 0–1 regardless of the maximum weight value (4 for L1a, 3 for L1b). The max weight only controls how much a single requirement pulls the average relative to others. Step 17 multiplies the final Functional Suitability score by 5 for display → 0–5 scale.

State-variant nodes (labels with parentheticals like "(filtered)", "(sorted)", "(updated)") always have `primary: false` — Step 6 skips L2 route matching for them; they serve as Step 9 AC hints only.

### Functional Appropriateness (FA) — L1b vs (L2 ∪ L3)

**ISO 25010 clause 3.1.3:** *"A product provides the necessary and sufficient steps to complete a task, excluding any unnecessary steps."*

This grounds the biconditional:
- L1b → (L2∪L3): *necessary direction* — are implied functions present? → scored
- L2 → L1b: *sufficient/unnecessary direction* — are there user-facing functions with no stated purpose? → advisory only

The L2 → L1b direction (sufficient/unnecessary direction) is advisory only because "unnecessary steps" has complex relationships with intentional redundancy for UI intuitiveness and roadmap decisions. L3-only internal code is excluded from this check — only user-facing L2 endpoints/screens can constitute unnecessary steps.

```
FA = ∑(E(L1x) × L1Cx) / ∑ L1Cx      [x ∈ L1b]
```

`L1Cx` for L1b items = weight derived from LLM-assigned strength:

| Strength | L1Cx weight |
|---|---|
| strongly_implied | 3 |
| medium | 2 |
| weak | 1 |

FA is **advisory only**. The weighted formula means a missing `strongly_implied` function penalises FA more than a missing `weak` one — mirroring how L1a priority weights FCom.

### Functional Correctness (FCor) — L4 vs L1a ∩ L3

AC-level scoring. Each requirement has multiple acceptance criteria; sub-weights sum to L1Cx.

```
S   = { x ∈ L1a | x ∈ L3 }              — eligible set (backend implemented)
S*  = S \ { x | all ACs blocked }        — testable subset

FCor = ∑(pass_i × ACw_i) / ∑ ACw_i       [i ∈ ACs of requirements in S*]
CP  = ∑_blocked_L1Cx / ∑_all_L1Cx
```

**Why L3 only, not (L2 ∪ L3):** Requirements where E()=0.4 (UI stub, no backend) would trivially fail correctness tests — FCom already penalises them. Scoping to L3 avoids double punishment.

| E() | In S? | Test type |
|---|---|---|
| 1.0 (L2 ∧ L3) | Yes | E2E — Playwright + API |
| 0.5 (L3 only) | Yes | API only — no Playwright |
| 0.4 (L2 only) | No | Excluded — FCom already penalises |
| 0.25 / 0.0 | No | Excluded |

| pass_i | Condition |
|---|---|
| 1.0 | AC passed |
| passes/3 | Flaky — run 3×, score = fraction passed |
| 0.0 | AC failed |
| — | Fully blocked — excluded from S*, weight added to CP |

`CP` = confidence penalty, reported separately alongside FCor.

### Final Score

```
Functional Suitability = 0.50 × FCom + 0.50 × FCor
Functional Appropriateness = Advisory only (reported separately)
```

---

## Conceptual Distinctions — FCom, FA, FCor

**FCom vs FA:** If a function is absent, is the software *broken* (FCom gap) or just *worse* (FA gap)? FCom = coverage. FA = calibration (necessary and sufficient per ISO 3.1.3).

```
EXPLICIT          OBVIOUS          IMPLIED          UNRELATED
stated            so basic         would help       exists with
                  nobody           but absence      no objective
                  writes it        isn't broken     at all
     |________________|________________|________________|
     L1a              L1a              L1b              Unlinked
     <————————— FCom —————————><————————— FA ——————————————>
```

**FA has two failure modes; FCom has one:**
- FCom: missing expected function (app is incomplete)
- FA necessary: missing implied enabler (app is harder to use)
- FA sufficient: unnecessary function present (app has extra complexity)

**Step 3.5 exists** because the L1a/L1b boundary is a human judgment call — the user promotes L1b items they consider expected rather than merely helpful.

**Behavioral properties** (persistence, error messages, confirmation dialogs) are not functions — they belong as ACs at Step 8. They cannot be mapped to a UI element or endpoint in Step 6.

**Known gap — behavioral requirements** (auto-reset, scheduled notifications, cache expiry): these correctly fail Step 1's extraction gate. Schema fix (Step 1 `type: "behavioral"`, Step 6 L3-only E(), Step 8 time/state ACs) deferred to before Step 8.

**L1a validity:** Steps 1–3 produce heuristic starting points from project type + requirements text, not the codebase. The formula is only valid after Step 3.5 locks L1a. The `functional_area` tag helps reviewers spot fabricated requirement clusters.

**Cascade:** If a root requirement has E()=0, all dependents cascade to E≈0. Step 7 advisory groups E()=0 items by `functional_area` to surface the root cause.

---

## The Evaluation Space as a 2D Plane

Every requirement is a point on a 2D plane. All pipeline step prompts are written with this model as their grounding. Prompts in future steps should reference it.

### X axis — explicitness (and feature dependency depth)

```
stated       obvious       implied       unlinked
 (L1a)        (L1a)         (L1b)        (L2 only → FA sufficient)
   |____________|_____________|_____________|
   <—— FCom ——><——————————— FA ———————————————>
```

The X axis encodes distance from the software's core purpose — how clearly a function follows from what the software is meant to do, not whether it was written down. Stated functions define the purpose itself; obvious and implied ones build on or extend them. This determines cascade direction: a missing stated function zeros out all its dependents (obvious and implied).

- **Stated (roots):** Foundational capabilities that define the app's purpose. Auth, core data model, primary CRUD actions. All other features depend on these. Users write them down because they define what the app does.
- **Obvious (direct dependents):** Assumed by any user; never written down. Two sub-types: (1) *dependency connectors* — navigation and entry points that make stated requirements independently testable (obvious in execution order, but only exist because the stated function exists — cascade runs in the "reason to exist" direction, so stated → obvious); (2) *app-type usability* — navigation, affordances, and feedback functions any user expects regardless of what is stated (e.g. back navigation from sub-pages with no navbar, empty states on list views).
- **Implied (second-order dependents):** Enhancements built on top of the obvious layer — filtering, sorting, bulk operations. Would improve the app; absence isn't catastrophic if roots are solid.
- **Unlinked (orphaned):** User-facing screens accessible at L2 with no L1 requirement → FA sufficient advisory (unnecessary steps per ISO 3.1.3).

### Y axis — implementation depth (two distinct phases)

**Phase 1 — Presence** (FCom/FA, measured by E()): Does the function exist at any layer? Detection only — no app execution needed.

| E() | Condition |
|---|---|
| 1.0 | L2 (UI accessible) AND L3 (backend implemented) |
| 0.5 | L3 only — implemented but not UI-accessible |
| 0.4 | L2 only — UI visible, backend missing or broken |
| 0.25 | Partial / unclear evidence in either layer |
| 0.0 | Not found |

**Phase 2 — Correctness** (FCor): For requirements above the presence threshold (L3 exists), does the implementation behave correctly? Requires running the app and executing tests.

```
FCor high   All ACs pass — happy path and edge cases
FCor mid    Happy path passes, edge cases fail
FCor low    Present in L3 but fails most tests
```

FCom and FA operate entirely in Phase 1. FCor operates entirely in Phase 2. A requirement at E()=1.0 (FCom: fully wired) can still have FCor=0.1 (FCor: behaving incorrectly). The axes are orthogonal.

### Pipeline implications

| Concern | How the 2D plane shapes it |
|---|---|
| FCom scoring | Weighted average of E() across L1a — cascade-sensitive; one missing root can cascade to many zeros |
| FA scoring | Same formula applied to L1b; L1b dependents of missing L1a roots also approach zero |
| Step 3.5 human review | Root requirements (stated, many dependents) are highest priority to confirm or delete |
| Step 7 cascade advisory | Group E()=0 items by `functional_area`; identify cluster root as primary gap |
| Step 8 AC generation | ACs for dependent requirements should assert prerequisite is satisfied before testing the dependent |
| Test execution order (Step 11) | Test root requirements first; if root fails, mark dependents as cascade-blocked, not independent failures |

### Validity gate — requirements must be independently invokable capabilities

For a requirement to be valid at any X-axis position (stated, obvious, or implied), it must describe a capability a user can directly navigate to, interact with, or observe. It must have a dedicated home in the interface — its own page, form, button, or view.

**Behavioral reactions do not qualify.** A reaction describes what the system does when or if something else happens. Reactions have no dedicated home of their own — they are properties of existing capabilities. They belong as acceptance criteria at Step 8.

The linguistic signal for LLMs: "System must [do X] when/if [condition]" = reaction = AC. If the item cannot be phrased without a conditional, it is not a standalone capability.

| Capability (valid requirement) | Reaction (AC — not a requirement) |
|---|---|
| User can log out | Session is cleared when user logs out |
| User can view their task list | Task list shows a message when no tasks exist |
| User can navigate back to home | Page is inaccessible when user is not authenticated |
| User can add a task | Data is saved to database when form is submitted |

This gate applies equally to L1a and L1b. An implied enhancement that is only a behavioral constraint on an existing capability — not a new independently-navigable function — is an AC regardless of how useful it feels.

**E()=0.4 known gap:** E()=0.4 (UI visible, no backend) is excluded from FCor because correctness tests require a backend. Step 14 catches this experientially. Not numerically scored in FCor — a known model limitation.

---

## Pipeline Steps

### Data Flow DAG — Steps 0 → 3.5

```
 ┌────────────────────────────────────────────────────────────────────────────────────────────┐
 │                        User Input (zip archive + requirements text)                         │
 └────────────────────────┬──────────────────────────────────────────┬───────────────────────┘
                          │                                          │
           file tree / config files              README + spec docs (≤ depth 2) · requirements_text
                          │                                          │
                          ▼                                          ▼
 ┌──────────────────────────────────────┐    ┌────────────────────────────────────────────────┐
 │       STEP 0 · Classifier            │    │          STEP 1 · Req Extractor                │
 │  project_type, frameworks            │    │  REQ-xxx: stated functions + path[]            │
 │  discovered_pages, template_engine   │    │  project_summary                               │
 │  service_layout, test_strategy       │    │  vague, functional_area                        │
 └─────────────┬────────────────────────┘    └────────────────────────┬───────────────────────┘
               │                                                       │
       discovered_pages                              node inventory (from path[])
               │                                     stated functions · project_summary
               │                                                       │
               └────────────────────────┬──────────────────────────────┘
                                        ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────┐
 │                          STEP 2 · Obvious Generator                                         │
 │          OBV-xxx (navigation gaps — CHECK 2: missing entry · CHECK 3: missing exit)        │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                  REQ-xxx (1) · project_summary (1) · OBV-xxx · discovered_pages (0)
                                        │
                                        ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────┐
 │                          STEP 3 · Implied Generator                                         │
 │       GEN-xxx · Pass 1: SOP pattern table · Pass 2: INF domain inference                  │
 │       placement: l1a (conf ≥ 0.80) · l1b advisory (< 0.80) · unpacks (vague parents)      │
 └────────────────────────────────────────────────────────────────────────────────────────────┘

 project_context (0) ────────────────────────────────────────────────────────────────────►┐
 project_summary (1) ────────────────────────────────────────────────────────────────────►│
 REQ-xxx (1) · OBV-xxx (2) ──────────────────────────────────────────────────────────────►│
 GEN-xxx l1a / l1b (3) ──────────────────────────────────────────────────────────────────►│
                                                                                            ▼
                         ┌──────────────────────────────────────────────────────────────────┐
                         │                  STEP 3.5 · Confirmation Gate                     │
                         │  confirmed_requirements (L1a)   advisory_requirements (L1b)       │
                         │  project_context (Step 0 passthrough)   project_summary           │
                         └──────────────────────────────────────────────────────────────────┘
```

Steps 0 and 1 execute **in parallel** — both read directly from the uploaded zip with no dependency on each other. Step 2 waits for both. Step 3 waits for Step 2. Step 3.5 waits for human confirmation after Step 3. Step 1 reads from disk independently of Step 0. Step 0 bypasses Step 1 and feeds directly into Steps 2, 3, and 3.5. Step 3.5 is a full fan-in that reads all four prior step results simultaneously plus the HTTP body from the frontend.

---

### Data Flow DAG — Steps 3.5 → 7

```
                    ┌───────────────────────────────────────────────────────────────────────────────────────────┐
                    │                          STEP 3.5 · Confirmation Gate                                     │
                    └──────────────────────────────────────────────────────────────────────────────────┬────────┘
                                               │ project_context                                       │
                                               ▼                                                       │
                    ┌───────────────────────────────────────────────────────────────────────────────┐  │
                    │                            STEP 4 · Repo Parser                               │  │
                    └──────────────────────────────────────────────────────────────────┬────────────┘  │
                                               │ frontend_routes                       │               │
                                               ▼                                       │               │
 project_context (3.5) ──────────────►┌───────────────────────────────────────┐       │               │
                                       │          STEP 5 · App Crawler         │       │               │
                                       └───────────────────────────────────────┘       │               │
                                               │                    │                  │               │
                                            pages[]              pages[]               │               │
                                               │                    │                  │               │
                                               ▼                    ▼                  ▼               │
     confirmed_reqs (3.5) ──────────►┌─────────────────┐  ┌─────────────────────────────────────┐    │
  frontend_routes (4) ───────────────►│  STEP 6         │  │        STEP 7.5 · FA Advisor        │◄───┘ confirmed_reqs
  impl_units · route_elements (4) ───►│  E() Scorer     │  │                                     │      advisory_reqs
  navigation_graph (4) ──────────────►│                 │  │                                     │◄─── project_summary (3.5)
                                       └────────┬────────┘  └─────────────────────────────────────┘
                                                │                                                  ▲
                                                │ entity_scores[]                                  │
                                                │ unlinked_routes                      implementation_units, db_models,
                                                │ unlinked_endpoints                   frontend_routes, languages (4)
                                                │
     confirmed_reqs (3.5) ──────────────────►  │
     advisory_reqs (3.5) ───────────────────►  │
                                                ▼
                                       ┌─────────────────┐
                                       │  STEP 7          │
                                       │  FCom/FA Scorer  │
                                       └─────────────────┘
```

Steps 6 and 7.5 execute **in parallel** after Step 5 completes. Step 7.5 reads directly from Steps 3.5, 4, and 5 — it does **not** depend on Step 6 output. Step 7 waits only for Step 6.

---

### Step −1: User Input
- Uploaded codebase as a `.zip` file
- Requirements document or plain-text description (required — software with no requirements cannot be meaningfully evaluated)
- Software must be functionally purposeful — a skeleton or toy project will produce a low-signal score

---

### Step 0: Project Type & Scope Classifier
**Status: COMPLETE**
**Phase: FCom setup**
**Tools:** Python, pathlib, json/yaml/toml, LLM (AsyncAnthropic, prompt caching)

**Inputs:**
| Field | Source |
|---|---|
| `extract_to` (Path) | zip extracted by upload handler to `uploads/{job_id}/extracted/` |
| `client` (AsyncAnthropic) | FastAPI app state, injected at startup |

Step 0 reads the file tree and config file contents directly from disk — it does not receive any prior step result.

**Logic:** Rule-based first — scans config files (package.json, requirements.txt, pyproject.toml, etc.), counts file extensions. LLM only called when file inspection is inconclusive.

**Output — stored at `job["step_results"]["step_0"]`:**
```json
{
  "project_type": "full_stack_web_app",
  "frontend_framework": "React",
  "frontend_tooling": "Vite",
  "backend_framework": "Spring Boot",
  "template_engine": null,
  "service_layout": "separate_frontend_backend",
  "server_routes_detected": false,
  "confidence": "high",
  "reasoning": "...",
  "test_strategy": { "primary": "Playwright E2E", "secondary": "JUnit/MockMvc" },
  "config_files_found": ["frontend/package.json", "backend/pom.xml"],
  "llm_used": false,
  "llm_model": null,
  "discovered_pages": ["login.html", "register.html", "home.html"]
}
```

`discovered_pages` is populated by `_discover_pages()`: HTML files in `templates/`/`views/`; HTML at root/static dirs; `.tsx/.jsx/.vue/.svelte` in `pages/`/`screens/`; SSR template engine files (`.blade.php`, `.erb`, `.cshtml`, `.ejs`, etc. from `_TEMPLATE_ENGINE_EXTS`) in `views/`/`templates/`; Android `*Activity.java`/`*Activity.kt` files anywhere.

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `project_type`, `frontend_framework`, `backend_framework`, `discovered_pages` | Step 3 (project context in LLM prompt + root node detection) | 
| `discovered_pages` | Step 2 (node inventory + root detection) |
| `test_strategy` | Step 9 (test type selection — not yet built) |
| Full result → `step_3_5.project_context` passthrough | Steps 4, 5 (framework dispatch + bootstrap strategy) |

**Test strategy design:** For `backend_api_only`, `primary` is always the HTTP-level integration test tool — never a unit test runner. For `full_stack_web_app`, `primary` is Playwright E2E and `secondary` is the backend API test tool.

**Known limitation:** Next.js, SvelteKit, Nuxt standalone (no separate backend service) are classified as `frontend_only`. Full re-classification to `full_stack_web_app` deferred to after Step 4 repo parsing.

---

### Step 1: Stated Requirement Extractor
**Status: COMPLETE**
**Phase: FCom setup — builds L1a (stated)**
**Tools:** Python, LLM (AsyncAnthropic, prompt caching)

**Inputs:**
| Field | Source |
|---|---|
| `requirements_text` (str) | `job["requirements_text"]` — user's typed requirements from upload form |
| `extract_to` (Path) | `uploads/{job_id}/extracted/` — Step 1 reads README and spec docs directly from disk |
| `client` (AsyncAnthropic) | FastAPI app state |

Step 1 does NOT receive the Step 0 result. It reads the zip directory itself to find READMEs (depth ≤ 2) and spec docs (keyword-matched `.md/.rst/.txt`, MAX_DOCS=30, MAX_CHARS_PER_DOC=12000). Ignores tool config dirs (`.claude`, `.cursor`, `.github`, `.vscode`, `.idea`).

**PathEntity schema (used in all path arrays Steps 1–3.5):**
```
{ type: "node"|"element"|"edge", label: str, primary: bool, ui_node?: str, from?: str, to?: str }
```
`primary: true` = entity is scored by E() if absent. `primary: false` = context only, already asserted by another function.

**Output — stored at `job["step_results"]["step_1"]`:**
```json
{
  "project_summary": "2–3 sentence domain/purpose description of the app",
  "requirements": [
    {
      "req_id": "REQ-001",
      "description": "User can log in",
      "path": [
        {"type": "edge",    "label": "navigate to login",     "primary": true,  "from": null,        "to": "Login Page"},
        {"type": "node",    "label": "Login Page",             "primary": true},
        {"type": "element", "label": "email input",           "primary": true,  "ui_node": "Login Page"},
        {"type": "element", "label": "password input",        "primary": true,  "ui_node": "Login Page"},
        {"type": "element", "label": "login button",          "primary": true,  "ui_node": "Login Page"},
        {"type": "edge",    "label": "navigate to dashboard", "primary": true,  "from": "Login Page", "to": "Dashboard"}
      ],
      "vague": false,
      "source": "user_input",
      "source_quote": "users should be able to log in",
      "tag": "stated",
      "priority": "high",
      "weight": 3.0,
      "testable": true,
      "functional_area": "auth"
    }
  ],
  "total_count": 4,
  "docs_used": ["README.md", "docs/REQUIREMENTS.md"],
  "truncated_docs": ["docs/REQUIREMENTS.md"],
  "excluded_docs_count": 2,
  "llm_model": "claude-haiku-4-5-20251001",
  "dropped_count": 1,
  "error": null
}
```

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `requirements` (full array) | Step 2 as `step1_requirements` — descriptions, paths, req_ids, vague flags |
| `requirements` (full array) | Step 3 as `step1_requirements` — same |
| `project_summary` (str) | Step 3 as `project_summary` keyword arg |
| `requirements[].req_id`, `requirements[].path`, `requirements[].vague` | Step 3.5 confirmation UI (pre-populates L1a table) |
| `requirements` (after Step 3.5 confirmation) | Step 6 L1a → L2/L3 mapping |
| `requirements[].path[].primary` entities | Step 6 E() scoring per entity |
| `requirements` (after Step 3.5 confirmation) | Step 7 FCom formula (weights + E() scores) |
| `requirements` (after Step 3.5 confirmation) | Step 8 AC generation |

---

### Step 2: Obvious Requirement Generator
**Status: COMPLETE**
**Phase: FCom setup — builds L1a (obvious)**
**Tools:** Python, LLM (AsyncAnthropic)

**Inputs:**
| Field | Source |
|---|---|
| `step1_requirements` (list) | `job["step_results"]["step_1"]["requirements"]` — full requirement array |
| `step0_result` (dict) | `job["step_results"]["step_0"]` — uses `discovered_pages` only |
| `client` (AsyncAnthropic) | FastAPI app state |

Step 2 derives its working data from these inputs via helper functions:
- `_extract_nodes_from_paths(step1_requirements)` → node inventory (state-variant labels excluded)
- `_extract_edges_from_paths(step1_requirements)` → edge inventory for CHECK 2/3
- `_identify_root_node(step1_requirements, discovered_pages)` → root node (excluded from CHECK 2)

**3-check logic (graph connectivity gaps only):**
- Check 1 — Build node inventory from Step 1 path arrays (state-variant labels excluded); `discovered_pages` used separately for root node detection only
- Check 2 — For each non-root node: is there a stated inbound edge? If NO → generate entry navigation function
- Check 3 — For each node: is there a stated outbound edge? If NO → generate exit navigation function

**Output — stored at `job["step_results"]["step_2"]`:**
```json
{
  "requirements": [
    {
      "req_id": "OBV-001",
      "description": "User can navigate to Task List Page",
      "path": [
        {"type": "edge", "label": "navigation link", "primary": true, "from": null, "to": "Task List Page"},
        {"type": "node", "label": "Task List Page", "primary": false}
      ],
      "source": "obvious",
      "reasoning": "CHECK 2 — Task List Page has no stated inbound navigation",
      "tag": "obvious",
      "depends_on": ["REQ-003"],
      "priority": "high",
      "weight": 3.0,
      "testable": true,
      "functional_area": "navigation"
    }
  ],
  "total_count": 3,
  "llm_model": "claude-haiku-4-5-20251001",
  "dropped_count": 0
}
```

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `requirements` (full array) | Step 3 as `step2_requirements` — descriptions for dedup only |
| `requirements` | Step 3.5 confirmation UI (pre-populates L1a table, non-demotable) |
| `requirements` (after Step 3.5 confirmation) | Step 6 L1a → L2/L3 mapping (same as Step 1 requirements) |
| `requirements` (after Step 3.5 confirmation) | Step 7 FCom formula |
| `requirements` (after Step 3.5 confirmation) | Step 8 AC generation |


---

### Step 3: L1b Implied Enhancement Generator
**Status: COMPLETE**
**Phase: FCom setup — builds L1b (and L1a candidates)**
**Tools:** Python, LLM (AsyncAnthropic)

**Inputs:**
| Field | Source |
|---|---|
| `step1_requirements` (list) | `job["step_results"]["step_1"]["requirements"]` — full array with descriptions, paths, vague flags, req_ids |
| `step2_requirements` (list) | `job["step_results"]["step_2"]["requirements"]` — descriptions used for dedup only |
| `step0_result` (dict) | `job["step_results"]["step_0"]` — uses `project_type`, `frontend_framework`, `backend_framework`, `discovered_pages` |
| `project_summary` (str) | `job["step_results"]["step_1"]["project_summary"]` — passed as keyword arg |
| `client` (AsyncAnthropic) | FastAPI app state |

Step 3 user message is built from:
- `project_type`, `frontend_framework`, `backend_framework`, `discovered_pages` (project context + root node detection via `_identify_root_node`)
- `project_summary` (INF grounding)
- Step 1 requirement descriptions + vague flags (SOP node inventory via `_extract_nodes_from_paths`; Step 1 `req_ids` used to validate both `depends_on` and `unpacks` — OBV-XXX IDs from Step 2 are never valid `depends_on` targets; a generated enhancement depends on a domain feature, not a navigation gap)
- Step 2 requirement descriptions (dedup only)

**Two-pass generation:**

**Pass 1 — SOP pattern-triggered (category: "sop")**
Fires on nodes from Step 1 path arrays. Pattern table:
- List node → filter (~0.82), search (~0.80), sort (~0.68), edit item (~0.85), delete item (~0.82)
- Detail node → edit (~0.85), delete (~0.82)
- CRUD COMPLETION RULE: when CREATE is stated for an entity, edit and delete always L1a (≥0.85 / ≥0.82)
- Auth present → account management / profile page (~0.87)
- Named changeable status → cross-status overview (~0.75), filter-by-status (~0.82)
- Temporal field → time-scoped view (~0.75), overdue alert (~0.72)
- Mutable records (edit/update stated) → audit / history (~0.60)
- User-configurable preferences → settings page (~0.82)
- Time-sensitive deadlines → notification surface (~0.65)
- Multi-user data → user profile (~0.82)

**Pass 2 — INF domain inference (category: "inf")**
Grounding step first (understand app purpose/structure), then generates across 7 angles:
1. RECURRING USE, 2. WORKFLOW COMPLETENESS, 3. DATA MANAGEMENT, 4. DOMAIN STANDARDS (exhaustive), 5. DISCOVERABILITY + HELP, 6. USER CONTROL, 7. OVERVIEW + INSIGHT

**Confidence → placement:**
- ≥ 0.80 → `placement: "l1a"`, strength: null
- 0.60–0.79 → `placement: "l1b"`, strength: `strongly_implied`, weight: 3.0
- 0.40–0.59 → `placement: "l1b"`, strength: `medium`, weight: 2.0
- < 0.40 → `placement: "l1b"`, strength: `weak`, weight: 1.0

**Output — stored at `job["step_results"]["step_3"]`:**
```json
{
  "requirements": [
    {
      "req_id": "GEN-001",
      "description": "User can view account information",
      "path": [
        {"type": "edge",    "label": "navigate to account",  "primary": true,  "from": "Dashboard",    "to": "Account Page"},
        {"type": "node",    "label": "Account Page",          "primary": true},
        {"type": "element", "label": "profile information",  "primary": true,  "ui_node": "Account Page"},
        {"type": "element", "label": "change password form", "primary": true,  "ui_node": "Account Page"},
        {"type": "edge",    "label": "return to dashboard",  "primary": false, "from": "Account Page", "to": "Dashboard"}
      ],
      "source": "generated",
      "tag": "generated",
      "category": "sop",
      "reasoning": "Auth pattern — login stated (REQ-001); no account management page in stated or obvious reqs",
      "unpacks": null,
      "depends_on": ["REQ-001"],
      "confidence_score": 0.88,
      "confidence_reason": "Login stated; account management is a standard paired function in authenticated apps",
      "placement": "l1a",
      "priority": "high",
      "strength": null,
      "weight": 3.0,
      "testable": true,
      "functional_area": "auth"
    }
  ],
  "total_count": 12,
  "sop_count": 5,
  "inference_count": 7,
  "llm_model": "claude-haiku-4-5-20251001",
  "dropped_count": 2,
  "error": null
}
```

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `requirements` where `placement == "l1a"` | Step 3.5 UI — pre-included in L1a section, demotable |
| `requirements` where `placement == "l1b"` AND `unpacks` targets a vague Step 1 parent | Step 3.5 UI — promoted to L1a section alongside l1a items, tagged "vague child", demotable |
| `requirements` where `placement == "l1b"` AND no vague `unpacks` | Step 3.5 UI — shown in Advisory section, promotable |
| `requirements[].unpacks` | Step 3.5 — vague parent auto-replace logic |
| `requirements` where `placement == "l1a"` | Step 3.5 confirm endpoint — merged into `confirmed_requirements` |
| `requirements` where `placement == "l1b"` | Step 3.5 confirm endpoint — copied as `advisory_requirements` |
| All downstream (Steps 6, 7, 8, 9, 13) read via `step_3_5` only — not from Step 3 directly |

---

### Step 3.5: Human Requirement Confirmation + Data Consolidation
**Status: COMPLETE**
**Phase: FCom setup — locks L1a and produces single milestone-1 output for all downstream steps**
**Tools:** React UI (`ConfirmationTable.tsx`), FastAPI `POST /jobs/{job_id}/confirm`

**Inputs — read from job JSON by the confirm endpoint:**
| Field | Source |
|---|---|
| `step_results.step_0` | `project_context` passthrough — architectural metadata for Steps 4, 5, 9, 11 |
| `step_results.step_1.requirements` | `step1_ids` for `deleted_count`; `depends_on` + `source_quote` looked up server-side by `req_id` |
| `step_results.step_1.project_summary` | copied to output for Steps 8, 16 |
| `step_results.step_2.requirements` | `step2_ids` for `deleted_count`; `depends_on` looked up server-side |
| `step_results.step_3.requirements` | L1b items (`placement == "l1b"`) copied as `advisory_requirements` |
| HTTP body `requirements` (list of `ConfirmedRequirement`) | user's finalised L1a list, submitted from the frontend |
| HTTP body `skipped` (bool) | true if user clicked Skip instead of Confirm |

**`ConfirmedRequirement` schema (Pydantic):**
```
req_id, description, path: list[PathEntity], vague: bool, tag, priority, weight,
functional_area, testable, source, promoted: bool, unpacks: str|null,
depends_on: list[str], source_quote: str|null
```
`depends_on` and `source_quote` are looked up server-side from prior step results by `req_id` — the frontend does not pass them.

**Output — stored at `job["step_results"]["step_3_5"]`; status → `"confirmed"`, `current_step` → 4:**
```json
{
  "confirmed_requirements": [
    {
      "req_id": "REQ-001",
      "description": "User can log in",
      "path": [...],
      "vague": false,
      "tag": "stated",
      "priority": "high",
      "weight": 3.0,
      "functional_area": "auth",
      "testable": true,
      "source": "stated",
      "promoted": false,
      "unpacks": null,
      "depends_on": [],
      "source_quote": "users should be able to log in"
    },
    {
      "req_id": "OBV-001",
      "description": "User can navigate to Dashboard",
      "path": [...],
      "vague": false,
      "tag": "obvious",
      "priority": "high",
      "weight": 3.0,
      "functional_area": "navigation",
      "testable": true,
      "source": "obvious",
      "promoted": false,
      "unpacks": null,
      "depends_on": ["REQ-003"],
      "source_quote": null
    }
  ],
  "advisory_requirements": [
    {
      "req_id": "GEN-008",
      "description": "User can filter tasks by status",
      "path": [...],
      "placement": "l1b",
      "strength": "strongly_implied",
      "weight": 3.0,
      "confidence_score": 0.75,
      "category": "sop",
      "reasoning": "Status field stated — filter-by-status is standard paired function",
      "confidence_reason": "Named status field exists in stated requirements",
      "depends_on": ["REQ-003"],
      "functional_area": "task_management",
      "testable": true
    }
  ],
  "project_context": {
    "project_type": "full_stack_web_app",
    "frontend_framework": "React",
    "frontend_tooling": "Vite",
    "backend_framework": "Spring Boot",
    "template_engine": null,
    "service_layout": "separate_frontend_backend",
    "server_routes_detected": false,
    "discovered_pages": ["login.html", "dashboard.html"],
    "test_strategy": {"primary": "Playwright E2E", "secondary": "JUnit/MockMvc"},
    "runtime": null
  },
  "project_summary": "A team task management application...",
  "confirmed_at": "2025-05-20T10:00:00Z",
  "skipped": false,
  "l1a_count": 12,
  "promoted_count": 1,
  "deleted_count": 2,
  "added_count": 0
}
```

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `confirmed_requirements` (full array incl. `path[]`) | **Steps 6, 7, 8, 9, 13** — authoritative L1a; `path[].primary` entities scored by E() in Step 6 |
| `confirmed_requirements[].weight` | **Step 7** — FCom formula (`∑ L1Cx`) |
| `advisory_requirements` (full array incl. `path[]`) | **Steps 6, 7** — FA scoring (L1b); `weight` used as `L1Cx` |
| `project_context` | **Steps 4, 5** — repo parsing strategy + crawl mode; **Steps 9, 11** — test tool selection |
| `project_summary` | **Steps 8, 16** — AC generation context; LLM ISO evaluator |

**Steps 0–3 outputs are fully subsumed** by `step_3_5` for all downstream purposes. Steps 4+ read only `step_3_5` for all milestone-1 data. Steps 0–3 individual results remain in job JSON as internal pipeline state (Steps 15–16 may read them for reporting).

**Fields dropped at Step 3.5:**

*Step 0 → `project_context`:* `confidence`, `reasoning`, `config_files_found`, `llm_used`, `llm_model`

*Step 1 envelope:* `total_count`, `docs_used`, `truncated_docs`, `excluded_docs_count`, `llm_model`, `dropped_count`, `error` — per-requirement fields: none dropped.

*Step 2 envelope:* `total_count`, `llm_model`, `dropped_count` — per-requirement: `reasoning` (CHECK 2/3 text, UI display only).

*Step 3 envelope:* `total_count`, `sop_count`, `inference_count`, `llm_model`, `dropped_count`, `error` — promoted l1a items: `category`, `reasoning`, `confidence_score`, `confidence_reason`, `placement`, `strength` — l1b advisory items: no fields dropped, copied as-is with full schema.

**If skipped:** `confirmed_requirements` = all Step 1 stated (non-vague) + all Step 2 obvious at default weights; `advisory_requirements` = all Step 3 l1b items; `project_context` and `project_summary` still populated. The skip logic is frontend-driven — ConfirmationTable pre-populates the HTTP body with only stated+obvious items; the backend stores `skipped: true` but applies no special branching.

---


Exact fields per edge:
- **Disk → Step 0:** file tree, config file contents (package.json, pom.xml, build.gradle, etc.)
- **Disk + job → Step 1:** README files (depth ≤ 2), keyword-matched spec docs (.md/.rst/.txt), `job["requirements_text"]`
- **Step 0 → Step 2:** `discovered_pages` only — passed to `_identify_root_node()` for root exclusion; also shown to LLM as page-file context (node inventory itself comes from Step 1 path arrays via `_extract_nodes_from_paths`)
- **Step 1 → Step 2:** `requirements[]` full array — descriptions, paths, req_ids, vague flags
- **Step 0 → Step 3:** `project_type`, `frontend_framework`, `backend_framework`, `discovered_pages` — project context for LLM prompt and `_identify_root_node()`
- **Step 1 → Step 3:** `requirements[]` full array — SOP node extraction, vague detection, `depends_on`/`unpacks` validation; `project_summary` — INF pass domain grounding
- **Step 2 → Step 3:** `requirements[]` descriptions only — dedup check (LLM shown as "already covered"; `_validate_and_normalise` semantic dedup)
- **Step 0 → Step 3.5:** 10 fields → `project_context`: `project_type`, `frontend_framework`, `frontend_tooling`, `backend_framework`, `template_engine`, `service_layout`, `server_routes_detected`, `discovered_pages`, `test_strategy`, `runtime`
- **Step 1 → Step 3.5:** `requirements[]` as req_id lookup for server-side `depends_on` + `source_quote` enrichment; `step1_ids` set for `deleted_count`; `project_summary` copied to output
- **Step 2 → Step 3.5:** `requirements[]` as req_id lookup for `depends_on` enrichment; `step2_ids` set for `deleted_count`
- **Step 3 → Step 3.5:** all items where `placement == "l1b"` → `advisory_requirements`; req_id lookup for `depends_on` enrichment
- **HTTP body → Step 3.5:** `requirements: list[ConfirmedRequirement]` (user's finalised L1a list); `skipped: bool`

---

### Step 4: Repo Parser — L3 Inventory
**Status: COMPLETE**
**Phase: FCom — builds L3 inventory**
**Tools:** Python (zipfile, pathlib), Tree-sitter (0.25 QueryCursor API), regex
**Input:** `step_3_5.project_context` — `backend_framework` + `frontend_framework` determine which extraction strategies to run.
**Ignores:** node_modules, .git, dist, build, .next, venv, __pycache__, coverage, target, .gradle, examples, demo, sample

**What Step 4 is building and why:**
Step 4 is the static code analysis pass. It reads the codebase without executing it and builds the complete L3 inventory — what is *implemented* in the source. This feeds Step 6's E() scoring via the exhaustive completeness model:

| Entity type | L3 check (Step 4) | L2 check (Step 5) |
|---|---|---|
| `node` | Route in `frontend_routes` | Page accessible via Playwright |
| `element` | Element in `route_elements` (parsed from source) | Element rendered in DOM |
| `navigation edge` | Nav trigger in `navigation_graph` (Link/anchor in source) | Nav trigger rendered in DOM |
| `data edge` | Backend handler in `implementation_units` | Trigger element rendered in DOM |
| `structural edge` | Trigger element in `route_elements` (same L3 source as `element` entities) | Trigger element rendered in DOM |

Linkage (is the trigger element wired to that endpoint?) → FCor (Step 11), not FCom.

**Extracted domains — purpose and layer:**

| Domain | Layer | Purpose in scoring |
|---|---|---|
| `frontend_routes` | L3 → L2 seed | **Node entity L3 check.** If a route isn't here, node E() ≤ 0.5. Also the Playwright crawl seed list for Step 5. Each entry is `{path, dynamic, params[]}`. |
| `route_elements` | L3 (element signal) | **Element entity L3 check.** Per-route inventory of interactive elements (`{type, subtype, label}`) parsed from source files. Step 6 uses this for E()=0.5 when Playwright couldn't reach a page. |
| `navigation_graph` | L3 (navigation signal) | **Navigation edge L3 check.** Per-route list of target routes found in navigation triggers (`<Link to>`, `<a href>`, `navigate()`, `router.push()`). Step 6 checks this to score whether a navigation trigger exists in source. |
| `implementation_units` | L3 (action signal) | **Data edge L3 check.** Backend handler existence — `kind: "api_endpoint"` for REST handlers, `kind: "form_handler"` for SSR HTML forms. Covers both REST APIs and traditional form-submission apps. |
| `route_to_files` | Infrastructure | Route → source file(s) mapping. Used internally by Step 4 to determine which files to parse for `route_elements` and `navigation_graph`. Each route's list includes 1-level-deep local imports so child components are included. |
| `important_files` | Infrastructure | Wider file inventory (capped at 100) for Step 7.5 advisor context and evidence pack. |
| `database_models` | Context | Step 7.5 FA advisor (codebase-grounded suggestions). Step 15/16 evidence pack. |
| `existing_tests` | Context | Step 15 test coverage report; Step 9 scaffolding decisions. |
| `languages` | Context | Reporting and Steps 15/16 evidence pack only. |

**Extraction strategies:**
- **Frontend routes + file mapping (single pass):** `_build_route_to_files` discovers routes AND maps them to files. Priority: Next.js pages/ → Next.js app/ → SvelteKit → React Router JSX + createBrowserRouter → Vue/Angular Router → SSR endpoint fallback → static HTML. Route strings enriched as `{path, dynamic, params[]}` via `_route_entry()`. 1-level-deep shallow import expansion on all mapped files.
- **API endpoints:** dispatched on `backend_framework` — Flask/FastAPI (tree-sitter Python), Django (regex on urls.py), Spring Boot (tree-sitter Java two-level: class `@RequestMapping` + method mappings; Kotlin regex fallback), Express/NestJS (regex on .js/.ts)
- **implementation_units:** wraps all `api_endpoints` as `kind: "api_endpoint"` + HTML `<form method="POST/PUT/DELETE">` in SSR templates as `kind: "form_handler"`.
- **route_elements:** for each route's file list from `route_to_files`, parse source for `<input>`, `<button>`, `<textarea>`, `<select>` via regex. Returns `{type, subtype, label}` — no runtime fields. Comment stripping applied first.
- **navigation_graph:** for each route's file list, scan for static string paths in `to=`, `href=`, `routerLink=`, `navigate()`, `router.push()`, `history.push()` — skips template literals and variables. Returns `{route: [target_routes]}`.
- **Database models:** SQLAlchemy/Django ORM (Python class regex), JPA `@Entity` (Java), TypeORM `@Entity()` (TS), Mongoose `new Schema(...)`, Prisma `.prisma` model blocks.
- **Test files / Important files / Languages:** glob patterns + extension counts.

**Output — stored at `job["step_results"]["step_4"]`:**
```json
{
  "frontend_routes": [
    { "path": "/", "dynamic": false, "params": [] },
    { "path": "/dashboard", "dynamic": false, "params": [] },
    { "path": "/login", "dynamic": false, "params": [] },
    { "path": "/users/:id", "dynamic": true, "params": ["id"] }
  ],
  "implementation_units": [
    { "kind": "api_endpoint", "method": "POST", "path": "/api/auth/login", "file": "src/main/java/.../AuthController.java", "handler": "login" },
    { "kind": "api_endpoint", "method": "GET",  "path": "/api/users/{id}", "file": "src/main/java/.../UserController.java", "handler": "getUser" }
  ],
  "route_elements": {
    "/login": [
      { "type": "input", "subtype": "email", "label": "Email address" },
      { "type": "input", "subtype": "password", "label": "Password" },
      { "type": "button", "subtype": "submit", "label": "Log in" }
    ]
  },
  "navigation_graph": {
    "/": ["/dashboard", "/login"],
    "/login": ["/", "/dashboard"],
    "/dashboard": ["/", "/users/:id"]
  },
  "route_to_files": {
    "/": ["src/pages/Home.tsx"],
    "/dashboard": ["src/pages/Dashboard.tsx"],
    "/login": ["src/pages/Login.tsx", "src/components/LoginForm.tsx"],
    "/users/:id": ["src/pages/UserDetail.tsx"]
  },
  "important_files": ["src/pages/Login.tsx", "src/main/java/.../AuthController.java", "src/services/api.ts"],
  "database_models": ["User", "Task"],
  "existing_tests": ["src/test/java/.../AuthControllerTest.java"],
  "languages": ["Java", "TypeScript"],
  "total_endpoints": 8,
  "total_routes": 4,
  "error": null
}
```
*L3 scoring inputs: `frontend_routes` (node), `route_elements` (element), `navigation_graph` (navigation edge), `implementation_units` (data edge). Infrastructure: `route_to_files`, `important_files`. Context: `database_models`, `existing_tests`, `languages`.*

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `frontend_routes` | Step 5 — Playwright crawl seed list; Step 6 — node entity L3 check |
| `route_elements` | Step 6 — element entity L3 check (E()=0.5 for routes Playwright couldn't reach) |
| `navigation_graph` | Step 6 — navigation edge L3 check (does a nav trigger exist in source?) |
| `implementation_units` | Step 6 — data edge L3 check; unlinked L3 detection: `[u for u in implementation_units if u["kind"] == "api_endpoint"]` |
| `route_to_files` | Internal to Step 4 (source for route_elements + navigation_graph); retained for downstream reference |
| `important_files` | Step 7.5 — FA advisor context; Steps 15/16 — evidence pack |
| `database_models` | Step 7.5 — FA advisor; Steps 15/16 — evidence pack |
| `languages`, `existing_tests` | Steps 15/16 — evidence pack |

---

### Step 5: App Crawler — L2 Element Inventory
**Phase: FCom — builds L2 element inventory**
**Tools:** Playwright, Python
**Input:**
- `step_3_5.project_context` (`project_type`, `frontend_framework`, `backend_framework`, `service_layout`, `frontend_tooling`, `test_strategy`) — bootstrap strategy + crawl mode
- Step 4 result: `frontend_routes` (crawl seed list)

**What Step 5 is building and why:**
Step 5 is the runtime observation pass. It boots the actual app and records what a user can see and interact with — the L2 inventory. L3 (Step 4) tells you what the code declares; L2 (Step 5) tells you what actually renders. The distinction matters: an element can exist in L3 source but be conditionally hidden at runtime, or be accessible in L2 but have no backend handler (E()=0.4). Step 4 owns all L3 evidence including source-level element extraction (`route_elements`) and navigation trigger parsing (`navigation_graph`). Step 5 is purely L2 — Playwright only.

**Extracted domains — purpose and layer:**

| Domain | Layer | Purpose in scoring |
|---|---|---|
| `pages[].route` + `accessible` | L2 (node signal) | **Node entity L2 check.** `accessible: true` → node E()=1.0 (L2 ∧ L3). Route in `unvisitable_routes` → Step 6 falls back to Step 4 `route_elements` → E()=0.5. |
| `pages[].elements` | L2 (element + nav signal) | **Element and navigation edge L2 check.** Interactive widgets (inputs, buttons, selects, links) found on each page at runtime. `discovered_by: "playwright"` → E()=1.0. For unvisitable routes, Step 6 uses Step 4 `route_elements` → E()=0.5. |
| `pages[].outbound_links` | Context | Supplementary; not used in E() scoring. Step 15 reporting only. |
| `pages[].api_calls_observed` | Context | Passive page-load GETs only — POST/PUT/DELETE never observed. Cross-check against Step 4 endpoints in Step 15 evidence pack. Not used for E() scoring. |
| `unvisitable_routes` | Scoring signal | Tells Step 6 which routes Playwright couldn't reach. Step 6 treats those routes as L3-only (E()=0.5) using Step 4 `route_elements`. |

**Why no LLM here:**
Step 5 is pure extraction — no judgment. Step 6 does the matching of L1a path entities against the inventory using LLM fuzzy matching.


**App bootstrap (heuristic from `project_context`):**
- `static_site` → `python -m http.server` on port 8082
- `mobile_app` → no bootstrap; all routes returned as static fallback immediately
- `frontend_only` → `npm run dev` (Vite→5174, Next.js→3000, SvelteKit→5174) or `npm start` (CRA/Webpack→3000)
- `backend_api_only` → FastAPI: `uvicorn` on 8001; Flask: `flask run` on 5001; Django: `manage.py runserver` on 8001; Express/NestJS: `npm start` on 3001; Spring Boot: `mvnw spring-boot:run` on 8001 (searches up to 2 levels deep for `mvnw`/`mvnw.cmd`)
- `full_stack_web_app` + `separate_frontend_backend` → find frontend subdirectory, start with npm (same ports as `frontend_only`)
- `full_stack_web_app` (SSR) → start backend per above; if not found, try npm frontend fallback
- Health check: poll port every 1.5s, 30s timeout; crawl begins once port responds
- Boot failure → all routes returned as `unvisitable_routes` with `reason: "boot_failed"`; Step 6 uses Step 4 `route_elements` for all
- Job status: `step_4_complete` → `step_5_running` → `step_5_complete` (or `step_5_error`)

**Playwright crawl:**
Boot the app. Visit each route from Step 4 `frontend_routes`. For each page, record:
- Page title (`document.title`)
- All interactive elements with non-empty labels: inputs, buttons, selects, textareas, links (`a[href]`). Label priority: `aria-label` → `placeholder` → `textContent` (skipped for input/select) → `title` → `name`. Elements without a resolvable label are dropped. `visible` flag records DOM visibility but non-visible elements are not filtered out.
- CSS selectors from running DOM
- Outbound navigation links
- Network requests during page load (XHR/fetch, passive — `api_calls_observed`)
- Accessibility: `accessible: true/false` (final URL matches requested route)

Routes Playwright cannot visit (auth-gated, 404, timeout) → `unvisitable_routes` + shell page with `elements: []`. Step 6 fills element evidence from Step 4 `route_elements`.

**Output — stored at `job["step_results"]["step_5"]`:**
```json
{
  "pages": [
    {
      "route": "/",
      "title": "Home",
      "discovered_by": "playwright",
      "accessible": true,
      "elements": [
        { "type": "a", "subtype": "link", "label": "Login", "selector": "a[href='/login']", "visible": true }
      ],
      "outbound_links": ["/login"],
      "api_calls_observed": []
    },
    {
      "route": "/login",
      "title": "Login",
      "discovered_by": "playwright",
      "accessible": true,
      "elements": [
        { "type": "input",  "subtype": "email",    "label": "Email address", "selector": "input[type='email']",    "visible": true },
        { "type": "input",  "subtype": "password", "label": "Password",      "selector": "input[type='password']", "visible": true },
        { "type": "button", "subtype": "submit",   "label": "Log in",        "selector": "button[type='submit']",  "visible": true }
      ],
      "outbound_links": ["/register", "/forgot-password"],
      "api_calls_observed": ["GET /api/auth/session"]
    },
    {
      "route": "/dashboard",
      "title": null,
      "discovered_by": "static_fallback",
      "accessible": null,
      "elements": [],
      "outbound_links": [],
      "api_calls_observed": []
    },
    {
      "route": "/users/:id",
      "title": null,
      "discovered_by": "static_fallback",
      "accessible": null,
      "elements": [],
      "outbound_links": [],
      "api_calls_observed": []
    }
  ],
  "unvisitable_routes": [
    { "route": "/dashboard", "reason": "auth_required" },
    { "route": "/users/:id", "reason": "auth_required" }
  ],
  "total_pages": 4,
  "error": null
}
```
*`discovered_by: "static_fallback"` means Playwright could not reach the route — `elements` is empty. Step 6 uses Step 4 `route_elements` for those routes (E()=0.5).*

**Key value:**
- Playwright gives ground-truth of what is rendered at runtime — conditional rendering, dynamic state, hidden elements are all correctly captured.
- CSS selectors come from running DOM (stable), not source code (unstable due to CSS-in-JS).
- `api_calls_observed` cross-checks Step 4's static endpoint list (supplementary — not used for E() scoring).

---

### Step 6: Requirement → L2/L3 Entity Mapper — **COMPLETE**
**Phase: FCom — computes E() per requirement**
**Tools:** Python, LLM (AsyncAnthropic — entity label matching)
**Input:**
- `step_3_5.confirmed_requirements` (L1a, each with `path: PathEntity[]`)
- `step_3_5.advisory_requirements` (L1b, each with `path: PathEntity[]`)
- Step 5 result: per-page element inventory (`pages[]`, `unvisitable_routes[]`)
- Step 4 result: `implementation_units` (data edge L3 matching — covers REST endpoints + SSR form handlers; unlinked L3 detection uses `[u for u in implementation_units if u["kind"] == "api_endpoint"]`), `frontend_routes`, `route_elements` (element L3 fallback for unvisitable routes), `navigation_graph` (navigation edge L3 fallback)

**FCom vs FCor boundary — data edge entities:**
Data edge `presence` (does the endpoint exist in `implementation_units`? does the triggering element exist in the DOM?) is scored here as FCom. Data edge `linkage` (is the triggering element actually wired to call that endpoint?) is FCor, scored only in Step 11 via E2E test execution. Step 6 never checks linkage — the E() piecewise below tests existence only.

---

**Matching approach — function-level grounding (Step 6a → 6b):**

Matching is done at function level, not entity level. Comparing each entity label in isolation against the full inventory fails because: (1) vocabulary gap between requirement language and DOM/source vocabulary is large; (2) the same label ("email field") appears on multiple pages, giving no basis for disambiguation without context.

**Step 6a — Grounding:** One LLM call per function. The LLM receives the full requirement description, all path entities in order, and the positive inventory scoped to the function's page. Route scoping is the critical step: `node` entities in the path resolve which route the function is about, then element and edge matching is restricted to that route's inventory (typically 5–15 elements instead of 500+ across the whole app). With a small, scoped candidate set and the function's intent as context, the LLM resolves all entities simultaneously — cross-entity consistency is enforced within the call.

Each entity resolves to a concrete inventory pointer:
- Node → `matched_route` (e.g. `"Login Page"` → `"/login"`)
- Element → `matched_selector` + `match_source: "playwright"|"route_elements"` (e.g. `"email input"` → `"input[type=email]"`)
- Navigation edge → `matched_nav_target` + `match_source: "playwright_element"|"navigation_graph"` (e.g. `"go to dashboard"` → `"/dashboard"`)
- Data edge → `matched_endpoint` + `trigger_selector` (e.g. `"add to cart"` → `"POST /api/cart"`)
- Structural edge → `triggering_element_found: true|false` + `match_source`

Output stored in job JSON as `step_6_grounding` — inspectable and correctable before scoring runs.

**Step 6b — Scoring:** Reads pre-resolved pointers from 6a and applies the piecewise E() tables deterministically. No fuzzy matching in the scoring pass.

**Edge classification — keyword table:**

Classify each `edge` entity by scanning `entity.label` (case-insensitive, word-boundary match):

| Category | Keywords | Scoring mechanism |
|---|---|---|
| **data** (HTTP mutation) | submit, add, create, delete, remove, update, save, mark, complete, pause, resume, sync, upload, download, move, configure, change, reset, toggle | `implementation_units` lookup + triggering element check |
| **navigation** (route transition) | navigate, go to, return, open, redirect, link to, show, display, access | Playwright element presence + `navigation_graph` fallback |
| **structural** (client-side UI interaction) | filter, search, sort, drag, drop, reorder | Triggering element presence only — no HTTP mutation expected |

Unknown edge labels → default `navigation` (conservative).

---

**Per-entity E() — piecewise functions by entity type:**

The Conceptual Model formula `E(L1x) = α × [∑ E(primary_i) / P] + (1−α) × [∑ E(secondary_j) / S]` uses per-entity E() values. Each entity type in `path[]` has a different evidence source and a different piecewise function.

**`node` entity** (page/screen) — evidence: route lookup (L3) + page accessibility (L2):

| Route in Step 4 `frontend_routes` | Page accessible in Step 5 (Playwright) | E(node) |
|---|---|---|
| ✓ | `accessible: true` | 1.0 |
| ✓ | `discovered_by: "static_fallback"` only | 0.5 |
| ✗ | — | 0.0 |

**`element` entity** (UI element) — evidence: element presence in Step 5 Playwright DOM (L2) + Step 4 `route_elements` (L3 fallback):

| Element in Step 5 Playwright DOM | Element in Step 4 `route_elements` (L3) | E(element) |
|---|---|---|
| ✓ | — | 1.0 |
| ✗ | ✓ | 0.5 |
| ✗ | ✗ | 0.0 |

Matching resolved in Step 6a grounding pass: element entities are matched against the scoped inventory for the resolved route — Step 5 `elements[]` if the page was visitable; Step 4 `route_elements[route]` if not. The `match_source` field records which inventory was used.

**`data` edge entity** (edge label implies HTTP mutation — submit/create/add/delete/remove/update/save/mark) — FCom checks existence only, not linkage:

| Endpoint in Step 4 `implementation_units` | Triggering element on matched page in Step 5 | E(data_edge) |
|---|---|---|
| ✓ | found | 1.0 |
| ✓ | not found | 0.5 |
| ✗ | found | 0.4 |
| ✗ | not found | 0.0 |

HTTP verb heuristic on edge label: submit/add/create → POST; remove/delete → DELETE; update/edit/save/mark → PATCH or PUT. Endpoint matching resolved in Step 6a grounding pass: edge label + full requirement description + `implementation_units` list → `matched_endpoint` or null.

**navigation `edge` entity** (navigate/go to/return/open — no HTTP mutation implied) — evidence: navigation trigger in Step 5 Playwright DOM (L2) + Step 4 `navigation_graph` (L3 fallback):

| Nav trigger in Step 5 Playwright DOM | In Step 4 `navigation_graph` (L3) | E(navigation_edge) |
|---|---|---|
| ✓ | — | 1.0 |
| ✗ | ✓ | 0.5 |
| ✗ | ✗ | 0.0 |

Navigation triggers are scored via the same Playwright element presence mechanism as `element` entities — links and navigation-triggering buttons appear in `pages[].elements`. Step 4 `navigation_graph` captures static `<Link to>`, `<a href>`, `navigate()`, `router.push()` targets per route and serves as the L3 fallback signal. `outbound_links` is NOT used for E() scoring (unreliable for programmatic navigation — use `pages[].elements` which includes rendered link elements).

**`structural` edge entity** (edge label implies client-side UI interaction — filter/search/sort/drag/reorder — no HTTP mutation expected):

No `implementation_units` lookup. Check only for a triggering element on the page anchor — same evidence sources as `element` entities.

| Triggering element in Step 5 Playwright DOM | Triggering element in Step 4 `route_elements` (L3) | E(structural_edge) |
|---|---|---|
| ✓ | — | 1.0 |
| ✗ | ✓ | 0.5 |
| ✗ | ✗ | 0.0 |

The triggering element match result is reused from the element-matching pass for the same page anchor — no additional LLM call needed. This category exists because filter/search/sort edges in GEN/OBV requirements would be misclassified as `navigation` (scored too strictly) or `data` (incorrectly requiring a backend handler) without it.

**Aggregation:**
```
E(req) = α   × [∑ E(primary_i)   / P]
       + (1-α) × [∑ E(secondary_j) / S]
where α = 0.7. If S = 0, α = 1.0.
```

**Note on `api_calls_observed`:** Step 5's passive crawl only captures page-load GET requests. POST/PUT/DELETE from form submissions are never observed. `api_calls_observed` is supplementary cross-check against Step 4 only — not used for E() scoring. The L3 signal comes entirely from Step 4 `implementation_units` (filtered to `kind == "api_endpoint"`).

**Unlinked detection:**
```python
# Step 5 routes visited by Playwright where no L1a path[] node entity matched them
l2_unlinked_routes = set(step5_accessible_routes) - set(matched_routes_by_l1a_nodes)

# Step 4 endpoints not matched as the L3 signal for any L1a requirement
l3_unlinked_endpoints = set(step4_endpoint_keys) - set(matched_endpoint_keys_by_l1a)
```

**Output — stored at `job["step_results"]["step_6"]`:**
```json
{
  "mapped": [
    {
      "req_id": "REQ-001",
      "description": "User can log in",
      "e_score": 1.0,
      "entity_scores": [
        { "label": "navigate to login",     "type": "edge",    "primary": true, "e": 1.0, "edge_kind": "navigation", "matched_nav_target": "/login" },
        { "label": "Login Page",            "type": "node",    "primary": true, "e": 1.0, "matched_route": "/login", "evidence": "route /login found + page accessible" },
        { "label": "email input",           "type": "element", "primary": true, "e": 1.0, "matched_selector": "input[type='email']" },
        { "label": "password input",        "type": "element", "primary": true, "e": 1.0, "matched_selector": "input[type='password']" },
        { "label": "login button",          "type": "element", "primary": true, "e": 1.0, "matched_selector": "button[type='submit']" },
        { "label": "navigate to dashboard", "type": "edge",    "primary": true, "e": 1.0, "edge_kind": "navigation", "matched_nav_target": "/dashboard" }
      ]
    }
  ],
  "unlinked_l2": [
    { "route": "/", "title": "Home", "note": "No L1a requirement's path[] node entity matched this route" }
  ],
  "unlinked_l3": [
    { "method": "GET", "path": "/api/users/{id}", "handler": "getUser", "file": "src/main/java/.../UserController.java", "note": "No L1a requirement matched this endpoint as its L3 signal" }
  ]
}
```

---

### Step 7: Functional Completeness + Appropriateness Scorer — **COMPLETE**
**Phase: FCom — numeric scoring**
**Tools:** Python (formula only — no LLM for numeric scoring)
**Input:** Step 6 (traceability matrix with E() scores per requirement) + `step_3_5.confirmed_requirements` (L1a weights) + `step_3_5.advisory_requirements` (L1b weights)
**Computes in one pass:**
1. **FCom numeric:** `∑(E × weight) / ∑weight` for all L1a, where weight = user-assigned priority
2. **FA numeric:** `∑(E × weight) / ∑weight` for all L1b, where weight = strength-derived (3/2/1)
3. **FCom advisory — missing L1a:** L1a items with E()=0.0 or low E(), listed with gap description
4. **FCom advisory — unlinked functions:** L2_unlinked and L3_unlinked from Step 6
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
      "unlinked_routes": [
        { "route": "/", "title": "Home", "note": "No L1a requirement's path[] visits this route" }
      ],
      "unlinked_endpoints": [
        { "method": "GET", "path": "/api/users/{id}", "note": "No L1a requirement implies this endpoint" }
      ]
    }
  },
  "functional_appropriateness": {
    "score": 0.71,
    "per_implied": [
      { "req_id": "GEN-008", "description": "User can filter tasks", "e_score": 1.0, "weight": 3.0, "contribution": 3.0 },
      { "req_id": "GEN-009", "description": "User can bulk-delete tasks", "e_score": 0.0, "weight": 1.0, "contribution": 0.0 }
    ],
    "advisory": {
      "missing_l1b": [
        {
          "req_id": "GEN-009",
          "description": "User can bulk-delete tasks",
          "e_score": 0.0,
          "strength": "weak",
          "advisory_type": "normative_gap",
          "note": "Type A — implied by domain pattern (Step 3), not found in positive inventory"
        }
      ]
    }
  }
}
```

`advisory_type: "normative_gap"` marks Type A advisories (L1b gaps from Step 7). Step 7.5 produces `advisory_type: "positive_grounded"` (Type B). Both are displayed together in the dashboard under FA advisory, clearly labelled by type.
```

**Dashboard checkpoint:** FCom numeric + FA numeric + all advisories displayed together in the coverage view. First deliverable milestone — no test execution required.

---

### Frontend Types — Steps 5–7

**`types/index.ts` additions when Steps 6 and 7 are built:**

**`JobStatus` union — add:**
```typescript
| 'step_6_running' | 'step_6_complete' | 'step_6_error'
| 'step_7_running' | 'step_7_complete' | 'step_7_error'
```

**New interfaces:**
```typescript
export interface EntityScore {
  label: string
  type: 'node' | 'element' | 'edge'
  primary: boolean
  e: number | null
  // node
  matched_route?: string
  evidence?: string
  // element
  matched_selector?: string | null
  matched_page?: string
  // edge (all kinds)
  edge_kind?: 'data' | 'navigation' | 'structural'
  skipped?: string
  // data edge
  matched_endpoint?: string | null
  triggering_element_found?: boolean
  // navigation edge
  matched_nav_target?: string | null
  // structural edge — no additional fields beyond triggering_element_found
}

export interface MappedRequirement {
  req_id: string
  description: string
  e_score: number
  entity_scores: EntityScore[]
}

export interface Step6Result {
  mapped: MappedRequirement[]
  unlinked_l2: { route: string; title: string | null; note: string }[]
  unlinked_l3: { method?: string | null; path?: string | null; handler?: string | null; file?: string; note: string }[]
}

export interface Step7Detail {
  numerator: number
  denominator: number
  requirement_count: number
}

export interface Step7Result {
  fcom: number
  fa: number
  fcom_detail: Step7Detail
  fa_detail: Step7Detail
  unlinked_l2: Step6Result['unlinked_l2']
  unlinked_l3: Step6Result['unlinked_l3']
}
```

**`StepResults` — extend:**
```typescript
export interface StepResults {
  // ... existing fields ...
  step_6?: Step6Result
  step_7?: Step7Result
}
```

**App.tsx — terminal statuses to add:**
```typescript
const terminalStatuses = [
  // ... existing ...
  'step_6_complete', 'step_6_error',
  'step_7_complete', 'step_7_error',
]
```

**New components:**

`MappingResult.tsx` (Step 6) — loading skeleton when `loading` prop is true; per-requirement row with `req_id` pill, description, E() score bar (≥0.8 green, 0.5–0.8 yellow, <0.5 red); expandable popdown showing `entity_scores[]` table with type badge (node/element/edge), edge_kind badge (data/navigation/structural), primary/secondary chip, E value, evidence note; collapsible unlinked L2 routes and L3 endpoints advisory sections.

`ScoringResult.tsx` (Step 7) — loading skeleton when `loading` prop is true; two score panels (FCom, FA) each with large numeric score, labelled progress bar, detail line (`N requirements · X.XX / Y.YY weighted`); collapsible unlinked L2/L3 advisory lists.

---

### Step 7.5: Positive-Grounded FA Advisor
**Phase: FA advisory — post-codebase improvement suggestions**
**Status: COMPLETE**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:**
- Step 4 result: `implementation_units`, `database_models`, `frontend_routes`, `languages` — what the codebase actually contains
- Step 5 result: per-page element inventory — what the running app exposes
- `step_3_5.confirmed_requirements` (L1a) — stated purpose and domain context
- `step_3_5.advisory_requirements` (L1b) — Step 3's pre-codebase implied suggestions, used as dedup reference
- `step_3_5.project_summary` — domain context for LLM

**Why this step exists — epistemics of two advisory types:**

Step 7's FA advisory (Type A) surfaces L1b items that scored low E() against the positive inventory. These are normative-grounded: "your app is missing something the domain implied it should have." But Step 3 generated L1b items *before seeing the codebase* — its SOP patterns and INF domain inference operated on requirement text and project type only.

This step generates Type B advisory: *positive-grounded* improvement suggestions derived from what the codebase actually contains. After Step 4 reveals real database models, endpoint patterns, and data relationships, an LLM can make suggestions that are specific to this codebase's actual structure — things Step 3 could not predict.

**Example of what Type A vs Type B looks like in practice:**

Type A (Step 7, normative-grounded): "User can filter tasks by status — this is a standard pattern for apps with a named status field (Step 3 confidence 0.82). Not found in codebase."

Type B (Step 7.5, positive-grounded): "Your schema has `team_id` on the Task model and a User model with a team relationship. Consider adding a team-scoped task view or assignee filter — this would extend your stated task management requirements into multi-user workflows that the data model already supports."

**Logic:**

1. LLM is given the positive inventory (Step 4 models/endpoints, Step 5 pages) alongside the L1a confirmed requirements and project summary.
2. Grounding step first: understand what this app actually does, what data it manages, what patterns are already established in the code.
3. Generate improvement suggestions specifically grounded in the positive inventory — only suggest features that are natural extensions of what already exists in the schema or endpoint structure.
4. Deduplicate against Step 3 L1b items — do not re-surface suggestions that Step 3 already generated (those are Type A; this step adds Type B only).
5. Each suggestion includes: what feature to add, which part of the positive inventory it builds on (specific model/endpoint/page), and why it would improve functional appropriateness.

**Output — stored at `job["step_results"]["step_7_5"]`:**
```json
{
  "suggestions": [
    {
      "suggestion_id": "FA-POS-001",
      "description": "User can view tasks assigned to team members",
      "grounded_in": {
        "models": ["Task", "User"],
        "endpoints": ["GET /api/tasks"],
        "rationale": "Task model has team_id and assigned_to fields; current task list endpoint has no team-scoped view"
      },
      "l1a_connection": "REQ-003 (User can manage tasks) — extends the existing task domain into multi-user scope",
      "priority": "medium"
    }
  ],
  "total_count": 4
}
```

**Display:** Shown in the dashboard alongside Step 7's Type A FA advisory (L1b gap items). Clearly labelled as "Codebase-grounded suggestions" to distinguish from "Implied feature gaps." Sorted by specificity of grounding — suggestions tied to multiple concrete models/endpoints first.

**Relationship to Step 3:** Step 3 is pre-codebase inference (domain patterns → implied requirements). Step 7.5 is post-codebase inference (actual structure → improvement suggestions). Together they form the complete FA advisory surface: what the domain implied the app should have (Type A) plus what the app's own structure suggests it could do (Type B).

---

### Step 8: Acceptance Criteria Generator
**Phase: FCor setup**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** L1a requirement list as finalised after Step 3.5 (or directly from Step 1+2 if Step 3.5 was skipped), including locked L1Cx per requirement
**Scope:** Only generates ACs for requirements in S = { x ∈ L1a | x ∈ L3 }. Requirements with E()=0.4, 0.25, or 0.0 are skipped — their gaps are already captured in FCom advisory.
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

FCor = ∑(pass_i × ACw_i) / ∑ ACw_i      [i ∈ ACs of requirements in S*]
CP  = ∑_blocked_L1Cx / ∑_all_L1Cx
```
Requirements excluded from S (E()=0.4, 0.25, 0.0) do not appear in FCor — their gaps are captured in FCom.
**Output:** FCor ratio + per-requirement AC breakdown + CP confidence penalty

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
**Aggregates** all layer data into one structured, auditable evidence package. Every score is traceable: FCor → AC results → test logs → L4; FCom → E() scores → L2/L3 evidence → L1a requirements.

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
- FCom score + FA advisory with data layer comparison labels
- FCor score + CP confidence penalty
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
| 2 — Requirements Pipeline | Steps 1, 2, 3, 3.5 | ✓ DONE |
| 3 — Repo Parser | Step 4 | ✓ DONE |
| 4 — Inventory + Mapping + Completeness | Steps 5, 6, 7, 7.5 | ✓ DONE |
| 5 — AC Generation + Test Execution | Steps 8, 9, 10, 11, 12 | Not started |
| 6 — Scoring + Dashboard | Steps 13, 14, 15, 16, 17 | Not started |
