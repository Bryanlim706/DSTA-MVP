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

`L1Cx` = `weight` on each requirement. Derives from two separate sources depending on layer:

- **L1a (`confirmed_requirements`):** `priority` label → weight. critical=4.0, high=3.0, medium=2.0, low=1.0. User can override priority at Step 3.5; the locked weight is what FCom reads.
- **L1b (`advisory_requirements`):** `confidence_score` (Step 3 LLM, 0.0–1.0) → `strength` label → weight. The confidence_score drives two one-time decisions at Step 3 generation time: (1) placement — ≥0.80 → `"l1a"` candidate, <0.80 → `"l1b"`; (2) strength — 0.60–0.79 → `strongly_implied` (weight 3.0), 0.40–0.59 → `medium` (weight 2.0), <0.40 → `weak` (weight 1.0). After these decisions, `confidence_score` is not used in any formula — `weight` is.

**Both FCom and FA output 0–1.** Both are weighted averages (∑(E×w)/∑w) — dividing by ∑weight normalises to 0–1 regardless of the maximum weight value (4 for L1a, 3 for L1b). The max weight only controls how much a single requirement pulls the average relative to others. Step 17 multiplies the final Functional Suitability score by 5 for display → 0–5 scale.

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

**L1a and L1b are a spectrum, not a binary — and the scoring philosophy must reflect this:**

The distinction between L1a (confirmed) and L1b (advisory) is a practical cut point on a continuous spectrum of certainty about what software should contain — not an ontological divide. The confidence scores generated by Step 3 encode exactly where on this spectrum each implied requirement falls. They were not generated for display only; they are the normative weight for FA scoring.

The spectrum has two regions with different scoring philosophies:

**FCom region — confirmed normative vs positive:**
L1a requirements have been confirmed by a human at Step 3.5. Their normative authority is locked and binary — a requirement is in L1a or it is not. FCom measures whether the positive evidence (Steps 4, 5) satisfies these confirmed claims. The E() comparison is strict: if a confirmed L1a requirement is absent from the positive inventory, FCom suffers, full stop. Steps 4–6 exist primarily to serve FCom.

**FA region — probabilistic normative vs positive:**
L1b requirements were NOT confirmed. Their normative claim is probabilistic — the Step 3 LLM believed with some confidence that these features would be appropriate, based on domain patterns and the app's stated purpose. The confidence score encodes the strength of that claim:
- `strongly_implied` (0.60–0.79): the LLM had a near-certain hypothesis — this feature almost always accompanies the stated functions in this app category
- `medium` (0.40–0.59): a reasonable domain expectation, but context-dependent
- `weak` (< 0.40): a plausible suggestion, but the LLM was uncertain whether this app warrants it

FA scores each L1b item against the positive inventory using the same E() mechanism as FCom, but weighted by its confidence-derived strength. A `strongly_implied` L1b item absent from the positive inventory is a meaningful FA gap — its near-certain claim was unmet. A `weak` item absent is almost no signal — it was a low-confidence suggestion. The formula `∑(E × L1Cx) / ∑ L1Cx` [x ∈ L1b] naturally encodes this: the denominator is dominated by high-weight items, so FA is primarily driven by the high-confidence L1b claims.

This is why FA is advisory rather than primary: its normative claims are unconfirmed LLM hypotheses, not human-locked requirements. But it is not purely observational either — it IS a normative vs positive comparison, just with probabilistic rather than confirmed normative authority.

**The practical consequence for Steps 4–6:**
Step 6 runs E() scoring for both L1a (for FCom) and L1b (for FA). The mechanism is the same. The difference is only in the weights and in the framing of the result: L1a E() scores feed a primary metric; L1b E() scores feed an advisory metric. There is no "contamination" — the positive inventory (Steps 4, 5) is the shared evidence base, and both FCom and FA draw from it with appropriate epistemic authority.

**Why Step 3.5 exists:**
The FCom/FA boundary — between "obvious" (L1a) and "implied" (L1b) — is a judgment call about how fundamental a function is to the app's purpose. It cannot be objectively derived. Step 3.5 is the human resolution gate for this ambiguity: the user promotes L1b items to L1a when they consider them expected rather than merely helpful.

**Why behavioural properties belong in the AC layer, not L1a/L1b:**
Items like "data persists across restarts", "error message shown on failure", "confirmation before delete" are not *functions* — they cannot be mapped to a UI element or API endpoint in Step 6. They are behavioural properties of existing functions and belong as acceptance criteria at Step 8. FCom and FA both measure whether *functions* exist; FCor measures whether those functions *behave correctly*. The three axes are orthogonal. Persistence, feedback, and error handling sit on the FCor axis, not the FCom or FA axis.

**Known gap — system-automatic (behavioral) requirements:**
Some stated requirements describe behaviors the system performs automatically, without user initiation: `"daily auto reset happens"`, `"notifications sent at midnight"`, `"cache expires after 1 hour"`. These are not user-navigable functions and correctly fail Step 1's extraction gate. However, force-converting them to UI functions (e.g. `"User can view daily reset status"`) is lossy — it changes the primary assertion from a scheduled behavior to a display element, producing wrong ACs and wrong E() scoring (FCom checks for a UI element instead of a scheduler in L3).

The correct model (deferred to before Step 8):
- Step 1 extracts these as `type: "behavioral"` with `path: null` instead of a UI traversal path
- Step 6 skips L2 matching for behavioral items; E() is L3-only (does the scheduler/cron/event handler exist in code?)
- Step 8 generates time/state-based ACs: *"Given [initial state], when [trigger fires], then [system state changes]"* — not UI-element checks

**Decision:** Defer until before Step 8. Steps 4–7 (completeness pipeline) are unaffected — they process whatever is in `step_3_5.confirmed_requirements` and do not depend on requirement type. During Steps 4–7 development, behavioral requirements that are incorrectly converted can be deleted at Step 3.5 human review. The schema change (Step 1 type field, Step 3.5 Pydantic model, Step 6 E() branching, Step 8 AC template) will be designed as one unit before Step 8 is built.

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
Note: `primary_language` is not in Step 0 output. Step 4 produces the authoritative `languages` array from source parsing.

`discovered_pages` is populated by `_discover_pages()`: HTML files in `templates/`/`views/`; HTML at root/static dirs; `.tsx/.jsx/.vue/.svelte` in `pages/`/`screens/`; SSR template engine files (`.blade.php`, `.erb`, `.cshtml`, `.ejs`, etc. from `_TEMPLATE_ENGINE_EXTS`) in `views/`/`templates/`; Android `*Activity.java`/`*Activity.kt` files anywhere.

**Output consumed by:**
| Field(s) | Consumed by |
|---|---|
| `project_type`, `frontend_framework`, `backend_framework` | Step 3 (project context in LLM prompt) |
| `discovered_pages` | Step 2 (node inventory + root detection), Step 3 (root node detection) |
| `test_strategy` | Step 9 (test type selection — not yet built) |
| `project_type`, `frontend_framework`, `backend_framework` | Step 4 (determines where to look for routes/models) |
| Full result | Step 5 (strategy selection for static vs. dynamic crawl) |

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
- Check 1 — Build node list from path arrays + discovered pages
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

**Steps 1 and 2 outputs are fully subsumed** by `confirmed_requirements` for all downstream purposes. Steps 4+ read only `step_3_5` for all milestone-1 data. Steps 0–3 individual results remain in job JSON as internal pipeline state (Steps 15–16 may read them for reporting).

**Fields dropped at Step 3.5 — not needed by any downstream step:**

*Step 0 — dropped from `project_context`:*
| Field | Why dropped |
|---|---|
| `confidence` | Classification confidence ("high"/"medium"/"low") — internal to Step 0's decision; architectural identity is locked |
| `reasoning` | Explains why Step 0 chose this project type — internal to classification |
| `config_files_found` | Which config files Step 0 read — internal to classification |
| `llm_used` | Whether LLM was called for classification — processing metadata |
| `llm_model` | Which model Step 0 used — processing metadata |

*Step 1 — dropped envelope fields:*
| Field | Why dropped |
|---|---|
| `total_count` | Count of extracted requirements — UI display only |
| `docs_used` | Which docs were read — UI display only |
| `truncated_docs` | Which docs were truncated — UI display only |
| `excluded_docs_count` | How many docs hit the MAX_DOCS cap — UI display only |
| `llm_model` | Processing metadata |
| `dropped_count` | How many requirements failed validation — processing metadata |
| `error` | Step 1 error string if extraction failed — processing metadata |

*Step 1 — per-requirement fields: none dropped.* All fields (`req_id`, `description`, `path`, `vague`, `source`, `source_quote`, `tag`, `priority`, `weight`, `testable`, `functional_area`) are preserved in `confirmed_requirements`.

*Step 2 — dropped envelope fields:*
| Field | Why dropped |
|---|---|
| `total_count` | Processing metadata |
| `llm_model` | Processing metadata |
| `dropped_count` | Processing metadata |

*Step 2 — dropped per-requirement fields:*
| Field | Why dropped |
|---|---|
| `reasoning` | "CHECK 2 — ..." / "CHECK 3 — ..." text — explains why the gap was generated; only needed in Step 3.5 UI |

*Step 3 — dropped envelope fields:*
| Field | Why dropped |
|---|---|
| `total_count` | Processing metadata |
| `sop_count` | Processing metadata |
| `inference_count` | Processing metadata |
| `llm_model` | Processing metadata |
| `dropped_count` | Processing metadata |
| `error` | Processing metadata |

*Step 3 — dropped per-requirement fields for promoted l1a items (GEN-XXX in `confirmed_requirements`):*
| Field | Why dropped |
|---|---|
| `category` | "sop" or "inf" — only needed in Step 3.5 UI for display |
| `reasoning` | Why the function was generated — only needed in Step 3.5 UI |
| `confidence_score` | Raw 0.0–1.0 float — job done; produced `placement` + `weight` |
| `confidence_reason` | Explanation of confidence — only needed in Step 3.5 UI |
| `placement` | "l1a" — redundant once confirmed |
| `strength` | null for l1a items; weight already derived |

*Step 3 — l1b items (`advisory_requirements`): no fields dropped.* Copied as-is with full schema including `path[]`, `strength`, `weight`, `confidence_score`, `category`, `reasoning`, `confidence_reason`, `depends_on`.

**If skipped:** `confirmed_requirements` = all Step 1 stated (non-vague) + all Step 2 obvious at default weights; `advisory_requirements` = all Step 3 l1b items; `project_context` and `project_summary` still populated. The skip logic is frontend-driven — ConfirmationTable pre-populates the HTTP body with only stated+obvious items; the backend stores `skipped: true` but applies no special branching.

---

### Data Flow — Steps 0 to 3.5

The pipeline is a DAG, not a linear chain. Step 1 reads from disk independently of Step 0. Step 0 bypasses Step 1 and feeds directly into Steps 2, 3, and 3.5. Step 3.5 is a full fan-in that reads all four prior step results simultaneously plus the HTTP body from the frontend.

```
DISK (file tree / configs)
  └──────────────────────────────────────────────► Step 0

DISK (README + spec docs)
job["requirements_text"]
  └──────────────────────────────────────────────► Step 1

                            Step 0 [discovered_pages]
                            Step 1 [requirements[]]
                                   └──────────────► Step 2

                            Step 0 [project_type,
                                    frontend_framework,
                                    backend_framework,
                                    discovered_pages]
                            Step 1 [requirements[],
                                    project_summary]
                            Step 2 [requirements[]
                                    (descriptions only)]
                                   └──────────────► Step 3

                            Step 0 [10 context fields]
                            Step 1 [requirements[] (lookup),
                                    project_summary]
                            Step 2 [requirements[] (lookup),
                                    req_id set]
                            Step 3 [requirements[] where
                                    placement=="l1b"]
                            HTTP body [confirmed list,
                                       skipped flag]
                                   └──────────────► Step 3.5
```

Exact fields per edge:
- **Disk → Step 0:** file tree, config file contents (package.json, pom.xml, build.gradle, etc.)
- **Disk + job → Step 1:** README files (depth ≤ 2), keyword-matched spec docs (.md/.rst/.txt), `job["requirements_text"]`
- **Step 0 → Step 2:** `discovered_pages` only — used for ground-truth node inventory shown to LLM and `_identify_root_node()` input
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

### Step 4: Repo Parser
**Status: COMPLETE**
**Phase: FCom setup**
**Tools:** Python (zipfile, pathlib), Tree-sitter (0.25 QueryCursor API), json/yaml/toml
**Input:** Uploaded zip file + `step_3_5.project_context` (for `project_type`, `frontend_framework`, `backend_framework`, `service_layout`, `template_engine`, `server_routes_detected` — determines where to look for routes and models)
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

### Step 5: App Crawler — L2 Element Inventory
**Phase: FCom — builds L2 raw element inventory**
**Tools:** Playwright (dynamic), Tree-sitter (static fallback), Python
**Input:**
- `step_3_5.project_context` (`project_type`, `test_strategy`, `discovered_pages`) — crawl strategy selection
- Step 4 result: `frontend_routes` (crawl seed list), `important_files` (static fallback scope)

**Why no LLM summarisation here:**
L1a requirements already contain `path: PathEntity[]` — the ordered traversal specifying exactly which pages, elements, and edges each requirement asserts. Those path entities ARE the L2 specification. Step 5 does not re-invent named functions from raw elements (that is what Step 1 already did). Step 5 only collects what the running app actually has; Step 6 then matches L1a path entities against it.

**Two-pass process:**

1. **Dynamic pass (Playwright):** Boot the app. Visit each route from Step 4 `frontend_routes`. For each page, record:
   - Page title / primary heading
   - All visible interactive elements: inputs (type + label), buttons (text/label), links (text + href), selects, checkboxes, textareas
   - CSS selectors and `data-testid` attributes for each element
   - Outbound navigation links visible on the page
   - Network requests observed during page load (XHR/fetch) — API endpoints triggered passively
   - Whether the page was accessible or blocked (auth-gated, 404, redirect)

2. **Static fallback (Tree-sitter):** For routes Playwright could not visit (auth-gated, requires form preconditions), run Tree-sitter on the corresponding source files from Step 4 `important_files`. Extract: JSX component declarations, `<input>`, `<button>`, `<form>` elements, route-level API call sites (fetch/axios calls). Marked `discovered_by: "static_fallback"`.

**Output — stored at `job["step_results"]["step_5"]`:**
```json
{
  "pages": [
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
      "api_calls_observed": ["POST /api/auth/login"]
    }
  ],
  "unvisitable_routes": [
    { "route": "/dashboard", "reason": "auth_required", "discovered_by": "static_fallback" }
  ]
}
```

**Key value:**
- Playwright gives ground-truth of what is rendered and interactive at runtime — not just what is declared in source
- Static fallback prevents auth-gated pages from being entirely invisible
- Selectors feed Step 9 test generation, now organised per page/route (Step 9 looks up `/login` selectors for requirements whose path visits "Login Page")
- `api_calls_observed` cross-checks and supplements Step 4's static endpoint extraction

---

### Step 6: Requirement → L2/L3 Entity Mapper
**Phase: FCom — computes E() per requirement**
**Tools:** Python, LLM (AsyncAnthropic — fuzzy entity label matching only)
**Input:**
- `step_3_5.confirmed_requirements` (L1a, each with `path: PathEntity[]`)
- `step_3_5.advisory_requirements` (L1b, each with `path: PathEntity[]`)
- Step 5 result: per-page element inventory (`pages[]`, `unvisitable_routes[]`)
- Step 4 result: `api_endpoints`, `frontend_routes`

**Path entities as search specification, not scoring unit:**
L1a requirements carry `path: PathEntity[]` — the LLM's normative model of what the UI should contain. These entities guide Step 6's search (which page to inspect, what element type to look for) but are NOT the atomic scoring unit. Scoring at per-entity granularity is unreliable because entity labels from Step 1 ("email input") may not match Playwright-found labels ("Email address", "Username") — every fuzzy mismatch would inject noise into E(). Instead, E() is computed at requirement level from two clean signals.

**Two signals per requirement:**

**Signal 1 — L2 (UI presence):** Are this requirement's primary UI elements accessible on the expected page?

Step 6 uses `node` entities from `path[]` to identify which page to inspect in Step 5. It then uses `element` entities (filtered to `primary: true`) as a search spec: what element types are expected on that page? The LLM is called once per requirement, given the primary element entities and the Step 5 page's element list, and outputs a match for each entity (`matched_selector | null`). The L2 score is the fraction of primary element entities matched:

```
L2_score = matched_primary_elements / total_primary_element_entities
```

Page accessibility modifies this score:
- Page visited by Playwright (`accessible: true`) → full weight
- Page auth-gated (static fallback only) → all element matches discounted × 0.5 (declared but not runtime-verified)
- Page not found at all → L2_score = 0.0 regardless of element matching

Secondary entities (`primary: false`) contribute to L2 with weight (1 − α) = 0.3, primary with α = 0.7 — matching the formula in the Conceptual Model. The α weighting is applied at the L2 signal level, not at a per-entity E() level.

**Signal 2 — L3 (backend presence):** Does Step 4 have the endpoint this requirement's action implies?

For requirements that involve a backend mutation or retrieval (any requirement whose path includes an action edge or whose description implies create/read/update/delete): Step 6 searches Step 4 `api_endpoints` for an endpoint whose method + path matches the requirement's implied action. LLM is used for this inference (given the requirement description, the source page route, and the Step 4 endpoint list, which endpoint corresponds to this requirement's primary action?).

For requirements that are pure UI (navigation only, display only — no backend mutation implied): L3 signal = 1.0 by default (no backend handler required).

L3 score is binary: 1.0 (endpoint found) or 0.0 (no matching endpoint).

**E(requirement) from the two signals:**

| L2_score | L3_score | E() |
|---|---|---|
| High (≥ 0.7) | 1.0 | 1.0 |
| Low (< 0.7) | 1.0 | 0.5 (backend exists, UI incomplete or inaccessible) |
| High (≥ 0.7) | 0.0 | 0.4 (UI present, no backend handler) |
| Low (< 0.7) | 0.0 | 0.0 |

These map to the established E() scale from the Conceptual Model. The 0.7 threshold for "high" L2 is a model parameter — it means "most of the expected UI elements are present."

**Note on navigation edges:** Navigation `from → to` edges in path[] are not separately scored in Step 6. Their L2 evidence (outbound links in Step 5) is unreliable for programmatic navigation (React Router `history.push()` won't appear in `outbound_links`). Navigation correctness is verified in Step 11 (Playwright E2E test execution) rather than inferred from passive crawl link lists.

**Note on `api_calls_observed`:** Step 5's passive crawl only captures page-load GET requests. It does NOT capture POST/PUT/DELETE triggered by form submissions (Step 5 never fills forms). `api_calls_observed` is therefore not used for E() scoring — it is only used as a supplementary cross-check against Step 4's static endpoint list. The L3 signal comes entirely from Step 4.

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
      "l2_score": 1.0,
      "l3_score": 1.0,
      "l2_detail": {
        "matched_page": "/login",
        "page_accessible": true,
        "element_matches": [
          { "entity_label": "email input",    "matched_selector": "input[type='email']",    "primary": true  },
          { "entity_label": "password input", "matched_selector": "input[type='password']", "primary": true  },
          { "entity_label": "login button",   "matched_selector": "button[type='submit']",  "primary": true  }
        ],
        "unmatched_entities": []
      },
      "l3_detail": {
        "matched_endpoint": { "method": "POST", "path": "/api/auth/login", "handler": "login", "file": "routes/auth.py" }
      }
    }
  ],
  "unlinked_l2": [
    { "route": "/admin", "title": "Admin Panel", "note": "No L1a requirement's path[] node visits this route" }
  ],
  "unlinked_l3": [
    { "method": "DELETE", "path": "/api/users/:id", "handler": "delete_user", "file": "routes/users.py", "note": "No L1a requirement's L3 signal matched this endpoint" }
  ]
}
```

---

### Step 7: Functional Completeness + Appropriateness Scorer
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
        { "route": "/admin", "title": "Admin Panel", "note": "No L1a requirement's path[] visits this route" }
      ],
      "unlinked_endpoints": [
        { "method": "DELETE", "path": "/api/users/:id", "note": "No L1a requirement implies this endpoint" }
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
        {
          "req_id": "L1B-002",
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

### Step 7.5: Positive-Grounded FA Advisor
**Phase: FA advisory — post-codebase improvement suggestions**
**Status: NOT YET DESIGNED**
**Tools:** Python, LLM (AsyncAnthropic)
**Input:**
- Step 4 result: `api_endpoints`, `database_models`, `frontend_routes`, `languages` — what the codebase actually contains
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
| 4 — Inventory + Mapping + Completeness | Steps 5, 6, 7 | Not started |
| 5 — AC Generation + Test Execution | Steps 8, 9, 10, 11, 12 | Not started |
| 6 — Scoring + Dashboard | Steps 13, 14, 15, 16, 17 | Not started |
