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
- SPA frontend suppresses SSR detection: When a SPA frontend (React, Vue, Angular, Svelte, Preact, SolidJS, Qwik, Alpine.js, Ember, Lit, React Native, Expo) is detected, `template_engine` is forced to `null` regardless of what `_detect_template_engine` finds — the SPA renders client-side, so a Thymeleaf dep in `pom.xml` or HTML files in `templates/` are not the rendering layer. Meta-frameworks that do SSR (Next.js, Nuxt, SvelteKit, Remix, Gatsby) are excluded from this override. `_SPA_FRAMEWORKS` constant controls the list.
- Service layout flex matching: `_detect_service_layout` now handles dir names with spaces/hyphens/underscores (e.g. "frontend src" matches the "frontend" keyword). Also: a SPA frontend in a frontend-named subdir alongside a non-frontend backend (e.g. Spring Boot in `src/main/java/`) returns `"separate_frontend_backend"` — catches the Spring Boot + React Vite in one repo pattern.
- Java full-stack (JS + Java): React/Angular/Vue + recognised Java framework (Spring Boot, Quarkus, Micronaut) with a `pom.xml` or `build.gradle` → `full_stack_web_app` at `high` confidence without LLM.
- Java full-stack (SSR): Spring Boot + `build.gradle.kts` + HTML templates in `src/main/resources/templates/` → `full_stack_web_app` at `high` confidence, `template_engine = "Thymeleaf"`. Deterministic — no LLM fallback. `build.gradle.kts` is now in CONFIG_FILES so Gradle Kotlin DSL projects are read. Note: only fires when no SPA frontend is detected (SPA suppression takes priority).
- Mobile apps: React Native and Expo classified as `mobile_app` (not `frontend_only`).
- Production deps: `backend_fw_js` detection uses only `dependencies` (not `devDependencies`) — prevents Express used as a dev mock server from misclassifying the project as `backend_api_only`.
- IGNORE_DIRS extended: `examples`, `demo`, `sample`, `demos`, `samples` excluded from walk to prevent example build files in library repos from affecting classification.
- Static site: rule-based `static_site` detection — HTML files present, no backend language → `medium` confidence without LLM.
- React confidence: if `react` is in deps but no `.jsx`/`.tsx` source files exist, confidence is `medium` → LLM review.
- `_discover_pages()` finds page/screen filenames from the file tree: HTML files in `templates/`/`views/`; HTML at root/static dirs; `.tsx/.jsx/.vue/.svelte` in `pages/`/`screens/`; SSR template engine files (`.blade.php`, `.erb`, `.cshtml`, `.ejs`, etc.) in `views/`/`templates/` via `_TEMPLATE_ENGINE_EXTS`; Android `*Activity.java`/`*Activity.kt` files. Result stored in `discovered_pages`.
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
- LLM (claude-haiku) extracts stated requirements as **functions** — "User can [action]" active voice. Also extracts `project_summary` (2–3 sentence domain/purpose description) in the same call. Every function must include a verbatim source quote.
- **Function+path model:** Each function includes `path: PathEntity[]` — ordered UI entities traversed to complete the goal. PathEntity: `{type: "node"|"element"|"edge", label, primary: boolean, ui_node?, from?, to?}`. `primary: true` = entity fundamentally asserted by this function (scored if absent); `primary: false` = context already asserted by another function.
- **Vague flag:** Source text too broad to build a specific path (e.g. "users can manage tasks") → `vague: true`, minimal single-node path. Step 3 decomposes via `unpacks` targeting. Vague functions never enter FCom scoring.
- **State-variant nodes** (labels with parentheticals like "(filtered)", "(sorted)") always `primary: false` — UI state, not navigable routes; Step 6 skips L2 route matching for them.
- **Extraction gate (positive framing):** "Does this text describe a goal a user can directly perform?" Rejects: backend subjects, quality attributes, automatic behaviors, system reactions ("X happens when/if Y"). Positive gate replaces growing negative lists.
- **Screenshot pages:** Markdown `### Page Name` headings immediately followed by a screenshot image (`![...](...)`) are extracted as vague functions ("User can access [Page Name]", `vague: true`). This handles README screenshot galleries where pages are documented without action verbs.
- Source quote verification uses whitespace-normalized comparison (`_norm()`) — collapses all whitespace to single space; newlines → spaces tolerated
- JSON truncation recovery: if response is cut off mid-array, recovers items up to last complete `},`
- `excluded_docs_count` in result shows how many spec docs were found but dropped (MAX_DOCS hit)
- `functional_area` field on each function for cascade advisory grouping
- **`project_summary`** passed to Step 3 so INF domain inference is purpose-aware

### Step 2 — Obvious Requirement Generator (COMPLETE)
- LLM finds graph connectivity gaps — pages that cannot be reached or cannot be left
- `discovered_pages` from Step 0 passed to LLM as ground-truth node inventory (codebase files)
- **Path-aware node extraction:** `_extract_nodes_from_paths()` parses node inventory from Step 1 function path arrays (state-variant labels excluded via `_is_state_variant()`). Step 2 no longer reads a flat `type=node` field — it parses path arrays.
- **Output format:** navigation functions with `path: PathEntity[]`. CHECK 2 → edge `{primary: true, from: null}` + destination node `{primary: false}`. CHECK 3 → source node `{primary: false}` + exit edge `{primary: true, to: null}`.
- **`depends_on` field:** lists the REQ-XXX ids from stated functions that make each obvious function necessary.
- **Parser:** handles LLM YES/NO reasoning text before JSON array via bracket_pos search.
- **`_build_user_message`:** stated functions formatted with `[req_id]` prefix for `depends_on` linkage; node inventory and edge inventory provided explicitly.
- **Code-level enforcement:** `_validate_and_normalise` drops any item whose `reasoning` does not start with "CHECK 2" or "CHECK 3"; validates path arrays; defaults edge entities to `primary: true`. Also enforces null source/destination: CHECK 2 edges always get `from=null`; CHECK 3 edges always get `to=null`; description is rebuilt from the path so the LLM cannot invent a specific source or destination page.
- **Root node detection (`_identify_root_node()`):** Detects the home/root page by parsing nodes from Step 1 path arrays. Two heuristics: (1) only one stated node in all paths → root; (2) `discovered_pages = ["index.html"]` (single-route SPA) + at least one stated node → first node is root. Detected root injected as `=== ROOT / HOME PAGE ===` — LLM skips CHECK 2 for it.

### Step 3 — Generated Requirement Generator (COMPLETE)
- LLM generates both L1a candidates (confidence ≥ 0.80) and L1b advisory items (< 0.80)
- **Two-pass generation — each output is a complete function with traversal path:**
  - **Pass 1 — SOP pattern-triggered (`category: "sop"`):** Fires on nodes from Step 1 stated functions. Pattern table: list node → filter ~0.82, search ~0.80, sort ~0.68, edit item ~0.85 (L1a), delete item ~0.82 (L1a); detail node → edit ~0.85 (L1a), delete ~0.82 (L1a); CRUD COMPLETION RULE — when CREATE is stated for an entity, edit + delete always L1a; auth present → account management / profile ~0.87; named changeable status → cross-status overview ~0.75, filter-by-status ~0.82; temporal field → time-scoped view ~0.75; mutable records → audit/history ~0.60; user preferences → settings ~0.82; time-sensitive deadlines → notification surface ~0.65; multi-user data → user profile ~0.82. Vague Step 1 functions (`vague: true`) are priority unpack targets — all applicable patterns fire with `unpacks: "<parent_req_id>"`.
  - **Pass 2 — INF domain inference (`category: "inf"`):** Reads `project_summary` + all stated functions. Grounding step first: understand this app's purpose, what it manages, and how it works before generating — only generate functions consistent with its actual structure. Then generates across 7 domain-completeness angles: (1) recurring use, (2) workflow completeness / onboarding, (3) data management (export/import/bulk/archive), (4) domain standards (exhaustive — what a comparable app always has), (5) discoverability + help, (6) user control (settings/preferences), (7) overview/insight. Bold — generates at 0.50–0.70; breadth over silence to drive FA scoring. Never re-generates Step 1, Step 2, or Pass 1 SOP functions.
- **Path construction:** Every generated function has a complete `path[]` with entry edge, body entities, and exit edge baked in. No `structural_edge` category — entry/exit are part of the function's path. State-variant nodes always `primary: false`.
- **Root node detection (`_identify_root_node()`):** Parses nodes from Step 1 path arrays; injects `=== ROOT / HOME PAGE ===` section to prevent phantom landing page generation.
- **Confidence → placement:** ≥ 0.80 → `placement: "l1a"`; 0.60–0.79 → `placement: "l1b"` strength: `strongly_implied`; 0.40–0.59 → `l1b` strength: `medium`; < 0.40 → `l1b` strength: `weak`
- **`unpacks` field:** Links Step 3 children to their vague Step 1 parent (`"REQ-xxx"` or `null`). Step 3.5 auto-includes unpacking children and excludes the vague parent.
- **`depends_on` field:** REQ-xxx IDs only (Step 1 stated functions). OBV-xxx (Step 2 navigation gaps) are not valid targets — a domain enhancement depends on a domain feature, not on navigation plumbing. Validated in `_validate_and_normalise` against `valid_step1_ids`.
- **Result envelope fields:** `requirements`, `total_count`, `sop_count`, `inference_count`, `llm_model`, `dropped_count`, `error`
- **Frontend:** `GeneratedRequirementsResult.tsx` — L1a panel (green, ≥ 80%) and L1b panel (yellow advisory), category badges (blue=Pattern, purple=Inferred), expandable rows show traversal path (PathDisplay) + reasoning + confidence_reason + unpacks badge + depends_on

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- Upload page: drag-and-drop zip + requirements textarea, file size display, validation
- Results: ClassificationResult (Step 0), RequirementsResult (Step 1), ObviousRequirementsResult (Step 2), GeneratedRequirementsResult (Step 3)
- **PathDisplay component (`PathDisplay.tsx`):** Shared component rendering traversal path arrays as type-coded badges with › separators. node=sky, element=violet, edge=amber. Secondary entities (primary=false) rendered at 40% opacity. Each entity shows its label; edges show `from → to`; elements show `ui_node`.
- Each function row expands to show traversal path (PathDisplay), reasoning, confidence, source quote. Vague badge shown inline for `vague: true` functions.
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

### Step 3.5 — Human Requirement Confirmation + Data Consolidation (COMPLETE)
- Pipeline pauses at `waiting_for_confirmation` after Step 3; resumes when user POSTs to confirm endpoint
- `POST /api/jobs/{job_id}/confirm` — validates job state, writes consolidated result to `step_results.step_3_5`, sets status to `confirmed`
- **This is the single consolidation point for all downstream steps.** Steps 4+ read only from `step_3_5` for all milestone-1 data.
- `ConfirmedRequirement` Pydantic model: `path: list[PathEntity]`, `vague: bool`, `unpacks: str | None`, `depends_on: list[str]`, `source_quote: str | None`. `depends_on` and `source_quote` are looked up server-side from prior step results by `req_id` — frontend does not pass them.
- Frontend `ConfirmationTable.tsx` — three-section review table:
  - **Section 1 (L1a)**: stated (non-vague) + obvious pre-included; Step 3 `placement: "l1a"` candidates pre-included but demotable. Expandable popdown shows PathDisplay + reasoning. Priority dropdown updates weight live.
  - **Section 2 (L1b Advisory)**: Step 3 `placement: "l1b"` items, each promotable to L1a. Expandable popdown shows PathDisplay + reasoning.
  - **Section 3**: inline add-function form → `CUSTOM-001` IDs; placeholder path: `[{type: "node", label: "TBD", primary: true}]`
- **Vague auto-replace:** Vague Step 1 functions excluded from initial L1a state. ALL Step 3 functions with `unpacks` pointing to a vague parent are auto-included in L1a — both `placement: "l1a"` and `placement: "l1b"` children — so the user can review and demote. Each such row gets a `vague child` badge (orange). L1b items promoted this way are excluded from the advisory section. UI notice: "N vague stated function(s) were auto-replaced by their Step 3 children — all children shown in L1a for review."
- Action bar: **Skip** (stated non-vague + obvious only, `skipped=true`) and **Confirm (N in score)**
- `step_3_5` result fields:
  - `confirmed_requirements` — locked L1a list (REQ/OBV/GEN/CUSTOM items), each with full `path[]`, `depends_on`, `source_quote`
  - `advisory_requirements` — Step 3 l1b items not promoted, copied as-is with full `path[]`, `strength`, `weight`, `confidence_score`
  - `project_context` — Step 0 passthrough: `project_type`, `frontend_framework`, `frontend_tooling`, `backend_framework`, `template_engine`, `service_layout`, `server_routes_detected`, `discovered_pages`, `test_strategy`, `runtime`
  - `project_summary` — Step 1 domain summary string
  - `confirmed_at`, `skipped`, `l1a_count`, `promoted_count`, `deleted_count`, `added_count`
- ResultPage shows a green summary banner with counts after confirmation

### Step 4 — Repo Parser (COMPLETE)
- Triggered automatically after Step 3.5 confirmation as a FastAPI `BackgroundTasks` task
- No LLM — pure Tree-sitter AST parsing (`tree-sitter>=0.22`, `QueryCursor` API from 0.25)
- Reads `step_3_5.project_context` for framework dispatch (`backend_framework`, `frontend_framework`)
- **Endpoint extraction:**
  - Flask/FastAPI: tree-sitter Python query on `decorated_definition` nodes; regex on decorator text for path + method
  - Django: regex on `urls.py` files for `path(...)` calls
  - Spring Boot: tree-sitter Java queries for class-level `@RequestMapping` (base path) + method-level `@GetMapping` etc.; concatenated path; Kotlin fallback via regex
  - Express/NestJS: regex on `.js/.ts` files for `app.get(...)` / `@Get(...)` patterns
- **Route extraction + file mapping (single pass):** `_build_route_to_files` is the single source of truth — discovers routes AND maps them to files in one function. `frontend_routes` is derived as `sorted(route_to_files.keys())` enriched with `{path, dynamic, params[]}` metadata via `_route_entry()`. Priority order: Next.js pages/ → Next.js app/ → SvelteKit → React Router JSX + createBrowserRouter → Vue/Angular Router (mapped to router config file) → SSR endpoint fallback → static HTML fallback.
- **`route_to_files`:** maps each frontend route → source file(s). Each route's list includes the page component plus its 1-level-deep local imports via `_expand_with_shallow_imports` — internal to Step 4; consumed by `_extract_route_elements` and `_extract_navigation_graph`. Not passed to Step 5.
- **`route_elements`:** L3 element inventory — `{route: [{type, subtype, label}, ...]}` parsed from each route's source files via regex on JSX/HTML. Extracted by `_extract_route_elements(route_to_files, root)`. Authoritative L3 signal for element E() scoring when Step 5 Playwright cannot visit a route (E()=0.5 fallback).
- **`navigation_graph`:** L3 navigation graph — `{route: [target_routes...]}` parsed from navigation triggers (`<Link to>`, `<a href>`, `navigate()`, `router.push()`, `history.push()`) in each route's source files. Extracted by `_extract_navigation_graph(route_to_files, root)`. L3 signal for navigation edge E() scoring.
- **`implementation_units`:** unified list of backend handlers — wraps all `api_endpoints` as `kind: "api_endpoint"` plus HTML `<form method="POST/PUT/DELETE">` tags in SSR template files as `kind: "form_handler"`. Authoritative L3 signal for Step 6 data edge E() scoring. Step 6 unlinked detection uses `[u for u in implementation_units if u["kind"] == "api_endpoint"]`.
- **Model extraction:** SQLAlchemy/Django (`class X(Base):`), JPA (`@Entity`), TypeORM (`@Entity()`), Mongoose (`new Schema(...)`), Prisma (`.prisma` regex)
- **Test file detection:** glob patterns (`test_*.py`, `*.test.ts`, `*Test.java`, etc.)
- **Important files:** entry-point names + endpoint files + router/model configs + frontend page/component/service files + config files + Java layer classes — capped at 100
- Job statuses: `confirmed` → `step_4_running` → `step_4_complete` (or `step_4_error`)
- Frontend polls for `step_4_complete` after confirmation; `RepoParserResult.tsx` shows loading skeleton then populated result

**Step 4 output fields** (stored in `step_results.step_4`):
```
// L3 scoring inputs (Step 6 E() formula)
frontend_routes (list[{path, dynamic, params[]}]),
implementation_units (kind/method/path/file/handler — api_endpoint + form_handler),
route_elements (route → [{type, subtype, label}, ...]),  // L3 element inventory
navigation_graph (route → [target_routes...]),           // L3 navigation graph
// Internal Step 4 use (not consumed by Step 5)
route_to_files (route → [file, ...]), important_files,
// Context / reporting (Step 7.5 advisor, Steps 15/16 evidence pack)
database_models, existing_tests, languages,
total_endpoints, total_routes, error
```

### Step 5 — App Crawler (COMPLETE)
- Triggered automatically after Step 4 completes (chained in `_run_step4` background task)
- No LLM — Playwright live crawl only; L3 element inventory is owned by Step 4 (`route_elements`)
- Bootstrap heuristic from `step_3_5.project_context`: `project_type` + `frontend_framework` + `frontend_tooling` + `service_layout` determine the start command and port
- Uses ports that avoid collision with DSTA's own services (8000, 5173): Vite→5174, CRA→3000, backend→8001, Flask→5001, Express→3001, static→8082
- Port poll: `httpx.AsyncClient` GET every 1.5s, 30s timeout; falls back to full static mode if app doesn't start
- Playwright crawl: `page.goto(route, wait_until="load")` + 400ms settle; JS injected to extract interactive elements (inputs/buttons/selects/textareas/links) with label priority: aria-label → placeholder → textContent → title → name; outbound same-origin links; XHR/fetch requests observed during page load
- Accessibility check: final URL path matches requested route → `accessible: true`; redirect to /login etc. → `accessible: false`, reason: `auth_required`
- Unvisitable/auth-gated routes: `_static_page()` returns a shell with `discovered_by: "static_fallback"` and empty `elements: []`; Step 6 uses Step 4 `route_elements` for these routes at E()=0.5
- Process cleanup: all started subprocesses terminated in `finally` block regardless of crawl outcome
- Job statuses: `step_4_complete` → `step_5_running` → `step_5_complete` (or `step_5_error`)
- Frontend polls until `step_5_complete`/`step_5_error`; `AppCrawlerResult.tsx` shows loading skeleton then populated result

**Step 5 output fields** (stored in `step_results.step_5`):
```
pages[] (route, title, discovered_by, accessible, elements[], outbound_links[], api_calls_observed[]),
unvisitable_routes[] (route, reason),
total_pages, error
```
**Element schema:** `{type, subtype, label, selector, visible}` — `selector` and `visible` are always populated for Playwright pages; `elements: []` for `discovered_by: "static_fallback"` pages (L3 fallback via Step 4 `route_elements`).

## What has NOT been built yet

- Steps 6–17 (see PLAN.md for full pipeline)
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
      step3_implied_generator.py     # Two-pass SOP/INF confidence-scored generator
      step4_repo_parser.py           # L3 repo parser (languages/endpoints/routes/models, tree-sitter)
      step5_app_crawler.py           # L2 app crawler (Playwright live crawl only; L3 elements owned by Step 4)
    storage/
      job_store.py                   # JSON file job persistence + list_jobs()
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob()
      types/index.ts                 # Job, Step0Result, Step1Result, Step2Result, etc.
      pages/UploadPage.tsx           # Upload form
      components/
        ClassificationResult.tsx     # Step 0 result display
        AppCrawlerResult.tsx         # Step 5 result display (pages/elements/accessibility)
        RepoParserResult.tsx         # Step 4 result display (languages/endpoints/routes/models)
        PathDisplay.tsx              # Shared traversal path badge renderer (node/element/edge)
        RequirementsResult.tsx       # Step 1 result display (function rows + path expand)
        ObviousRequirementsResult.tsx # Step 2 result display (navigation gap functions)
        GeneratedRequirementsResult.tsx # Step 3 result display (L1a/L1b panels + path expand)
        ConfirmationTable.tsx        # Step 3.5 review/edit table (promote/demote/add/delete + vague auto-replace)
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
- **Formula-driven scores** — LLM never overrides the formula. FCom and FA both output 0–1 (weighted averages: ∑(E×w)/∑w, normalised regardless of max weight). Step 17 multiplies by 5 → 0–5 display scale.
- **Weight/confidence chain** — L1a `weight` derives from `priority` label (critical=4, high=3, medium=2, low=1); user can change at Step 3.5. L1b `weight` derives from `confidence_score` → `strength` (≥0.80 → l1a candidate; 0.60–0.79 → strongly_implied=3.0; 0.40–0.59 → medium=2.0; <0.40 → weak=1.0). `confidence_score` is not used in any formula after these decisions — `weight` is.
- **Step 3.5 as consolidation gate** — confirm endpoint writes a single complete output for all downstream steps: `confirmed_requirements` (L1a), `advisory_requirements` (L1b), `project_context` (Step 0 passthrough), `project_summary` (Step 1). Steps 4+ read only `step_3_5`. Steps 1 and 2 outputs are fully subsumed.
- **Root-level Python check** — `root_level_py` in Step 0 prevents sub-service requirements.txt (depth 2+) from falsely determining backend_framework
- **SSR detection (`_has_html_views`)** — Step 0 checks for `templates/`/`views/` HTML files and engine-specific extensions (`.ejs`, `.twig`, `.blade.php`, etc.) to distinguish Flask/Django/Express SSR apps from pure REST APIs. Without this, all Python/JS/PHP backends without a JS frontend framework were misclassified as `backend_api_only`, producing wrong Step 2 obvious requirements.
- **Java full-stack rule** — `frontend_fw + java_fw` (detected from `pom.xml`/`build.gradle`/`build.gradle.kts`) classifies as `full_stack_web_app` at `high` confidence before the generic `monorepo` check. Ensures Spring Boot + React/Angular/Vue is always classified deterministically.
- **Java SSR rule** — `java_fw + _has_html_views()` bypasses the `return None` early guard so Spring Boot + Thymeleaf is classified deterministically at `high` confidence without LLM. `build.gradle.kts` added to CONFIG_FILES so Gradle Kotlin DSL is readable. Only fires when no SPA frontend detected — SPA suppression (`_SPA_FRAMEWORKS`) takes priority.
- **SPA frontend suppresses template_engine** — When `frontend_fw` is in `_SPA_FRAMEWORKS` (React, Vue, Angular, Svelte, etc. — not Next.js/Nuxt/SvelteKit/Remix/Gatsby), `template_engine` is forced to `null` after `_detect_template_engine` runs. Prevents Thymeleaf from being reported for Spring Boot + React projects where the React SPA is the rendering layer and Thymeleaf is just a pom.xml dependency. Applied in both the rule-based and LLM fallback paths.
- **Service layout flex matching** — `_detect_service_layout` uses prefix matching (not exact set intersection) for directory names: "frontend src", "frontend-app", "frontend_v2" all match the "frontend" keyword. Also: SPA in a frontend-named subdir + non-frontend backend (e.g. Spring Boot in `src/main/java/`) → `"separate_frontend_backend"`. Catches the common Spring Boot + React Vite in one repo pattern where the backend lives in `src/` not `backend/`.
- **Production deps for backend detection** — `backend_fw_js` uses `js_deps_prod` (production `dependencies` only) not `js_deps_merged`, preventing Express/NestJS in `devDependencies` (mock servers, test utilities) from misclassifying a React SPA as a full-stack app.
- **Mobile detection** — React Native / Expo detected before the `frontend_only` branch and classified as `mobile_app` with Jest primary.
- **Static site rule** — HTML files present, no backend language extensions → `static_site` at `medium` confidence. No LLM needed for plain HTML/CSS/JS sites.
- **React source validation** — if `react` is in deps but no `.jsx`/`.tsx` files exist in file_tree → `medium` confidence → LLM review (avoids false high-confidence React claims from peer-dep contamination).
- **New deterministic fields** — `frontend_tooling`, `template_engine`, `service_layout`, `server_routes_detected` computed by pure helpers from the file tree and config contents. Populated for both rule-based and LLM results. See `docs/step0-edge-case-audit.md`.
- **Test strategy primary/secondary** — for `backend_api_only`, primary is always the HTTP-level test tool (Pytest API tests / Jest/Supertest / JUnit/MockMvc / PHPUnit / RSpec), not a unit test runner. Unit tests are never the right primary for verifying user-facing API requirements. Secondary is `null` for API-only (deduped away) and the backend test tool for full-stack apps (Playwright primary + backend tool secondary).
- **Step 1 truncation recovery** — `_parse_llm_response` recovers requirements from truncated JSON responses rather than failing with 0 results
- **Function+path model (Steps 1–3.5)** — Requirements are functions ("User can [action]") with a `path: PathEntity[]` traversal array, not atomic graph entities. `primary: boolean` distinguishes entities fundamentally asserted by a function from context nodes already covered by another. E() is function-level, aggregated as `0.7 × [primary avg] + 0.3 × [secondary avg]`. State-variant nodes (labels with parentheticals) always `primary: false`. Vague functions (`vague: true`) never enter FCom scoring — Step 3 decomposes them via `unpacks` field.
- **Two-pass Step 3** — SOP (pattern table fires on Step 1 stated nodes) + INF (pure domain reasoning from `project_summary`). No 5-category taxonomy. No `structural_edge` — entry/exit baked into function paths. `placement` replaces `l1_recommendation`. Step 3 does not re-apply Step 2 connectivity checks.
- **Step 4 tree-sitter API (0.25)** — `lang.query()` is deprecated; use `Query(lang, pattern)` to create a query and `QueryCursor(query).matches(node)` to execute — returns `list[tuple[int, dict[str, list[Node]]]]`. Node text is `.text` (bytes). Language objects (`_LANG_PY`, `_LANG_JAVA`, etc.) and `Query` objects are created once at module import time, not per-file.
- **Step 4 framework dispatch** — endpoint extraction dispatches on `backend_framework` from `step_3_5.project_context`. Spring Boot: two-level extraction (class-level `@RequestMapping` base path + method-level `@GetMapping` etc.); Kotlin `.kt` files use regex fallback (no tree-sitter-kotlin). Blueprint/APIRouter prefix resolution deferred: paths captured without prefix, annotated if needed by Step 6.
- **Step 4 triggers on confirmation** — `confirm.py` launches `_run_step4()` as a `BackgroundTasks` task immediately after writing `step_3_5`. Job status: `confirmed` → `step_4_running` → `step_4_complete`. Frontend `useEffect` in `App.tsx` polls every 2s until terminal status.
- **Step 5 chains directly from Step 4** — `_run_step4` calls `await _run_step5()` after a successful Step 4 result is written. `step_4_complete` is transient (not a polling terminal status). Frontend terminal statuses: `step_5_complete`, `step_5_error`, `step_4_error`. Job status: `step_4_complete` → `step_5_running` → `step_5_complete`.
- **Step 5 port isolation** — evaluated app uses ports that avoid collision with DSTA's own services: Vite→5174, CRA→3000, backend FastAPI/Django/Spring→8001, Flask→5001, Express→3001, static HTTP→8082. Port 8000 (DSTA backend) and 5173 (DSTA frontend) are never assigned to the evaluated app.
- **Step 5 boot failure → full static fallback** — if the app's process fails to start or the port doesn't respond within 30s, all routes are processed as static_fallback with `reason: "boot_failed"`. No partial crawl.
- **Step 5 Playwright SSL** — `browser.new_context(ignore_https_errors=True)` handles evaluated apps with self-signed certs. DSTA's own httpx port-poll client also uses `verify=False`.
- **playwright install chromium** — Chromium must be installed in the DSTA backend venv: `NODE_TLS_REJECT_UNAUTHORIZED=0 python -m playwright install chromium` (corporate proxy workaround for SSL cert). Already done; stored in `C:\Users\Owner\AppData\Local\ms-playwright\`.
- **Step 4 route normalisation** — all frontend routes start with `/` and have no trailing `/` (except root `/`). Routes are deduplicated within each extraction strategy. Object-based `createBrowserRouter` routes only collected from files that import `react-router-dom`.
- **Step 4 JSX route extraction — `.jsx` vs `.tsx` tree-sitter queries** — Tree-sitter query language must match the language used to parse each file. `_Q_TSX_ROUTE_SC`/`_Q_TSX_ROUTE_OPEN` are compiled against `_LANG_TSX` and silently return nothing when run on `.jsx` files parsed with `_LANG_JS`. Fix: `_Q_JS_ROUTE_SC`/`_Q_JS_ROUTE_OPEN` compiled against `_LANG_JS` are used for `.jsx`/`.js` files; TSX queries used only for `.tsx` files.
- **Step 4 Spring Boot nested zip** — `mvnw.cmd` searched only at root level failed for projects extracted into a subdirectory (e.g. `SpringBoot-Reactjs-Ecommerce-main/`). Fix: `_backend_spec` for Spring Boot and `_find_frontend_dir` now search 2 levels deep from the extract root.
- **Step 3 `depends_on` unhashable list** — LLM occasionally returns `depends_on: [["REQ-001"], "REQ-002"]` (nested list), causing `d in valid_step1_ids` to hash a list → `TypeError`. Fix: `isinstance(d, str)` guard before the set membership check.
- **Step 4 L3 element extraction — JSX comment stripping** — Cart.jsx was ~95% `//`-commented-out code. `_strip_comments()` strips `{/* ... */}` JSX block comments and `^\s*//` line-only comments before element extraction to eliminate false matches from dead code. Used in `_elements_from_text()` (Step 4 `_extract_route_elements`).
- **Step 4 L3 element extraction — button arrow-function label extraction** — `<button onClick={(e) => {...}}>Label</button>`: the `[^>]*?` attr capture stops at the `>` inside `=>`, so the regex captures the arrow function body as "content". Fix: after capturing, `rsplit('>', 1)` takes only the part after the last `>` (the actual closing of the opening tag); then JSX ternary expressions like `{cond ? "Add to Cart" : "Out of Stock"}` are resolved by extracting the first quoted string. Button content regex changed from `([^<]{1,80})` to `(.*?)` with DOTALL to handle multi-line arrow function bodies that exceed 80 chars.
- **Flask/Django SSR `frontend_routes` from GET endpoints** — `_extract_frontend_routes` falls back to GET API endpoint paths (not HTML template filenames) when `frontend_fw` is empty and endpoints exist. Template files (layouts, partials, macros) would otherwise appear as fake routes; the `/` root was also missing because the index handler renders `home.html` (not `index.html`). The endpoints-based fallback fires only when no JS framework was detected, before the static HTML fallback.
- **React SPA / Electron `route_to_files` includes App component** — For projects where route `/` maps only to HTML shell files (e.g. `public/index.html`), Step 4 also adds the main App component (`App.tsx`/`App.jsx`) to `route_to_files['/']`. Lookup order: important_files first, then file-walk. This ensures `_extract_route_elements` reads real JSX source (with actual inputs/buttons) instead of the empty HTML entry point.
- **Blade/template expression form_handler paths normalised to `None`** — `_build_implementation_units` now detects actions containing `{{`, `{%` or starting with `{` (Blade/Jinja/Twig expressions like `{{ route('...') }}`) and sets `path=None` instead of storing the literal expression string.
- **`assets` added to IGNORE_DIRS** — Files under `assets/` directories (e.g. `public/assets/js/chart-lib/index.html`) are now excluded from file walk, language detection, and route extraction. Prevents third-party library HTML files from being mistaken for application routes (observed in Laravel monorepos containing chart libraries).
- **`route_to_files`** — Step 4 maps each frontend route to its source file(s). `_build_route_to_files` is the single source of truth for both route discovery and file mapping — no separate `_extract_frontend_routes` pass. File-based routers (Next.js pages/, SvelteKit +page.svelte) produce exact 1:1 maps. React Router apps: `_route_component_files()` resolves each route → component file via import parsing. Vue/Angular Router: each route maps to the router config file. After initial mapping, `_expand_with_shallow_imports` adds 1-level-deep child imports so `_extract_route_elements` sees form elements in child components. `route_to_files` is internal to Step 4 — not consumed by Step 5.
- **`implementation_units`** — Authoritative L3 signal for Step 6 data edge E() scoring. Wraps every backend handler as `kind: "api_endpoint"` plus HTML `<form method="POST/PUT/DELETE">` tags in SSR template files as `kind: "form_handler"`. Step 6 unlinked L3 detection: `[u for u in implementation_units if u["kind"] == "api_endpoint"]`. `api_endpoints` is no longer a separate output field — it's an internal variable used to build `implementation_units`.
- **Exhaustive completeness model (4 entity types)** — FCom/FA scores four entity types found in each `path[]`: `node` (page/screen), `element` (interactive widget), `navigation edge` (traversal trigger — a link or button that changes route), `data edge` (HTTP mutation — a form submit / delete / update action). Each type has an L3 check (Step 4) and an L2 check (Step 5). L3 sources: `frontend_routes` (nodes), `route_elements` (elements), `navigation_graph` (navigation edges), `implementation_units` (data edges). L2 sources: Step 5 `pages[].accessible` (nodes), `pages[].elements` (elements + navigation edges via Playwright DOM). E() piecewise: L3+L2=1.0, L3 only=0.5, L2 only (data edges)=0.4, neither=0.0. Navigation edges scored same piecewise as element entities via Playwright DOM element presence, not `outbound_links`.
- **Step 5 is a passive crawl only** — Playwright visits each route from Step 4 on page load, extracts visible elements with selectors, and records outbound links. It does NOT fill forms or click buttons — form-submission POST/PUT/DELETE calls are never captured in `api_calls_observed`. `api_calls_observed` is supplementary cross-check against Step 4 only, not an E() evidence source. Bootstrap is heuristic-based from Step 0 `project_context`: `frontend_only`/Vite → `npm run dev`; FastAPI → `uvicorn main:app`; etc. For auth-gated and unvisitable routes, Step 5 returns empty elements (`elements: []`); Step 6 falls back to Step 4 `route_elements` (E()=0.5). CSS selectors come from the running Playwright DOM (not from source analysis — CSS-in-JS and component libraries make source selectors unreliable). Step 9 does NOT read Step 5 selectors; Step 9 generates `getByRole`/`getByText`/`getByPlaceholder` locators from path entity labels via LLM.
- **Step 6 scores E() per entity, not per requirement** — Each `path[]` entity gets its own E() value via a piecewise function by entity type. `node` entities: route in Step 4 + page accessible in Step 5 → {1.0, 0.5, 0.0}. `element` entities: found in Step 5 Playwright DOM=1.0; found in Step 4 `route_elements` (L3 source-level)=0.5; not found=0.0; via LLM fuzzy label matching. `data edge` entities (submit/create/delete/update implied): endpoint in Step 4 `implementation_units` + triggering element in Step 5 Playwright → {1.0, 0.5, 0.4, 0.0}. `navigation edge` entities: navigation trigger found in Step 5 Playwright DOM=1.0; found in Step 4 `navigation_graph` (L3 source-level)=0.5; not found=0.0. Aggregated via formula: `E(req) = 0.7×[primary avg] + 0.3×[secondary avg]`.
- **FCom/FA/FCor are orthogonal and independently scored** — Steps 4–7 compute FCom and FA (presence, no test execution needed). Steps 8–11 compute FCor (correctness, requires E2E test execution). Step 11 test results feed FCor only; they never update FCom E() scores. FCom is locked after Step 7.
- **Unlinked detection (Steps 5/6)** — unlinked L2 = Step 5 routes visited by Playwright where no L1a path[] node entity matched them; unlinked L3 = `implementation_units` items with `kind == "api_endpoint"` not matched as the L3 signal for any L1a requirement. Route-level and endpoint-level, not named-function-level. Step 7 advisory reports both lists.
- **Step 4/5 known limitations (by framework)** — Laravel: no PHP/web.php route parser or Eloquent model extractor; `frontend_routes=[]`, Step 5 returns "No frontend routes" non-fatal error. React SPA / Electron (no router, single-page): `frontend_routes=['/']`, `route_elements['/']` includes App component elements via shallow import expansion, but misses elements in deeper child components not reachable without full import resolution; Step 5 Playwright provides the full L2 picture if the app can boot. Flask SSR `route_to_files['/']`: only contains `app.py` when the root template is named anything other than `index.html`; `route_elements['/']` extracts from Python source (no HTML elements found). None of these are bugs — they are the limit of static analysis without running the app.
- **Step 0 open issues (not fixed in Steps 4/5)** — (1) Laravel `frontend_fw=None`: Blade-rendered apps have no JS frontend framework; Step 4 produces no routes. (2) Electron/React SPA with no router: Step 0 correctly classifies but Step 5 gets 0 elements since the full component tree is not traversed. (3) Monorepos containing Android sub-apps (e.g. AttendanceMS): Java is counted in `languages` from Android source, which is correct but may mislead — it is not Spring Boot Java.

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

1. Build Step 6 — E() Scorer (per-entity piecewise E() functions by entity type; LLM batch calls for element fuzzy matching and endpoint matching; aggregated via α=0.7/0.3 formula; produces `entity_scores[]` per requirement and unlinked lists)
2. Build Step 7 — FCom/FA Scorer (pure Python formula; runs once after Step 6; scores locked; no LLM)
3. Build Step 7.5 — FA Advisor (positive-grounded; runs in parallel with Step 6; reads 3.5+4+5 directly)

---

## Known limitations / future scope

### Microservices
The evaluator is designed for **self-contained applications with user-facing flows**. Microservices architectures are out of scope for the MVP for two reasons:
1. Individual services are rarely self-contained enough to evaluate against user-story-level requirements — most are internally-facing and flows span multiple services
2. Steps 5 (L2 Inventory), 9 (Test Generator), and 11 (Sandbox) assume one running app with one base URL and a UI to crawl

**Future implementation:** Microservices support is a post-MVP in-place extension — do not clone the repo. The branch point is `project_type == "microservices"` from Step 0's job JSON, which already flows through the pipeline. Steps 5, 9, and 11 will need a microservices implementation path. To keep this retrofit additive (not a rewrite), ensure the **output schemas** of Steps 5, 9, and 11 remain stable and Playwright-specific logic does not leak into downstream step inputs.
