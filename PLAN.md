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

`L1Cx` = confidence weight (critical = 4, high = 3, medium = 2, low = 1; default 1.0)

State-variant nodes (labels with parentheticals like "(filtered)", "(sorted)", "(updated)") always have `primary: false` — Step 6 skips L2 route matching for them; they serve as Step 9 AC hints only.

### Functional Appropriateness (FA) — L1b vs (L2 ∪ L3)

**ISO 25010 clause 3.1.3:** *"A product provides the necessary and sufficient steps to complete a task, excluding any unnecessary steps."*

This grounds the biconditional:
- L1b → (L2∪L3): *necessary direction* — are implied functions present? → scored
- (L2∪L3) → L1b: *sufficient/unnecessary direction* — are there functions with no stated purpose? → advisory only

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

Alternative (if all three sub-characteristics must be numerically scored): 40% FCom + 45% FCor + 15% FA. Preferred option is 50/50 because FCom and FCor are backed by harder evidence.

---

## Conceptual Distinctions — FCom, FA, FCor

**The distinguishing question for FCom vs FA:**
> "If this function is absent, is the software *broken* or just *worse*?"

FCom gap = the software fails at its stated purpose. FA gap = the software succeeds but inefficiently.

FCom = *coverage* — does the software have enough? FA = *calibration* — does it have the right set (necessary and sufficient, per ISO 3.1.3)? The ISO definitions are nearly circular; this directional framing resolves the ambiguity.

**FCom vs FA is a spectrum, not a binary:**

```
EXPLICIT          OBVIOUS          IMPLIED          UNRELATED
stated in         so basic         would help       exists with
requirements      nobody           but absence      no objective
                  writes it        isn't broken     at all
     |________________|________________|________________|
     L1a              L1a              L1b              Unlinked
     <————————— FCom —————————><————————— FA ——————————————>
```

- L1a (stated + obvious) → FCom: coverage of expected functions
- L1b (implied) → FA necessary direction: implied enablers that improve task efficiency
- Unlinked L2 → FA sufficient direction: user-facing functions with no stated or implied purpose (unnecessary steps per ISO 3.1.3). L3-only internal code paths are excluded — they are invisible to users and do not constitute "steps" in the ISO sense.

**FA has two failure modes; FCom has one:**
- FCom: missing expected function (app is incomplete)
- FA necessary: missing implied enabler (app is harder to use)
- FA sufficient: unnecessary function present (app has extra complexity)

**Why Step 3.5 exists:**
The FCom/FA boundary — between "obvious" (L1a) and "implied" (L1b) — is a judgment call about how fundamental a function is to the app's purpose. It cannot be objectively derived. Step 3.5 is the human resolution gate for this ambiguity: the user promotes L1b items to L1a when they consider them expected rather than merely helpful.

**Why behavioural properties belong in the AC layer, not L1a/L1b:**
Items like "data persists across restarts", "error message shown on failure", "confirmation before delete" are not *functions* — they cannot be mapped to a UI element or API endpoint in Step 6. They are behavioural properties of existing functions and belong as acceptance criteria at Step 8. FCom and FA both measure whether *functions* exist; FCor measures whether those functions *behave correctly*. The three axes are orthogonal. Persistence, feedback, and error handling sit on the FCor axis, not the FCom or FA axis.

**L1a validity model — generate, confirm, lock:**
Steps 1–3 produce heuristic starting points. The LLM reasons from project type and stated requirements, not the actual codebase — it can fabricate requirements for features that don't exist in this specific app, assign wrong weights, or miss app-specific functions. This is expected and by design. The formula is only valid after **Step 3.5 locks L1a**. Skipping Step 3.5 produces an unreliable FCom score. The `functional_area` tag on each L1a item helps reviewers spot fabricated clusters — if an entire cluster (e.g. all "product_detail" requirements) has no match in the uploaded code, the cluster is likely fabricated and should be deleted at Step 3.5.

**Cascade sensitivity:**
FCom is sensitive to dependency chains. If a root feature is absent from L3, all downstream requirements cascade to E=0, producing a score that may feel disproportionately low. This is technically accurate (the app IS missing those functions) but uninformative about root cause. Step 7 advisory output will group E=0 items by `functional_area` and flag cascade clusters ("N requirements missing — likely one root component absent"). Step 3.5 also mitigates this: reviewers can remove requirements they consider preconditions of others rather than independent objectives.

---

## The Evaluation Space as a 2D Plane

Every requirement is a point on a 2D plane. All pipeline step prompts are written with this model as their grounding. Prompts in future steps should reference it.

### X axis — explicitness (and feature dependency depth)

```
stated       obvious       implied       unlinked
 (L1a)        (L1a)         (L1b)        (L2/L3 only)
   |____________|_____________|_____________|
   <—— FCom ——><——————————— FA ———————————————>
```

The X axis encodes both how explicitly a requirement was stated AND its depth in the feature dependency tree. This is structural, not accidental: people articulate what a system *is* (roots), not what it must enable as prerequisite infrastructure.

- **Stated (roots):** Foundational capabilities that define the app's purpose. Auth, core data model, primary CRUD actions. All other features depend on these. Users write them down because they define what the app does.
- **Obvious (direct dependents):** Assumed by any user; never written down. Two sub-types: (1) *dependency connectors* — what stated requirements depend on to be independently testable (e.g. "user can view task list" makes "user can add task" verifiable); (2) *app-type usability* — navigation, affordances, and feedback functions any user expects regardless of what is stated (e.g. back navigation from sub-pages with no navbar, empty states on list views).
- **Implied (second-order dependents):** Enhancements built on top of the obvious layer — filtering, sorting, bulk operations. Would improve the app; absence isn't catastrophic if roots are solid.
- **Unlinked (orphaned):** Exists in L2/L3 but has no stated or implied purpose.

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

### Cascade: X and Y interact via dependency

A Y=0 at a root position (stated, left of X) cascades to Y≈0 for all dependents, regardless of their X position. If auth is absent (Y=0, root), then task management (obvious, dependent) also fails — not because task code is missing, but because its prerequisite is absent. FCom correctly assigns E≈0 to all cascading items, but Step 7 advisory must surface the root cause.

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

**Note on E()=0.5 (implemented, not UI-accessible):** A requirement that maps only to a backend component with no UI exposure is still valid for backend_api_only projects. For full-stack apps it represents a completeness gap — the function exists but users cannot reach it — which FCom advisory flags. The current prompt focus is full-stack web applications; backend_api_only project type is out of scope for the MVP prompt design.

### E()=0.4 known gap

E()=0.4 (UI visible, no backend) sits lower than E()=0.5 (backend present, no UI) because FCor requires backend. But 0.4 is *worse* for users — they see a form that does nothing, setting expectations that are immediately broken. These requirements are excluded from FCor. Step 14 (Workflow Friction Analyser) catches this experientially. Not numerically scored in FCor — a known model limitation.

### Prompt design philosophy (all steps)

The X/Y plane determines what each pipeline step's LLM should and should not do:

**Step 1 (stated):** Extract user-facing functions from stated requirements text. Each function is expressed in active voice ("User can [action]") and includes a `path: PathEntity[]` — the ordered traversal of UI entities the user visits to complete the goal. `primary: true` = entity fundamentally asserted by this function (scored); `primary: false` = context node asserted by another function. Vague functions that cannot yield a specific path get `vague: true` and a minimal single-node path; Step 3 decomposes them. Gate (positive framing): "Does this text describe a goal a user can directly perform?" — rejects backend subjects, quality attributes, automatic behaviors, and system reactions.

**Step 2 (obvious):** Graph connectivity gaps only — no usability inference. Extract node inventory from Step 1 function path arrays (state-variant labels excluded). Run two checks per node:
- *Check 2 — Entry paths:* Is there a stated inbound navigation? If NO → generate a navigation function with edge (`primary: true, from: null`) + destination node (`primary: false`).
- *Check 3 — Exit paths:* Is there a stated exit? If NO → generate a navigation function with source node (`primary: false`) + exit edge (`primary: true, to: null`).

Never generate: auth guards, session management, invocation controls, observable outcomes, error messages, empty states, or anything phrased "System must X when Y." Deduplication is semantic — if a stated function already covers the navigation, do not regenerate it.

**Step 3 (implied):** Two-pass generation — each output is a complete function with traversal path (entry + body + exit). FA-scored (not FCom-scored). Confidence ≥ 0.80 → `placement: "l1a"` candidate at Step 3.5; below → `placement: "l1b"` advisory. Gate: "Can a user independently perform this goal?" YES → include. NO → discard.
- *Pass 1 — SOP pattern-triggered:* Fires on Step 1 stated nodes against a fixed pattern table (list→filter/sort/edit/delete; auth→profile; status-field→cross-status overview; temporal→calendar view; etc.). Vague Step 1 functions are priority unpack targets — all applicable patterns fire, with `unpacks: "<parent_req_id>"`.
- *Pass 2 — INF domain inference:* Pure open-ended reasoning from `project_summary` — what would a regular user return to repeatedly that Pass 1 didn't cover? No checklist.

No `structural_edge` category — entry/exit paths are baked into each function's path array.

**Step 8 (ACs):** ACs live on the Y axis — they measure Phase 2 correctness. ACs for dependent requirements should first assert prerequisites are satisfied. Persistence, error messages, and edge-case handling are ACs, not L1a requirements.

**Step 11 (test execution):** Execute in dependency order — test roots first. If a root fails, mark its dependents as cascade-blocked rather than running them as independent tests. This distinguishes true independent failures from cascade failures in the FCor output.

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
Note: `primary_language` is not in Step 0 output. Step 4 produces the authoritative `languages` array from source parsing.

**Test strategy design:** For `backend_api_only`, `primary` is always the HTTP-level integration test tool — never a unit test runner, which does not verify HTTP-level requirements. For `full_stack_web_app`, `primary` is Playwright E2E and `secondary` is the backend API test tool (for L3-only requirements not accessible via the UI). Implementation details in CLAUDE.md.

**Known limitation:** Next.js, SvelteKit, Nuxt standalone (no separate backend service) are classified as `frontend_only`. Full re-classification to `full_stack_web_app` deferred to after Step 4 repo parsing.

---

### Step 1: Stated Requirement Extractor
**Status: COMPLETE**
**Phase: FCom setup — builds L1a (stated)**
**Tools:** Python, LLM (AsyncAnthropic, prompt caching)
**Input:** Requirements text provided by user + README (read directly from zip) + any uploaded specification documents
**Function model:** Every extracted requirement is a **function** — a user-facing goal described in active voice ("User can log in"). Each function includes a `path: PathEntity[]` — an ordered traversal of UI entities the user visits to complete the goal.
**PathEntity schema:**
```
{ type: "node"|"element"|"edge", label: string, primary: boolean, ui_node?: string, from?: string, to?: string }
```
`primary: true` = this entity is fundamentally asserted by this function (E() penalises its absence). `primary: false` = context node already asserted by another function.
**Gate (positive framing):** Before extracting any item, test: "Does this text describe a goal a user can directly perform?" Rejects: backend subjects, quality attributes, automatic behaviors, system reactions ("X happens when/if Y"). Implemented as a positive test — LLMs ignore growing negative lists when priors are strong.
**Vague flag:** If source text is too broad to build a specific path (e.g. "users can manage tasks"), set `vague: true` with a minimal single-node path. Step 3 decomposes vague functions via `unpacks` targeting.
**Rule:** Only extract what is **explicitly stated**. No inference. Every item must include its verbatim source quote. Source quote verification uses whitespace-normalised comparison (anti-hallucination; newlines → spaces tolerated).
**Tag:** `stated`
**Output (step_results.step_1):**
```json
{
  "project_summary": "A personal task and goal management web app where users create named categories and track goal rows with due dates, importance, and status.",
  "requirements": [
    {
      "req_id": "REQ-001",
      "description": "User can log in",
      "path": [
        {"type": "edge",    "label": "navigate to login",  "primary": true, "from": null,         "to": "Login Page"},
        {"type": "node",    "label": "Login Page",         "primary": true},
        {"type": "element", "label": "email input",        "primary": true, "ui_node": "Login Page"},
        {"type": "element", "label": "password input",     "primary": true, "ui_node": "Login Page"},
        {"type": "element", "label": "login button",       "primary": true, "ui_node": "Login Page"},
        {"type": "edge",    "label": "navigate to dashboard", "primary": true, "from": "Login Page", "to": "Dashboard"}
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

---

### Step 2: Obvious Requirement Generator
**Status: COMPLETE**
**Phase: FCom setup — builds L1a (obvious)**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** Step 0 (project_type, framework) + Step 1 (stated requirements with path arrays)
**3-check deterministic prompt (graph connectivity gaps only):**
- Check 1 — Build node list: extract nodes from Step 1 function path arrays + discovered page files (deduplicated, state-variant labels excluded)
- Check 2 — Entry paths: for each node except home, is there a stated inbound navigation element? If NO → generate a navigation function with an edge (`primary: true, from: null`) + destination node (`primary: false`)
- Check 3 — Exit paths: for each node, is there a stated way to leave it? If NO → generate a navigation function with a source node (`primary: false`) + exit edge (`primary: true, to: null`)
**Never generate:** auth guards, session management, invocation controls for stated capabilities, observable outcomes, error messages, empty states, or anything phrased "System must X when Y."
**Root node detection:** `_identify_root_node()` detects the home/root page by parsing nodes from Step 1 path arrays. Detected root injected as `=== ROOT / HOME PAGE ===` — LLM skips CHECK 2 for it.
**Logic:** LLM reasons YES/NO per node per check, then outputs JSON functions with path arrays. Deterministic — only graph connectivity gaps.
**Deduplication:** Step 1 stated functions passed with req_id prefix for reference.
**Tag:** `obvious` | **Weight:** derives from priority (critical=4.0, high=3.0, medium=2.0, low=1.0) — same as Step 1
**Output:**
```json
[
  {
    "req_id": "OBV-001",
    "description": "User can navigate to Task List Page",
    "path": [
      {"type": "edge", "label": "navigate to task list", "primary": true, "from": null, "to": "Task List Page"},
      {"type": "node", "label": "Task List Page", "primary": false}
    ],
    "source": "obvious",
    "reasoning": "CHECK 2 — Task List Page has no stated inbound navigation element",
    "tag": "obvious",
    "depends_on": ["REQ-003"],
    "priority": "high",
    "weight": 3.0,
    "testable": true,
    "functional_area": "navigation"
  }
]
```

**Combined L1a pool:** Step 1 (stated) + Step 2 (obvious) → forms the initial L1a before Step 3.5 confirmation.

Note: Key accuracy step. Consider requirement dependencies and branching which will bias the score

---

### Step 3: L1b Implied Enhancement Generator
**Status: COMPLETE**
**Phase: FCom setup — builds L1b (and L1a candidates)**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:** Step 0 (project type) + Step 1 (functions + `project_summary`) + Step 2 (combined L1a pool)
**Two-pass generation — each output is a complete function with traversal path:**

**Pass 1 — SOP pattern-triggered functions**
Fires only on nodes from Step 1 stated functions. Checks each node against the SOP pattern table:
- List node → filter (~0.82), search (~0.80), sort (~0.68), edit item (~0.85), delete item (~0.82)
- Detail node → edit (~0.85), delete (~0.82)
- CRUD COMPLETION RULE: when CREATE is stated for an entity, edit and delete complete the CRUD cycle → always L1a (≥0.85 / ≥0.82)
- Auth present → account management / profile page (~0.87)
- Named changeable status field → cross-status overview page (~0.75), filter-by-status element (~0.82)
- Temporal field (dates, deadlines) → time-scoped view / calendar view (~0.75)
- Mutable records (edit/update stated) → audit / history page (~0.60)
- User-configurable preferences stated → settings page (~0.82)
- Time-sensitive deadlines or thresholds → notification surface (~0.65)
- Multi-user / per-user data → user profile / identity page (~0.82)

Vague unpack targeting: functions with `vague: true` in Step 1 are priority targets — apply ALL applicable patterns and set `unpacks: "<parent_req_id>"` on each child.

**Pass 2 — INF domain inference**
Read `project_summary` and all stated functions. Generate functions across 7 domain-completeness angles that Pass 1 did not cover:
1. RECURRING USE — frequent/daily functions (status checks, monitoring)
2. WORKFLOW COMPLETENESS — onboarding, getting-started, completion states
3. DATA MANAGEMENT — bulk ops, export, import, archive, restore, history
4. DOMAIN STANDARDS — what a comparable app always offers as standard
5. DISCOVERABILITY + HELP — help page, onboarding tour, empty-state guidance
6. USER CONTROL — settings, preferences, notification controls, customisation
7. OVERVIEW + INSIGHT — dashboards, analytics, summary views

Bold generation — generates at confidence 0.50–0.70 for genuine domain gaps; breadth over silence because this pass drives FA scoring.

**Confidence → placement:**
- ≥ 0.80 → `placement: "l1a"` (promoted to FCom scoring pool at Step 3.5)
- 0.60–0.79 → `placement: "l1b"`, strength: `strongly_implied`, weight: 3.0
- 0.40–0.59 → `placement: "l1b"`, strength: `medium`, weight: 2.0
- < 0.40 → `placement: "l1b"`, strength: `weak`, weight: 1.0

**Path construction:** Every generated function includes a complete `path[]` with entry edge, body entities, and exit edge. New-page introductions: entry edge + destination node both `primary: true`; exit edge `primary: false`. Element functions: element(s) + submit edge `primary: true`, containing page `primary: false`. State-variant nodes always `primary: false`. No `structural_edge` category — entry/exit are baked into the function's path.

**Tag:** `generated` | **Categories:** `"sop"` | `"inf"`
**Output:**
```json
[
  {
    "req_id": "GEN-001",
    "description": "User can view account information",
    "path": [
      {"type": "edge",    "label": "navigate to account",   "primary": true,  "from": "Dashboard",    "to": "Account Page"},
      {"type": "node",    "label": "Account Page",           "primary": true},
      {"type": "element", "label": "profile information",   "primary": true,  "ui_node": "Account Page"},
      {"type": "element", "label": "change password form",  "primary": true,  "ui_node": "Account Page"},
      {"type": "edge",    "label": "return to dashboard",   "primary": false, "from": "Account Page", "to": "Dashboard"}
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
]
```

**Step 3 result envelope:**
```json
{
  "requirements": [...],
  "total_count": 12,
  "sop_count": 5,
  "inference_count": 7,
  "llm_model": "claude-haiku-4-5-20251001",
  "dropped_count": 2,
  "error": null
}
```

---

### Step 3.5: Human Requirement Confirmation *(optional)*
**Status: COMPLETE**
**Phase: FCom setup — locks L1a**
**Tools:** React UI, FastAPI endpoint, async job queue
**Input:** Step 1 (stated functions) + Step 2 (obvious functions) + Step 3 (L1b with placement and weights)
**Architecture:** Pipeline pauses with status `waiting_for_confirmation`. Resumes when user submits confirmed list.

**User can:**
- Confirm, edit, delete, reprioritise any L1a function
- Adjust priority weights (critical=4, high=3, medium=2, low=1)
- Promote L1b functions to L1a (adds them to FCom and FCor scoring)
- Add entirely new functions

**Display — three sections:**
1. **L1a Section** — stated + obvious pre-included; Step 3 `placement: "l1a"` candidates also pre-included but demotable. Each row shows req_id, description, tag badge, priority dropdown. Expandable popdown reveals traversal path (PathDisplay), reasoning, and confidence detail.
2. **L1b Advisory Section** — Step 3 `placement: "l1b"` items, each promotable to L1a. Expandable popdown shows path, reasoning, confidence.
3. **Add Function** — inline form producing `CUSTOM-001` IDs.

**Vague auto-replace:** Vague Step 1 functions (`vague: true`) are excluded from the initial L1a state. Any Step 3 functions with `unpacks: "REQ-xxx"` pointing to a vague parent are auto-included in L1a Section, replacing the parent. A notice shows "N vague stated function(s) were auto-replaced by their Step 3 children."

**After confirmation:** L1a is locked. Pipeline resumes.
**If skipped:** All stated (non-vague) + obvious functions treated as L1a at default weights. L1b remains advisory.

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

**Dashboard checkpoint:** FCom numeric + FA numeric + all advisories displayed together in the coverage view. First deliverable milestone — no test execution required.

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
| 3 — Repo Parser | Step 4 | Not started |
| 4 — Inventory + Mapping + Completeness | Steps 5, 6, 7 | Not started |
| 5 — AC Generation + Test Execution | Steps 8, 9, 10, 11, 12 | Not started |
| 6 — Scoring + Dashboard | Steps 13, 14, 15, 16, 17 | Not started |
