# CLAUDE.md — Software Quality Evaluator

Read this file at the start of every session to get full context on the project.

---

## What this project is

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM explains results, never overrides them.

See `PLAN.md` for the full pipeline design, 4-layer model, and scoring formulas.

---

## What has been built

### Step 0 — Project Type & Scope Classifier (COMPLETE)
- User uploads a `.zip` of their project + requirements text via the React frontend
- Backend saves the zip, creates a job (JSON file), runs Step 0 in the background
- Rule-based first (config files + extension counts); LLM (claude-haiku, prompt caching) called only when confidence is medium or rules produce no match
- `test_strategy` always formula-derived from `project_type` + `backend_framework` — LLM never overrides it
- Root-level Python check: Python configs only found in sub-service directories (depth 2+) are ignored for framework detection — triggers LLM fallback to handle multi-service apps correctly
- SSR detection: Flask/Django/Express/PHP backends with a `templates/` or `views/` directory are classified as `full_stack_web_app` (not `backend_api_only`). Engine-specific template extensions (`.ejs`, `.twig`, `.blade.php`, `.pug`, `.hbs`, `.njk`, `.jinja2`) are treated as unambiguous SSR signals regardless of directory.
- Java full-stack (JS + Java): React/Angular/Vue + recognised Java framework (Spring Boot, Quarkus, Micronaut) with a `pom.xml` or `build.gradle` → `full_stack_web_app` at `high` confidence without LLM.
- Java full-stack (SSR): Spring Boot + `build.gradle.kts` + HTML templates in `src/main/resources/templates/` → `full_stack_web_app` at `high` confidence, `template_engine = "Thymeleaf"`. Deterministic — no LLM fallback. `build.gradle.kts` is now in CONFIG_FILES so Gradle Kotlin DSL projects are read.
- Mobile apps: React Native and Expo classified as `mobile_app` (not `frontend_only`).
- Production deps: `backend_fw_js` detection uses only `dependencies` (not `devDependencies`) — prevents Express used as a dev mock server from misclassifying the project as `backend_api_only`.
- IGNORE_DIRS extended: `examples`, `demo`, `sample`, `demos`, `samples` excluded from walk to prevent example build files in library repos from affecting classification.
- Static site: rule-based `static_site` detection — HTML files present, no backend language → `medium` confidence without LLM.
- React confidence: if `react` is in deps but no `.jsx`/`.tsx` source files exist, confidence is `medium` → LLM review.
- Tests: `backend/tests/test_step0_classifier.py` — 12 fixtures, all passing.
- Audit doc: `docs/step0-edge-case-audit.md` — full 20-case analysis.

**Step 0 output fields** (stored in `step_results.step_0`):
```
project_type, frontend_framework, frontend_tooling, backend_framework,
template_engine, service_layout, server_routes_detected,
confidence, reasoning, test_strategy,
config_files_found, llm_used, llm_model, discovered_pages
runtime  (only for electron_app)
```
`primary_language` is NOT in Step 0 output — Step 4 produces the authoritative `languages` array from source parsing.

**New fields added in 20-case audit:**
- `frontend_tooling` — build tool: `"Vite"`, `"Create React App"`, `"Webpack"`, `"Parcel"`, etc.
- `template_engine` — SSR engine: `"Thymeleaf"`, `"Jinja2"`, `"Blade"`, `"EJS"`, etc.
- `service_layout` — `"single_project"` | `"separate_frontend_backend"` | `"monorepo"` | `"single_project_ssr"` | `"unknown"`
- `server_routes_detected` — `true` when Next.js/Nuxt/SvelteKit/Remix API route dirs are found
- `runtime` — only for `electron_app`: `"Electron"`

### Step 1 — Stated Requirement Extractor (COMPLETE)
- Scans uploaded zip for README files (capped at depth ≤ 2) and spec docs (keyword-matched .md/.rst/.txt)
- Ignores tool config dirs: `.claude`, `.cursor`, `.github`, `.vscode`, `.idea` (these waste slots)
- MAX_DOCS = 30, MAX_CHARS_PER_DOC = 12000
- LLM (claude-haiku) extracts stated requirements as **graph entities** — nodes, edges, or elements within nodes (not capability statements). Also extracts a `project_summary` (2–3 sentence domain/purpose description) in the same call. Every requirement must include a verbatim source quote.
- Source quote verification uses whitespace-normalized comparison (`_norm()`) — collapses all whitespace to single space before substring check, so LLM quote normalization (newlines → spaces) doesn't cause false drops
- JSON truncation recovery: if response is cut off mid-array, recovers items up to last complete `},`
- `excluded_docs_count` in result shows how many spec docs were found but dropped (MAX_DOCS hit)
- `functional_area` field on each requirement for cascade advisory grouping
- **Entity taxonomy:** `type` = `"node"` (a page/screen) | `"edge"` (stated navigation path) | `"element"` (control/feature within a page). `ui_node` = the page this entity belongs to (for nodes: itself; for elements: containing page; for edges: destination page).
- **Page-identity rule:** Named entities do NOT require `.html` filenames — "the contacts page shows..." is extractable even if no .html file is named.
- **Behavioural decomposition rule:** Automatic behaviours that only make sense because the user can change a value → extract the element that enables it. "Rows with done status sink to the bottom" → element: status-change control on [task list page]. The automatic behaviour sentence is the source_quote.
- **X-axis only:** Capabilities ("user can log in") and behavioral properties (validation, redirects, persistence) are Y-axis items — never extracted. The entity is the extractable unit, not the capability it enables.
- **Extraction gate (positive framing):** Before extracting any item, the LLM tests: "Does the source text name a specific UI entity and describe what it IS or provides?" Rejects: automatic behaviors (hashing, redirecting, validating, sorting), backend subjects (app.py, server.py, database), reactions ("System must X when/if Y"), behavioral properties of existing entities, and quality attributes (responsive, accessible, performant, secure) — none of these name a UI entity. This replaces a growing negative "what to skip" list, which LLMs ignore when their training priors are strong.
- **`project_summary`** passed to Step 3 so INF-C/INF-D domain inference is purpose-aware (e.g. "task manager" → overdue tracking, completion %, progress view) rather than purely structural pattern matching.

### Step 2 — Obvious Requirement Generator (COMPLETE)
- LLM finds graph connectivity gaps — pages that cannot be reached or cannot be left
- `discovered_pages` from Step 0 passed to LLM as ground-truth node inventory (codebase files)
- **Prompt design (3-check deterministic):** (1) build node list from stated + discovered pages, (2) entry paths per node — is there a stated inbound navigation element? (3) exit paths per node — is there a stated way to leave it? (mechanism-agnostic). Hard stops: auth guards, invocation controls for stated capabilities, observable outcomes, error messages, anything phrased "System must X when Y".
- **`depends_on` field:** lists the REQ-XXX ids from stated requirements that make each obvious requirement necessary.
- **Parser:** handles LLM YES/NO reasoning text before JSON array via bracket_pos search.
- **`_build_user_message`:** stated requirements formatted with `[req_id]` prefix for `depends_on` linkage.
- **Code-level enforcement:** `_validate_and_normalise` drops any item whose `reasoning` does not start with "CHECK 2" or "CHECK 3" — guards against LLM hallucinating CHECK 4/5 labels despite prompt instructions.
- **Root node detection (`_identify_root_node()`):** Detects the home/root page before building the user message to prevent phantom entry navigation. Two heuristics: (1) only one `type=node` requirement → that page is root; (2) `discovered_pages = ["index.html"]` (single-route SPA) with at least one node req → first node is root. Detected root is injected as an explicit `=== ROOT / HOME PAGE ===` section instructing the LLM to skip CHECK 2 for it and not invent a phantom landing page to navigate from.

### Step 3 — Generated Requirement Generator (COMPLETE)
- LLM generates both L1a candidates (confidence ≥ 0.80) and L1b advisory items (< 0.80)
- **5 categories + structural edges:**
  - SOP-A: pattern-triggered new nodes — three trigger types: (1) feature keywords (auth → profile; offline → offline records; multi-user → user identity; sync → sync status); (2) data structure patterns (temporal field → time-scoped browsing page ~0.75–0.85; collection-status/category field → cross-status overview page ~0.70–0.82; parent-child/many-to-many relationship → grouping page ~0.65–0.80); (3) lifecycle patterns (mutable records → audit/history page ~0.50–0.65; user-configurable preferences → settings page ~0.70–0.85; time-sensitive deadlines/thresholds → notification surface ~0.55–0.75)
  - SOP-B: rule-triggered elements within existing **stated** nodes only (`type=node` from Step 1). Does NOT fire for Step 1 elements (`type=element`) — they are sub-components, not pages. Does NOT fire for nodes generated in SOP-A/INF-C in the same pass — those get structural_edge only. Rules: list node → filter ~0.82, search ~0.80, sort ~0.68, pagination ~0.50–0.75, edit item ~0.72, delete item ~0.65; detail node → edit ~0.75, delete ~0.70; dashboard node → date-range filter ~0.65, export ~0.50; status-field node (named changeable status, OR page named "overview"/"summary"/"report" aggregating items with status) → filter-by-status ~0.82, bulk-update ~0.45.
  - INF-C: domain-knowledge new nodes — reads `project_summary` to understand the app's domain and purpose, then asks what a regular user would return to repeatedly that stated pages and SOP patterns don't provide; no fixed checklist — pure open-ended domain reasoning
  - INF-D: contextual elements within existing nodes (domain-specific, not covered by SOP-B). Positive framing: "Is this something a user taps, reads, or fills in?" — YES → include; NO (system response/feedback/side-effect) → it's an AC, discard. **Action-page heuristic:** pages whose name starts with a verb ("Take X", "Add X", "Record X", "Submit X", "Create X", "Edit X") → always consider input fields: does the action have a subject/person (→ selector/picker), a date or time (→ date/time picker), a quantity or reference ID (→ number/text input)? Generate these as INF-D elements.
  - INF-E: missing edges between existing nodes (cross-links and shortcuts beyond Step 2 minimum)
  - structural_edge: entry/exit edges for new nodes generated in SOP-A/INF-C — `l1_recommendation` inherits from parent node (l1b parent → l1b structural edge, not l1a)
- **Generation gate (positive framing):** Before including any item, the LLM tests: "Can a user independently navigate to this, or directly invoke it (click, tap, fill, select) as a standalone UI entity that exists regardless of what the user just did?" YES → include. NO → discard (Y-axis AC). Items that only appear as a consequence of another action, describe HOW something works, or express a quality property have no dedicated UI home. This replaces the former NEVER GENERATE negative list, which LLMs circumvent when their training priors are strong.
- **Root node detection (`_identify_root_node()`):** Same logic as Step 2 — detects the home/root page and injects a ROOT/HOME PAGE section into the Step 3 user message. Guards against INF-C fabricating a phantom home/landing page above the SPA root, and INF-E generating navigation to the root from a page that doesn't exist.
- **Confidence → placement:** ≥ 0.80 → l1a; 0.60–0.79 → l1b strongly_implied; 0.40–0.59 → l1b medium; < 0.40 → l1b weak
- **Result envelope fields:** `requirements`, `total_count`, `sop_count`, `inference_count`, `llm_model`, `dropped_count`, `error`
- **Frontend:** `GeneratedRequirementsResult.tsx` — L1a panel (green, ≥ 80% confidence) and L1b panel (yellow advisory), category badges (blue=rule, purple=inferred, gray=nav-gap), expandable rows show reasoning + confidence_reason + depends_on

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- Upload page: drag-and-drop zip + requirements textarea, file size display, validation
- Results: ClassificationResult (Step 0), RequirementsResult (Step 1), ObviousRequirementsResult (Step 2), GeneratedRequirementsResult (Step 3)
- Each requirement row expands to show source quote / reasoning + functional_area badge
- Job list endpoint `GET /api/jobs` lets you find the latest job_id without copying from the frontend

### Backend infrastructure (COMPLETE)
- Python 3.12 + FastAPI
- `POST /api/upload` — validates zip + requirements, creates job, starts background pipeline
- `GET /api/jobs/{job_id}` — returns job JSON
- `GET /api/jobs` — lists recent jobs (most-recent-first, default limit 10)
- Job store: one JSON file per job in `./jobs/{job_id}.json`
- Uploads stored in `./uploads/{job_id}/project.zip`
- Pipeline runs Steps 0 → 1 → 2 → 3 as async background task; status tracked in job JSON (`step_3_complete`)

---

### Step 3.5 — Human Requirement Confirmation (COMPLETE)
- Pipeline pauses at `waiting_for_confirmation` after Step 3; resumes when user POSTs to confirm endpoint
- `POST /api/jobs/{job_id}/confirm` — validates job state, stores locked L1a as `step_results.step_3_5`, sets status to `confirmed`
- Frontend `ConfirmationTable.tsx` — three-section review table:
  - **Section 1 (L1a)**: stated + obvious pre-included; Step 3 l1a candidates pre-included but demotable. Priority dropdown updates weight live.
  - **Section 2 (L1b Advisory)**: Step 3 l1b items, each promotable to L1a
  - **Section 3**: inline add-requirement form → `CUSTOM-001` IDs
- Action bar: **Skip** (stated + obvious only, `skipped=true`) and **Confirm (N in score)**
- `step_3_5` result stored in job JSON: `confirmed_requirements`, `confirmed_at`, `skipped`, `l1a_count`, `promoted_count`, `deleted_count`, `added_count`
- ResultPage shows a green summary banner with counts after confirmation

## What has NOT been built yet

- Steps 4–17 (see PLAN.md for full pipeline)
- Docker sandbox (Step 11)

---

## Project structure

```
c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\
  backend/
    main.py                          # FastAPI entry point (port 8000)
    .env                             # ANTHROPIC_API_KEY, UPLOAD_DIR, JOBS_DIR (not committed)
    .env.example                     # Template
    requirements.txt
    api/
      routes/
        upload.py                    # POST /api/upload
        jobs.py                      # GET /api/jobs, GET /api/jobs/{job_id}
    pipeline/
      step0_classifier.py            # Project type + framework classifier
      step1_req_extractor.py         # Stated requirement extractor
      step2_obvious_generator.py     # Obvious requirement generator
      step3_implied_generator.py     # 5-category confidence-scored generator
    storage/
      job_store.py                   # JSON file job persistence + list_jobs()
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob()
      types/index.ts                 # Job, Step0Result, Step1Result, Step2Result, etc.
      pages/UploadPage.tsx           # Upload form
      components/
        ClassificationResult.tsx     # Step 0 result display
        RequirementsResult.tsx       # Step 1 result display
        ObviousRequirementsResult.tsx # Step 2 result display
        GeneratedRequirementsResult.tsx # Step 3 result display (L1a/L1b panels)
        ConfirmationTable.tsx        # Step 3.5 review/edit table (promote/demote/add/delete)
      App.tsx                        # Stage state machine
  uploads/                           # Runtime — gitignored
  jobs/                              # Runtime — gitignored
  docs/
    step0-edge-case-audit.md         # 20-case classifier audit
  PLAN.md
  CLAUDE.md
```

---

## How to run locally

### Backend (port 8000)
```bash
cd c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\backend
venv\Scripts\activate          # Python 3.12 venv
uvicorn main:app --reload
```

### Frontend (port 5173)
```bash
cd c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\frontend
npm run dev
```

**npm SSL issue (corporate proxy):** If `npm install` fails with `SELF_SIGNED_CERT_IN_CHAIN`, run:
```bash
npm config set strict-ssl false
npm install
```
Or copy `package-lock.json` from another machine where install succeeded — npm will use it without re-hitting the registry.

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

---

## Key technical decisions

- **AsyncAnthropic** with `cache_control: ephemeral` on system prompt — keeps classification fast and cheap
- **JSON files per job** in `./jobs/` — no database for MVP; easy to inspect and debug
- **Async background task** (FastAPI `BackgroundTasks`) — upload returns immediately with `job_id`, frontend polls
- **Python 3.12 required** — Python 3.14 (pre-release) causes pydantic-core Rust compilation failure on install
- **Formula-driven scores** — LLM never overrides the formula
- **Root-level Python check** — `root_level_py` in Step 0 prevents sub-service requirements.txt (depth 2+) from falsely determining backend_framework
- **SSR detection (`_has_html_views`)** — Step 0 checks for `templates/`/`views/` HTML files and engine-specific extensions (`.ejs`, `.twig`, `.blade.php`, etc.) to distinguish Flask/Django/Express SSR apps from pure REST APIs. Without this, all Python/JS/PHP backends without a JS frontend framework were misclassified as `backend_api_only`, producing wrong Step 2 obvious requirements.
- **Java full-stack rule** — `frontend_fw + java_fw` (detected from `pom.xml`/`build.gradle`/`build.gradle.kts`) classifies as `full_stack_web_app` at `high` confidence before the generic `monorepo` check. Ensures Spring Boot + React/Angular/Vue is always classified deterministically.
- **Java SSR rule** — `java_fw + _has_html_views()` bypasses the `return None` early guard so Spring Boot + Thymeleaf is classified deterministically at `high` confidence without LLM. `build.gradle.kts` added to CONFIG_FILES so Gradle Kotlin DSL is readable.
- **Production deps for backend detection** — `backend_fw_js` uses `js_deps_prod` (production `dependencies` only) not `js_deps_merged`, preventing Express/NestJS in `devDependencies` (mock servers, test utilities) from misclassifying a React SPA as a full-stack app.
- **Mobile detection** — React Native / Expo detected before the `frontend_only` branch and classified as `mobile_app` with Jest primary.
- **Static site rule** — HTML files present, no backend language extensions → `static_site` at `medium` confidence. No LLM needed for plain HTML/CSS/JS sites.
- **React source validation** — if `react` is in deps but no `.jsx`/`.tsx` files exist in file_tree → `medium` confidence → LLM review (avoids false high-confidence React claims from peer-dep contamination).
- **New deterministic fields** — `frontend_tooling`, `template_engine`, `service_layout`, `server_routes_detected` computed by pure helpers from the file tree and config contents. Populated for both rule-based and LLM results. See `docs/step0-edge-case-audit.md`.
- **Test strategy primary/secondary** — for `backend_api_only`, primary is always the HTTP-level test tool (Pytest API tests / Jest/Supertest / JUnit/MockMvc / PHPUnit / RSpec), not a unit test runner. Unit tests are never the right primary for verifying user-facing API requirements. Secondary is `null` for API-only (deduped away) and the backend test tool for full-stack apps (Playwright primary + backend tool secondary).
- **Step 1 truncation recovery** — `_parse_llm_response` recovers requirements from truncated JSON responses rather than failing with 0 results

---

## Git workflow

PAT stored via git credential store. To push:
```bash
cd c:\Users\Owner\OneDrive\Documents\GitHub\DSTA
git add <files>
git commit -m "describe what you did"
git push origin main
```

**Required before every commit (no exceptions):**
- Did the design, formulas, or output schemas change? → Update `PLAN.md`
- Were new steps built, bugs fixed, paths changed, or working instructions revised? → Update `CLAUDE.md`

Both files must be in the same commit as the code — not a follow-up commit. This is how context persists across devices and sessions. The local `~/.claude/projects/*/memory/` directory is machine-local only — do not rely on it for cross-session rules.

---

## Next steps

1. Build Step 4 — Repo Parser (outputs `languages`, `api_endpoints`, `database_models`)

---

## Known limitations / future scope

### Microservices
The evaluator is designed for **self-contained applications with user-facing flows**. Microservices architectures are out of scope for the MVP for two reasons:
1. Individual services are rarely self-contained enough to evaluate against user-story-level requirements — most are internally-facing and flows span multiple services
2. Steps 5 (L2 Inventory), 9 (Test Generator), and 11 (Sandbox) assume one running app with one base URL and a UI to crawl

**Future implementation:** Microservices support is a post-MVP in-place extension — do not clone the repo. The branch point is `project_type == "microservices"` from Step 0's job JSON, which already flows through the pipeline. Steps 5, 9, and 11 will need a microservices implementation path. To keep this retrofit additive (not a rewrite), ensure the **output schemas** of Steps 5, 9, and 11 remain stable and Playwright-specific logic does not leak into downstream step inputs.
