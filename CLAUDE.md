# CLAUDE.md — Software Quality Evaluator

Read this file at the start of every session to get full context on the project.

---

## What this project is

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM explains results, never overrides them.

See `PLAN.md` for the full pipeline design, 5-layer model, and scoring formulas.

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
- Service layout flex matching: `_detect_service_layout` now handles dir names with spaces/hyphens/underscores/suffixes (e.g. "frontend src" matches "frontend", "Ecommerce-Frontend" also matches via suffix check). `_matches` checks `startswith` AND `endswith` for `-`, `_`, ` ` separators. Also: a SPA frontend in a frontend-named subdir alongside a non-frontend backend (e.g. Spring Boot in `src/main/java/`) returns `"separate_frontend_backend"` — catches the Spring Boot + React Vite in one repo pattern.
- Service layout zip-wrapper unwrap: `_detect_service_layout` now unwraps a single root wrapper directory (e.g. `SpringBoot-Reactjs-Ecommerce-main/`) before keyword matching — `top_dirs` of size 1 triggers a one-level deeper scan, so `Ecommerce-Frontend` and `Ecommerce-Backend` are correctly identified as frontend/backend dirs. Without this, all paths sharing one container dir were invisible to keyword matching.
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

### Step 1 — Stated Requirement Extractor (COMPLETE)
- Scans uploaded zip for README files (capped at depth ≤ 2) and spec docs (keyword-matched .md/.rst/.txt)
- Ignores tool config dirs: `.claude`, `.cursor`, `.github`, `.vscode`, `.idea` (these waste slots)
- MAX_DOCS = 30, MAX_CHARS_PER_DOC = 12000
- LLM (claude-haiku) extracts stated requirements as **functions** — "User can [action]" active voice. Also extracts `project_summary` (2–3 sentence domain/purpose description) in the same call. Every function must include a verbatim source quote.
- **Function+path model:** Each function includes `path: PathEntity[]` — ordered UI entities traversed to complete the goal. PathEntity: `{type: "node"|"element"|"edge", label, primary: boolean, ui_node?, from?, to?}`. `primary: true` = entity fundamentally asserted by this function (scored if absent); `primary: false` = context already asserted by another function.
- **State-variant nodes** (labels with parentheticals like "(filtered)", "(sorted)", "(updated)") must be omitted from path arrays entirely — they are UI state, not navigable routes, and are never scored. `_validate_path` strips any that slip through post-LLM. Step 1 and Step 3 prompts say "OMIT them entirely."
- **Extraction gate (actor + action framing):** A requirement qualifies only if the user is the actor performing a deliberate action they initiate in the UI (active verb: log in, add, delete, navigate) — "Is the user the subject, and are they choosing to do this?" Fails if the real subject is the system/app/database. The opening rule also excludes "merely observing a result, receiving a message, or having the system act on their behalf" — so reaction/observation statements (e.g. "User sees error message when invalid", "System hashes passwords") are acceptance criteria, routed to Step 8, not L1a functions. Centers the gate on actor+action rather than "observable outcome" (which previously admitted observation statements). Role conditions and trigger phrasings still qualify.
- **Screenshot pages:** Markdown `### Page Name` headings immediately followed by a screenshot image (`![...](...)`) are extracted as single-node functions ("User can access [Page Name]"). This handles README screenshot galleries where pages are documented without action verbs.
- Source quote verification uses whitespace-normalized comparison (`_norm()`) — collapses all whitespace to single space; newlines → spaces tolerated
- JSON truncation recovery: if response is cut off mid-array, recovers items up to last complete `},`
- `excluded_docs_count` in result shows how many spec docs were found but dropped (MAX_DOCS hit)
- `functional_area` field on each function for cascade advisory grouping
- **`project_summary`** passed to Step 3 so INF domain inference is purpose-aware

### Step 2 — Obvious Requirement Generator (COMPLETE)
- LLM finds graph connectivity gaps — pages that cannot be reached or cannot be left
- `discovered_pages` from Step 0 passed to `_identify_root_node()` for root exclusion and shown to LLM as page-file context — node inventory itself is built from Step 1 path arrays via `_extract_nodes_from_paths()`
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
  - **Pass 1 — SOP pattern-triggered (`category: "sop"`):** Fires on Step 1 stated requirements (not a separate node list — the `STATED NODE INVENTORY` block and `_extract_nodes_from_paths` import were removed from the Step 3 user message; Pass 1 reads the stated function descriptions directly). **Pass 1 is conservative — generate ONLY functions explicitly in the pattern table, no freelancing; when in doubt, skip (breadth comes from Pass 2).** Pattern table: list node → filter ~0.82, search ~0.80, sort ~0.68, edit item ~0.85 (L1a), delete item ~0.82 (L1a); detail node → edit ~0.85 (L1a), delete ~0.82 (L1a); create/add stated → edit ~0.85, delete ~0.82 (CRUD completion, now a plain table row — no override language, governed by the same dedup rule as every other pattern); auth present → account management / profile ~0.87; named changeable status → cross-status overview ~0.75, filter-by-status ~0.82; temporal field → time-scoped view ~0.75; mutable records → audit/history ~0.60; user preferences → settings ~0.82; time-sensitive deadlines → notification surface ~0.65; multi-user data → user profile ~0.82. **Dedup rules:** capability test (skip if a stated/obvious function roughly means the same thing, regardless of verb); a function is one complete goal, never a path step (navigate/fill/submit are `path[]` entities of one function, not separate functions); no composite restatements. **Note: dedup is currently prompt-only (no deterministic code backstop in `_validate_and_normalise` beyond exact lowercase string match) — Haiku still occasionally emits subset-of-stated duplicates.**
  - **Pass 2 — INF domain inference (`category: "inf"`):** Reads `project_summary` + all stated functions. Grounding step first: understand this app's purpose, what it manages, and how it works before generating — only generate functions consistent with its actual structure. Then generates across 7 domain-completeness angles: (1) recurring use, (2) workflow completeness / onboarding, (3) data management (export/import/bulk/archive), (4) domain standards (exhaustive — what a comparable app always has), (5) discoverability + help, (6) user control (settings/preferences), (7) overview/insight. Bold — generates at 0.50–0.70; breadth over silence to drive FA scoring.
  - **Pass 3 — dedicated deduplication (`_dedup_generated`):** A separate, single-purpose LLM call run after Passes 1+2 and `_validate_and_normalise`. Generation optimises for recall; Pass 3 is the precision gate. It receives the FULL set — stated + obvious + all generated — and returns `keep`/`drop` per generated function, dropping any that (1) mean the same capability as a stated/obvious function (verb-synonym and location/container-phrasing invariant; "navigate to X section" == obvious "navigate to X page"), (2) are a step within a stated/obvious flow (open/fill/submit form, confirm, cancel, back-nav), or (3) are redundant with another generated function (keep clearest). Survivors are renumbered `GEN-001…`. **Fails open** — any LLM/parse error keeps all generated. This is why the generation prompts no longer carry their own dedup prose: dedup is centralised here, comparing stated AND obvious AND generated-vs-generated equally, which the pass-scoped in-prompt rules structurally could not. Output adds `deduped_count` + `dedup_log` (`id`, `description`, `duplicate_of`, `reason`).
- **Path construction:** One primary rule for all functions: elements and edges are always `primary: true`; nodes are always `primary: false` (pages are traversal context, not assertions). Exception: if a function has no element or edge (sole purpose is asserting a page exists), the node is `primary: true`. Page scope has two cases: (A) existing page — `node (false) → element(s) (true) → submit edge (true)`, no entry/exit nav edges; (B) new page — `entry edge (true) → new page node (false) → body elements (true) → exit edge (true)`, entry must reference an existing stated page. State-variant trailing nodes/elements omitted entirely.
- **Root node detection (`_identify_root_node()`):** Parses nodes from Step 1 path arrays; injects `=== ROOT / HOME PAGE ===` section to prevent phantom landing page generation.
- **Confidence → placement:** ≥ 0.80 → `placement: "l1a"`; 0.60–0.79 → `placement: "l1b"` strength: `strongly_implied`; 0.40–0.59 → `l1b` strength: `medium`; < 0.40 → `l1b` strength: `weak`
- **`depends_on` field:** REQ-xxx IDs only (Step 1 stated functions). OBV-xxx (Step 2 navigation gaps) are not valid targets — a domain enhancement depends on a domain feature, not on navigation plumbing. Validated in `_validate_and_normalise` against `valid_step1_ids`.
- **Result envelope fields:** `requirements`, `total_count`, `sop_count`, `inference_count`, `llm_model`, `dropped_count`, `deduped_count`, `dedup_log`, `error`
- **Frontend:** `GeneratedRequirementsResult.tsx` — L1a panel (green, ≥ 80%) and L1b panel (yellow advisory), category badges (blue=Pattern, purple=Inferred), expandable rows show traversal path (PathDisplay) + reasoning + confidence_reason + depends_on

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- Upload page: drag-and-drop zip + requirements textarea, file size display, validation
- Results: ClassificationResult (Step 0), RequirementsResult (Step 1), ObviousRequirementsResult (Step 2), GeneratedRequirementsResult (Step 3)
- **PathDisplay component (`PathDisplay.tsx`):** Shared component rendering traversal path arrays as type-coded badges with › separators. node=sky, element=violet, edge=amber. Secondary entities (primary=false) rendered at 40% opacity. Each entity shows its label; edges show `from → to`; elements show `ui_node`.
- Each function row expands to show traversal path (PathDisplay), reasoning, confidence, source quote.
- Job list endpoint `GET /api/jobs` lets you find the latest job_id without copying from the frontend

### Backend infrastructure (COMPLETE)
- Python 3.14 + FastAPI
- `POST /api/upload` — validates zip + requirements, creates job, starts background pipeline
- `GET /api/jobs/{job_id}` — returns job JSON
- `GET /api/jobs` — lists recent jobs (most-recent-first, default limit 10)
- `POST /api/jobs/{job_id}/terminate` — stops the in-progress pipeline. Sets status to `terminated`; best-effort tears down any Step 11 sandbox. **Cooperative termination:** `job_store.is_terminated(job_id)` is checked at every step boundary in `_run_pipeline` (Steps 0–3) and the confirm.py chain (`_run_step4`…`_run_step7_5`) + the sandbox runner — a running step finishes but the chain halts and won't overwrite the `terminated` status (the post-await guard also prevents a late step writing `step_X_complete`/`step_X_error` over it). In-flight LLM/subprocess calls are not force-killed; termination takes effect at the next boundary. Frontend top bar (always visible, all stages) has **Terminate** (calls this, stops polling — `terminated` is a polling terminal status) and **New session** (terminates the active job, then resets to the upload page). `terminated` + `step_3_5` present → results stay visible (spinners off); `terminated` without `step_3_5` → stage stays/becomes `loading` so `LoadingView`/`EarlyResultsView` renders with `isTerminated=true` (no crash from missing step results). **Confirmed-stage termination:** when `stage === 'confirming'` and terminate is called, `handleTerminate` does NOT transition stage — the ConfirmationTable remains visible but with the action bar (Confirm/Skip) replaced by a "Pipeline terminated — scoring was not started." notice (`job.status === 'terminated'` check in `ConfirmationTable`). This preserves the full steps 0–3 review the user was looking at. Previously this transitioned to `step_3_complete` which showed an empty ResultPage (no `step_3_5`, no step 4–7.5 data). Additional frontend fixes: (1) `handleUploadComplete` skips `setStage('step_3_complete')` when `pollJob` resolves with `terminated`; (2) URL hash restore with terminated-before-step_3_5 job sets stage to `loading`; (3) `reset()` uses `history.replaceState` instead of `window.location.hash = ''` to cleanly remove the trailing `#` from the URL; (4) `activeStepId` returns -99 for `stage === 'loading'` + `jobStatus === 'terminated'` so the sidebar shows no blue active step; (5) `ResultPage` status text for terminated jobs uses step result presence (`step_results.step_4/5/6/7/7_5`) to display the correct "Steps 0–N complete — terminated" label.
- Job store: one JSON file per job in `./jobs/{job_id}.json`
- Uploads stored in `./uploads/{job_id}/project.zip`
- Pipeline runs Steps 0 → 1 → 2 → 3 as async background task (terminal: `step_3_complete`); Steps 4–7.5 chain automatically after Step 3.5 confirmation (terminal: `step_7_5_complete`)

---

### Step 3.5 — Human Requirement Confirmation + Data Consolidation (COMPLETE)
- Pipeline pauses at `waiting_for_confirmation` after Step 3; resumes when user POSTs to confirm endpoint
- `POST /api/jobs/{job_id}/confirm` — validates job state, writes consolidated result to `step_results.step_3_5`, sets status to `confirmed`
- **This is the single consolidation point for all downstream steps.** Steps 4+ read only from `step_3_5` for all milestone-1 data.
- `ConfirmedRequirement` Pydantic model: `path: list[PathEntity]`, `depends_on: list[str]`, `source_quote: str | None`. `depends_on` and `source_quote` are looked up server-side from prior step results by `req_id` — frontend does not pass them.
- Frontend `ConfirmationTable.tsx` — three-section review table:
  - **Section 1 (L1a)**: all stated + obvious pre-included; Step 3 `placement: "l1a"` candidates pre-included but demotable. Expandable popdown shows PathDisplay + reasoning. Priority dropdown updates weight live.
  - **Section 2 (L1b Advisory)**: Step 3 `placement: "l1b"` items, each promotable to L1a. Expandable popdown shows PathDisplay + reasoning.
  - **Section 3**: inline add-function form → `CUSTOM-001` IDs; placeholder path: `[{type: "node", label: "TBD", primary: true}]`
- Action bar: **Skip** (stated + obvious only, `skipped=true`) and **Confirm (N in score)**
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
- **`route_elements`:** L3 element inventory — `{route: [{type, subtype, label}, ...]}` parsed from each route's source files via regex on JSX/HTML. Extracted by `_extract_route_elements(route_to_files, root)`. Authoritative L3 signal for element E() scoring when Step 5 Playwright cannot visit a route (E()=0.75 for elements/edges; node-only routes score E()=0.5).
- **`navigation_graph`:** L3 navigation graph — `{route: [target_routes...]}` parsed from navigation triggers (`<Link to>`, `<a href>`, `navigate()`, `router.push()`, `history.push()`) in each route's source files. Extracted by `_extract_navigation_graph(route_to_files, root)`. L3 signal for navigation edge E() scoring.
- **`implementation_units`:** unified list of backend handlers — wraps all `api_endpoints` as `kind: "api_endpoint"` plus HTML `<form method="POST/PUT/DELETE">` tags in SSR template files as `kind: "form_handler"`. Authoritative L3 signal for Step 6 data edge E() scoring. Step 6 unlinked detection uses `[u for u in implementation_units if u["kind"] == "api_endpoint"]`.
- **Model extraction:** SQLAlchemy/Django (`class X(Base):`), JPA (`@Entity`), TypeORM (`@Entity()`), Mongoose (`new Schema(...)`), Prisma (`.prisma` regex)
- **Test file detection:** glob patterns (`test_*.py`, `*.test.ts`, `*Test.java`, etc.)
- **Important files:** entry-point names + endpoint files + router/model configs + frontend page/component/service files + config files + Java layer classes — capped at 100
- Job statuses: `confirmed` → `step_4_running` → `step_4_complete` (transient — Step 5 chains immediately) → `step_5_running` → `step_5_complete` (or `step_4_error`/`step_5_error`)
- `RepoParserResult.tsx` renders when step_4 data appears; frontend continues polling to `step_7_5_complete` (terminal)

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
- Unvisitable/auth-gated routes: `_static_page()` returns a shell with `discovered_by: "static_fallback"` and empty `elements: []`; Step 6 uses Step 4 `route_elements` for these routes (E()=0.75 for elements/edges, 0.5 for nodes)
- Process cleanup: all started subprocesses terminated in `finally` block regardless of crawl outcome
- Job statuses: `step_4_complete` → `step_5_running` → `step_5_complete` (transient — Step 6 chains immediately) or `step_5_error`
- Frontend continues polling to `step_7_5_complete` (terminal); `AppCrawlerResult.tsx` shows loading skeleton then populated result

**Step 5 output fields** (stored in `step_results.step_5`):
```
pages[] (route, title, discovered_by, accessible, elements[], outbound_links[], api_calls_observed[]),
unvisitable_routes[] (route, reason),
total_pages, error
```
**Element schema:** `{type, subtype, label, selector, visible}` — `selector` and `visible` are always populated for Playwright pages; `elements: []` for `discovered_by: "static_fallback"` pages (L3 fallback via Step 4 `route_elements`).

### Step 6 — Entity Mapper (COMPLETE)
- Triggered automatically after Step 5 completes (chained in `_run_step5`)
- LLM (claude-haiku) — one call per requirement (L1a + L1b), concurrent via `asyncio.gather`
- **Step 6a (grounding):** For each requirement, builds a scoped inventory (candidate routes from node entity labels, elements from page_inventory for those routes, implementation_units, nav_inventory) and calls LLM to match each path entity to a concrete inventory item. LLM returns one grounding object per entity indexed by position.
- **Step 6b (scoring):** Reads grounding objects and applies deterministic piecewise E() by entity type: node (route_found+accessible=1.0, static_fallback=0.5, none=0.0), element (playwright=1.0, route_elements=0.75, none=0.0), data_edge (endpoint+trigger=1.0, endpoint_only=0.75, trigger_only=0.4, none=0.0), navigation_edge (playwright_element=1.0, navigation_graph=0.75, none=0.0), structural_edge (playwright=1.0, route_elements=0.75, none=0.0). Node stays at 0.5 for L3-only because route accessibility is binary and a non-responding route is a real capability gap. Elements/edges use 0.75 for L3-only because the gap to 1.0 is typically caused by backend-data rendering (API calls that require a running database), not by the feature being absent.
- **Edge classification:** `_classify_edge_kind(label)` — data keywords (submit/add/create/delete/update/save/…), structural keywords (filter/search/sort/drag/reorder), navigation default.
- **Aggregation:** `E(req) = 0.7×[primary_avg] + 0.3×[secondary_avg]` (if no secondary, α=1.0).
- **Unlinked detection:** unlinked_l2 = Step 5 accessible routes not matched by any L1a node entity; unlinked_l3 = Step 4 api_endpoints not matched as data edge L3 signal by any L1a requirement.
- `page_inventory` built from Step 5: playwright-accessible pages use live DOM elements (source=playwright); static_fallback/auth-gated pages fall back to Step 4 route_elements (source=route_elements).
- Tests: `backend/tests/test_step6_entity_mapper.py` — 59 tests, all passing.
- Frontend: `MappingResult.tsx` — per-requirement expandable rows with E() bars, entity score table, unlinked L2/L3 advisory sections.

**Step 6 output fields** (stored in `step_results.step_6`):
```
mapped (req_id, description, e_score, entity_scores[]),
unlinked_l2 (route, title, note),
unlinked_l3 (method, path, handler, file, note),
llm_model, error
```

### Step 7 — FCom/FA Scorer (COMPLETE)

- Triggered automatically after Step 6 completes (chained in `_run_step6`)
- No LLM — pure Python formula
- **FCom:** `∑(E×weight) / ∑weight` over all L1a confirmed requirements (weight from user priority)
- **FA:** same formula over all L1b advisory requirements (weight from strength-derived value)
- **Advisories:** missing_l1a (E<0.5 confirmed requirements, sorted by e_score asc), missing_l1b (E<0.5 advisory), unlinked_routes/endpoints passed through from Step 6
- Tests: `backend/tests/test_step7_scorer.py` — 15 tests, all passing.
- Frontend: `ScoringResult.tsx` — two score panels (FCom, FA) with large percentage display, progress bars, collapsible advisories.

**Step 7 output fields** (stored in `step_results.step_7`):
```
fcom, fa,
fcom_detail (numerator, denominator, requirement_count),
fa_detail,
fcom_advisory (missing_l1a[], unlinked_routes[], unlinked_endpoints[]),
fa_advisory (missing_l1b[]),
error
```

### Step 7.5 — Positive-Grounded FA Advisor (COMPLETE)
- Triggered automatically after Step 7 completes (chained in `_run_step7`)
- LLM (claude-haiku) — one call; reads Steps 3.5, 4, and 5 directly (does NOT depend on Step 6)
- Generates Type B advisory: improvement suggestions grounded in the actual codebase structure (models, endpoints, UI) rather than domain-normative patterns (Type A from Step 7)
- **Dedup against L1b:** user message includes all Step 3 advisory L1b items (capped at 25) so LLM avoids re-generating what Step 3 already suggested
- **Positive inventory:** `database_models`, `implementation_units` (api_endpoints only), `frontend_routes`, and Step 5 live page elements (up to 15 pages × 6 labels) passed to LLM for grounding
- **Output validation:** `_parse_response` validates each suggestion: description non-empty, `suggestion_id` matches `FA-POS-\d+`, `priority` in {high, medium, low}, `l1a_connection` "null"/"none" strings coerced to `None`, missing `grounded_in` defaults to empty lists. Truncation recovery: tries last `},` if full parse fails.
- **Renumbering:** suggestion_ids are renumbered sequentially after parsing (FA-POS-001, FA-POS-002, …) regardless of what LLM generated
- Job statuses: `step_7_complete` → `step_7_5_running` → `step_7_5_complete` (or `step_7_5_error`)
- Tests: `backend/tests/test_step7_5_fa_advisor.py` — 23 tests, all passing
- Frontend: `FA75AdvisorResult.tsx` — per-suggestion cards with priority badge (high=red, medium=amber, low=gray), rationale text, model/endpoint chips, l1a_connection note; loading skeleton; shown below `ScoringResult`

**Step 7.5 output fields** (stored in `step_results.step_7_5`):
```
suggestions[] (suggestion_id, description, grounded_in{models[], endpoints[], rationale}, l1a_connection, priority),
total_count, llm_model, error
```

### Step 8 — Behavioral Requirement Generator (COMPLETE)
- Triggered manually: `POST /api/jobs/{job_id}/behavioral` — requires `step_7_5` complete; caches on hit (re-POST returns existing result); status `step_8_running` → `step_8_complete` | `step_8_error`
- LLM (claude-haiku) — one call; reads raw requirements text + `step_3_5` + `step_4`
- **Orphan autonomous behaviors:** extracts state changes or triggered actions that occur WITHOUT any user-initiated UI action (auto-reset, scheduled notifications, session/cache expiry, background sync). These correctly fail Step 1's actor+action gate (real subject is the system/scheduler/timer), and live here as `BEH-xxx` requirements for correctness testing.
- **Negative grounding:** prompt includes all confirmed + advisory requirements and all `api_endpoints` from `step_4.implementation_units` — LLM skips any behavior that has a matching user-triggerable endpoint
- **`_parse_response`:** JSON array parse with truncation recovery; `req_id` counter uses `len(results)+1` (not enumerate) so invalid/skipped items do not offset BEH numbering; `priority` validated against `{critical, high, medium, low}` (defaults to `medium`); `source_quote` coerced: empty/whitespace-only → `None`
- **Path:** every behavioral requirement gets a fixed path `[{type: "node", label: "System", primary: True}]` — no traversal, scored separately from FCom
- **`_PRIORITY_WEIGHT`:** critical=4.0, high=3.0, medium=2.0, low=1.0 (same scale as L1a)
- Frontend: loading skeleton in `CorrectnessConfirmation.tsx` while `step_8_running`; items appear un-ticked by default in the Behavioral section
- Tests: `backend/tests/test_step8_behavioral_gen.py` — 17 tests, all passing

**Step 8 output fields** (stored in `step_results.step_8`):
```
behavioral_requirements[] (req_id, description, path, priority, weight, source_quote),
llm_model, error
```

### Step 8.5 — AC Generator (COMPLETE)
- Triggered manually: `POST /api/jobs/{job_id}/acs` body `{selected_ids: [...]}` — status `step_8_5_running` → `step_8_5_complete` | `step_8_5_error`
- **Hybrid deterministic + concurrent LLM:** deterministic classification of goal kind, slot set, and weight fractions; LLM (claude-haiku) fills only the Given/When/Then prose; one LLM call per selected requirement via `asyncio.gather`
- **FCor orthogonality:** Step 8.5 reads only `step_3_5` + `step_8` — never reads Step 6 `e_score`. FCom and FCor are independent and cannot be mixed.
- **Per-req caching:** req_ids already present in `step_8_5.acceptance_criteria` are skipped on re-POST; new selections are merged and returned in `selected_ids` order
- **Goal kind classification (`_classify_goal_kind`):** scans all `edge` entities in path by keyword precedence: data > structural > navigation > presence (presence = no edges at all). behavioral = BEH-xxx req_id prefix (separate slot set).
- **Data verb sub-classification (`_classify_data_verb`):** delete > create > update keyword precedence on edge labels; default = create.
- **AC slot sets (`_ac_slots`):**
  - `data` → [happy_path 0.5, persistence 0.3, edge_case 0.2]
  - `structural` → [happy_path 0.7, edge_case 0.3]
  - `navigation` → [happy_path 1.0]
  - `presence` → [happy_path 1.0]
  - `behavioral` → [fires_when_due 0.6, not_before_due 0.4]
- **`_compute_acws`:** `acw_i = round(frac_i × W, 2)`; last AC absorbs rounding remainder so `Σacw == W` exactly
- **`_ac_id` format:** REQ-001 → AC-001-1; OBV-001 → AC-OBV-001-1; GEN-005 → AC-GEN-005-3; BEH-001 → AC-BEH-001-1; CUSTOM-001 → AC-CUSTOM-001-1
- **`_test_type` rule:** behavioral goal → `"behavioral"`; data goal + API-only test strategy (primary contains "api" or "supertest" case-insensitive, no "e2e") → `"api"`; all other combinations → `"e2e"`
- **`_classify_edge_kind` shared:** extracted from `step6_entity_mapper.py` to `pipeline/utils.py`; Step 6 imports from there (`_DATA_KEYWORDS`, `_STRUCTURAL_KEYWORDS`, `_classify_edge_kind`)
- **`run()`:** builds lookup dict of all reqs (confirmed L1a + advisory L1b + behavioral BEH), skips cached, fires concurrent LLM calls, merges cached+new in `selected_ids` order
- **Placeholder GWT:** if LLM returns fewer AC items than slots, missing slots are filled with placeholder text (`"[LLM did not generate this AC]"`) so output length always matches slot count
- Frontend: `ACResult.tsx` — per-req collapsible cards with goal_kind / type / test_type badges; per-AC cards with given/when/then prose, acw, type badge; loading skeleton
- Tests: `backend/tests/test_step8_5_ac_generator.py` — 46 tests, all passing

**Step 8.5 output fields** (stored in `step_results.step_8_5`):
```
acceptance_criteria[] (req_id, description, type, goal_kind, l1cx, test_type,
  acceptance_criteria[]: {ac_id, given, when, then, acw, type}),
selected_ids, total_acs, llm_model, error
```

**Correctness screen navigation (frontend):**
- Hash routing: `#<jobId>` = presence view (Steps 0–7.5); `#<jobId>/correctness` = correctness screen (Steps 8/8.5)
- `canRunCorrectness = !!(step_results.step_7_5)` — sidebar FCor header glows (`animate-pulse`, indigo) when true and not already on correctness screen
- Sidebar FCor group header: label button navigates to correctness screen; separate chevron button toggles the group dropdown. Presence header becomes clickable to navigate back when on correctness screen.
- `handleNavCorrectness()` in App.tsx: sets hash, sets stage to `'correctness'`, fires `generateBehavioral()` (POST behavioral endpoint)
- `handleNavPresence()`: sets hash back to `#<jobId>`, sets stage to `'step_3_complete'`
- Correctness polling effect: polls while `step_8_running` or `step_8_5_running`
- Hash restore on mount: if view==='correctness' and `step_7_5` present → sets stage to `'correctness'`

## What has NOT been built yet

- Steps 9–10, 12–17 (see PLAN.md for full pipeline)
- Step 11 test execution (Docker boot is complete; test scripts require Steps 9–10)

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
        correctness.py               # POST /api/jobs/{job_id}/behavioral, /acs
    pipeline/
      step0_classifier.py            # Project type + framework classifier
      step1_req_extractor.py         # Stated requirement extractor
      step2_obvious_generator.py     # Obvious requirement generator
      step3_implied_generator.py     # Two-pass SOP/INF confidence-scored generator
      step4_repo_parser.py           # L3 repo parser (languages/endpoints/routes/models, tree-sitter)
      step5_app_crawler.py           # L2 app crawler (Playwright live crawl only; L3 elements owned by Step 4)
      step8_behavioral_gen.py        # Orphan autonomous behavior extractor (BEH-xxx)
      step8_5_ac_generator.py        # Hybrid deterministic+LLM AC generator (Given/When/Then, acw math)
      utils.py                       # Shared: _classify_edge_kind, _validate_path, etc.
    storage/
      job_store.py                   # JSON file job persistence + list_jobs()
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob(), generateBehavioral(), generateACs()
      types/index.ts                 # Job, Step0Result…Step85Result, BehavioralRequirement, ACRequirementResult, etc.
      pages/UploadPage.tsx           # Upload form
      components/
        ClassificationResult.tsx     # Step 0 result display
        AppCrawlerResult.tsx         # Step 5 result display (pages/elements/accessibility)
        RepoParserResult.tsx         # Step 4 result display (languages/endpoints/routes/models)
        PathDisplay.tsx              # Shared traversal path badge renderer (node/element/edge)
        RequirementsResult.tsx       # Step 1 result display (function rows + path expand)
        ObviousRequirementsResult.tsx # Step 2 result display (navigation gap functions)
        GeneratedRequirementsResult.tsx # Step 3 result display (L1a/L1b panels + path expand)
        ConfirmationTable.tsx        # Step 3.5 review/edit table (promote/demote/add/delete)
        CorrectnessConfirmation.tsx  # Step 8/8.5 correctness screen (selection + AC display)
        ACResult.tsx                 # Step 8.5 AC display (per-req collapsible cards + GWT prose)
        Sidebar.tsx                  # Stage-aware sidebar (FCor group header nav + glow)
      App.tsx                        # Stage state machine (correctness stage + hash routing)
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
venv\Scripts\activate          # Python 3.14 venv
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
- **Step 0 LLM uses tool use (not free-form JSON)** — `CLASSIFICATION_TOOL` defines enum-constrained schemas for `project_type`, `frontend_framework`, `backend_framework`, and `confidence`. `tool_choice={"type": "tool", "name": "classify_project"}` forces the model to always call the tool; `tool_block.input` is already a parsed dict. Python explicitly plucks each LLM field by name into a controlled output dict and computes the remaining fields (`frontend_tooling`, `template_engine`, `service_layout`, `server_routes_detected`, `test_strategy`) deterministically.
- **JSON files per job** in `./jobs/` — no database for MVP; easy to inspect and debug
- **Async background task** (FastAPI `BackgroundTasks`) — upload returns immediately with `job_id`, frontend polls
- **Python 3.14** — venv at `backend\venv`; pydantic-core installs from a prebuilt wheel (no Rust toolchain needed)
- **Formula-driven scores** — LLM never overrides the formula. FCom and FA both output 0–1 (weighted averages: ∑(E×w)/∑w, normalised regardless of max weight). Step 17 multiplies by 5 → 0–5 display scale.
- **Weight/confidence chain** — L1a `weight` derives from `priority` label (critical=4, high=3, medium=2, low=1); user can change at Step 3.5. L1b `weight` derives from `confidence_score` → `strength` (≥0.80 → l1a candidate; 0.60–0.79 → strongly_implied=3.0; 0.40–0.59 → medium=2.0; <0.40 → weak=1.0). `confidence_score` is not used in any formula after these decisions — `weight` is.
- **Step 3.5 as consolidation gate** — confirm endpoint writes a single complete output for all downstream steps: `confirmed_requirements` (L1a), `advisory_requirements` (L1b), `project_context` (Step 0 passthrough), `project_summary` (Step 1). Steps 4+ read only `step_3_5`. Steps 0–3 outputs are fully subsumed.
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
- **Test strategy primary/secondary** — for `backend_api_only`, primary is always the HTTP-level test tool (Pytest API tests / Jest/Supertest / JUnit/MockMvc / PHPUnit / RSpec), not a unit test runner. Unit tests are never the right primary for verifying user-facing API requirements. Secondary is `null` for API-only (deduped away) and the backend test tool for full-stack apps (Playwright primary + backend tool secondary).
- **Step 1 truncation recovery** — `_parse_llm_response` recovers requirements from truncated JSON responses rather than failing with 0 results
- **Function+path model (Steps 1–3.5)** — Requirements are functions ("User can [action]") with a `path: PathEntity[]` traversal array, not atomic graph entities. `primary: boolean` distinguishes entities fundamentally asserted by a function from context nodes already covered by another. E() is function-level, aggregated as `0.7 × [primary avg] + 0.3 × [secondary avg]`. State-variant trailing nodes/elements (labels with parentheticals like "(updated)", "(filtered)", or result-state descriptors like "filtered employee list") must be omitted from paths entirely — `_validate_path` strips trailing state-variant nodes post-LLM.
- **Three-pass Step 3** — SOP (pattern table fires on Step 1 stated requirements) + INF (pure domain reasoning from `project_summary`) + a dedicated **Pass 3 deduplication** LLM call. **Generation passes carry NO dedup prose** — dedup is centralised in Pass 3, which sees stated + obvious + all generated equally and fails open on error. **Lean LLM output schema:** the generation LLM emits only the 8 fields it must author — `description`, `path`, `category`, `confidence_score`, `reasoning`, `priority`, `depends_on`, `functional_area`. The deterministic fields (`req_id`, `source`, `tag`, `placement`, `strength`, `weight`, `testable`) are computed by `_validate_and_normalise`. `confidence_reason` is back-filled from `reasoning` in code (display-only, never scored). Cuts generation output tokens ~40%.
- **Step 4 tree-sitter API (0.25)** — `lang.query()` is deprecated; use `Query(lang, pattern)` to create a query and `QueryCursor(query).matches(node)` to execute — returns `list[tuple[int, dict[str, list[Node]]]]`. Node text is `.text` (bytes). Language objects (`_LANG_PY`, `_LANG_JAVA`, etc.) and `Query` objects are created once at module import time, not per-file.
- **Step 4 framework dispatch** — endpoint extraction dispatches on `backend_framework` from `step_3_5.project_context`. Spring Boot: two-level extraction (class-level `@RequestMapping` base path + method-level `@GetMapping` etc.); Kotlin `.kt` files use regex fallback (no tree-sitter-kotlin). Blueprint/APIRouter prefix resolution deferred: paths captured without prefix, annotated if needed by Step 6.
- **Step 4 triggers on confirmation** — `confirm.py` launches `_run_step4()` as a `BackgroundTasks` task immediately after writing `step_3_5`. Job status: `confirmed` → `step_4_running` → `step_4_complete`. Frontend `useEffect` in `App.tsx` polls every 2s until terminal status.
- **Step 5 chains directly from Step 4** — `_run_step4` calls `await _run_step5()` after a successful Step 4 result is written. `step_4_complete` is transient. Steps 5→6→7→7.5 are similarly chained; terminal polling status is `step_7_5_complete`.
- **Step 5 port isolation** — evaluated app uses ports that avoid collision with DSTA's own services: Vite→5174, CRA→3000, backend FastAPI/Django/Spring→8001, Flask→5001, Express→3001, static HTTP→8082. Port 8000 (DSTA backend) and 5173 (DSTA frontend) are never assigned to the evaluated app.
- **Step 5 boot failure → full static fallback** — if the app's process fails to start or the port doesn't respond within 30s, all routes are processed as static_fallback with `reason: "boot_failed"`. No partial crawl.
- **Step 5 Playwright SSL** — `browser.new_context(ignore_https_errors=True)` handles evaluated apps with self-signed certs. DSTA's own httpx port-poll client also uses `verify=False`.
- **playwright install chromium** — Chromium must be installed in the DSTA backend venv: `NODE_TLS_REJECT_UNAUTHORIZED=0 python -m playwright install chromium` (corporate proxy workaround for SSL cert). Already done; stored in `C:\Users\Owner\AppData\Local\ms-playwright\`.
- **Step 4 route normalisation** — all frontend routes start with `/` and have no trailing `/` (except root `/`). Routes are deduplicated within each extraction strategy. Object-based `createBrowserRouter` routes only collected from files that import `react-router-dom`.
- **Step 4 JSX route extraction — `.jsx` vs `.tsx` tree-sitter queries** — Tree-sitter query language must match the language used to parse each file. `_Q_TSX_ROUTE_SC`/`_Q_TSX_ROUTE_OPEN` are compiled against `_LANG_TSX` and silently return nothing when run on `.jsx` files parsed with `_LANG_JS`. Fix: `_Q_JS_ROUTE_SC`/`_Q_JS_ROUTE_OPEN` compiled against `_LANG_JS` are used for `.jsx`/`.js` files; TSX queries used only for `.tsx` files.
- **Step 4 Spring Boot nested zip** — `mvnw.cmd` searched only at root level failed for projects extracted into a subdirectory (e.g. `SpringBoot-Reactjs-Ecommerce-main/`). Fix: `_backend_spec` for Spring Boot and `_find_frontend_dir` now search 2 levels deep from the extract root.
- **Step 3 `depends_on` unhashable list** — LLM occasionally returns `depends_on: [["REQ-001"], "REQ-002"]` (nested list). Causes a `TypeError` when Python tries to hash the value for set membership. Fix: `isinstance(d, str)` guard in the `depends_on` list comprehension.
- **Step 4 L3 element extraction — JSX comment stripping** — Cart.jsx was ~95% `//`-commented-out code. `_strip_comments()` strips `{/* ... */}` JSX block comments and `^\s*//` line-only comments before element extraction to eliminate false matches from dead code. Used in `_elements_from_text()` (Step 4 `_extract_route_elements`).
- **Step 4 L3 element extraction — button arrow-function label extraction** — `<button onClick={(e) => {...}}>Label</button>`: the `[^>]*?` attr capture stops at the `>` inside `=>`, so the regex captures the arrow function body as "content". Fix: after capturing, `rsplit('>', 1)` takes only the part after the last `>` (the actual closing of the opening tag); then JSX ternary expressions like `{cond ? "Add to Cart" : "Out of Stock"}` are resolved by extracting the first quoted string. Button content regex changed from `([^<]{1,80})` to `(.*?)` with DOTALL to handle multi-line arrow function bodies that exceed 80 chars.
- **Step 4 L3 element extraction — input `onChange` arrow-function truncation** — `<input onChange={(e) => setState(e.target.value)} placeholder="X" />`: `_JSX_INPUT_RE` used `[^>]*?` for attribute matching which stops at the `>` in the arrow function `=>`, silently dropping all attributes after the onChange (including `placeholder`). Fix: changed `_JSX_INPUT_RE` to use `(?:[^>{}]|\{(?:[^{}]|\{[^{}]*\})*\})*?` — this allows `{...}` blocks (up to 2 levels of nesting) within the attribute span so `>` inside curly braces no longer terminates the match. Confirmed affected real-world case: LoginPage.jsx username/password inputs were missing from `route_elements` because their `onChange` used arrow functions.
- **Flask/Django SSR `frontend_routes` from GET endpoints** — `_extract_frontend_routes` falls back to GET API endpoint paths (not HTML template filenames) when `frontend_fw` is empty and endpoints exist. Template files (layouts, partials, macros) would otherwise appear as fake routes; the `/` root was also missing because the index handler renders `home.html` (not `index.html`). The endpoints-based fallback fires only when no JS framework was detected, before the static HTML fallback.
- **React SPA / Electron `route_to_files` includes App component** — For projects where route `/` maps only to HTML shell files (e.g. `public/index.html`), Step 4 also adds the main App component (`App.tsx`/`App.jsx`) to `route_to_files['/']`. Lookup order: important_files first, then file-walk. This ensures `_extract_route_elements` reads real JSX source (with actual inputs/buttons) instead of the empty HTML entry point.
- **Blade/template expression form_handler paths normalised to `None`** — `_build_implementation_units` now detects actions containing `{{`, `{%` or starting with `{` (Blade/Jinja/Twig expressions like `{{ route('...') }}`) and sets `path=None` instead of storing the literal expression string.
- **`assets` added to IGNORE_DIRS** — Files under `assets/` directories (e.g. `public/assets/js/chart-lib/index.html`) are now excluded from file walk, language detection, and route extraction. Prevents third-party library HTML files from being mistaken for application routes (observed in Laravel monorepos containing chart libraries).
- **`route_to_files`** — Step 4 maps each frontend route to its source file(s). `_build_route_to_files` is the single source of truth for both route discovery and file mapping — no separate `_extract_frontend_routes` pass. File-based routers (Next.js pages/, SvelteKit +page.svelte) produce exact 1:1 maps. React Router apps: `_route_component_files()` resolves each route → component file via import parsing. Vue/Angular Router: each route maps to the router config file. After initial mapping, `_expand_with_shallow_imports` adds 1-level-deep child imports so `_extract_route_elements` sees form elements in child components. `route_to_files` is internal to Step 4 — not consumed by Step 5.
- **`implementation_units`** — Authoritative L3 signal for Step 6 data edge E() scoring. Wraps every backend handler as `kind: "api_endpoint"` plus HTML `<form method="POST/PUT/DELETE">` tags in SSR template files as `kind: "form_handler"`. Step 6 unlinked L3 detection: `[u for u in implementation_units if u["kind"] == "api_endpoint"]`. `api_endpoints` is no longer a separate output field — it's an internal variable used to build `implementation_units`.
- **Exhaustive completeness model (5 entity types)** — FCom/FA scores five entity types found in each `path[]`: `node` (page/screen), `element` (interactive widget), `navigation edge` (traversal trigger — a link or button that changes route), `data edge` (HTTP mutation — a form submit / delete / update action), `structural edge` (client-side UI interaction — filter/search/sort — no HTTP mutation; classified by Step 6 keyword table on edge labels). Each type has an L3 check (Step 4) and an L2 check (Step 5). L3 sources: `frontend_routes` (nodes), `route_elements` (elements + structural edges), `navigation_graph` (navigation edges), `implementation_units` (data edges). L2 sources: Step 5 `pages[].accessible` (nodes), `pages[].elements` (elements + navigation edges + structural edges via Playwright DOM). E() piecewise: L3+L2=1.0, L3 only=0.5, L2 only (data edges)=0.4, neither=0.0. Navigation and structural edges scored same piecewise as element entities; structural edges skip `implementation_units` lookup.
- **Step 5 is a passive crawl only** — Playwright visits each route from Step 4 on page load, extracts visible elements with selectors, and records outbound links. It does NOT fill forms or click buttons — form-submission POST/PUT/DELETE calls are never captured in `api_calls_observed`. `api_calls_observed` is supplementary cross-check against Step 4 only, not an E() evidence source. Bootstrap is heuristic-based from Step 0 `project_context`: `frontend_only`/Vite → `npm run dev`; FastAPI → `uvicorn main:app`; etc. For auth-gated and unvisitable routes, Step 5 returns empty elements (`elements: []`); Step 6 falls back to Step 4 `route_elements` (E()=0.75 for elements/edges, 0.5 for nodes). CSS selectors come from the running Playwright DOM (not from source analysis — CSS-in-JS and component libraries make source selectors unreliable). Step 9 does NOT read Step 5 selectors; Step 9 generates `getByRole`/`getByText`/`getByPlaceholder` locators from path entity labels via LLM.
- **Step 6 scores E() per entity, not per requirement** — Each `path[]` entity gets its own E() value via a piecewise function by entity type. `node` entities: route in Step 4 + page accessible in Step 5 → {1.0, 0.5, 0.0}. `element` entities: found in Step 5 Playwright DOM=1.0; found in Step 4 `route_elements` (L3 source-level)=0.75; not found=0.0; via Step 6a function-level grounding (route-scoped, one LLM call per function). `data edge` entities (submit/create/delete/update implied): endpoint in Step 4 `implementation_units` + triggering element in Step 5 Playwright → {1.0, 0.75, 0.4, 0.0}. `navigation edge` entities: navigation trigger found in Step 5 Playwright DOM=1.0; found in Step 4 `navigation_graph` (L3 source-level)=0.75; not found=0.0. Aggregated via formula: `E(req) = 0.7×[primary avg] + 0.3×[secondary avg]`.
- **FCom/FA/FCor are orthogonal and independently scored** — Steps 4–7 compute FCom and FA (presence, no test execution needed). Steps 8–11 compute FCor (correctness, requires E2E test execution). Step 11 test results feed FCor only; they never update FCom E() scores. FCom is locked after Step 7.
- **Unlinked detection (Steps 5/6)** — unlinked L2 = Step 5 routes visited by Playwright where no L1a path[] node entity matched them; unlinked L3 = `implementation_units` items with `kind == "api_endpoint"` not matched as the L3 signal for any L1a requirement. Route-level and endpoint-level, not named-function-level. Step 7 advisory reports both lists.
- **Step 4/5 known limitations (by framework)** — Laravel: no PHP/web.php route parser or Eloquent model extractor; `frontend_routes=[]`, Step 5 returns "No frontend routes" non-fatal error. React SPA / Electron (no router, single-page): `frontend_routes=['/']`, `route_elements['/']` includes App component elements via shallow import expansion, but misses elements in deeper child components not reachable without full import resolution; Step 5 Playwright provides the full L2 picture if the app can boot. Flask SSR `route_to_files['/']`: only contains `app.py` when the root template is named anything other than `index.html`; `route_elements['/']` extracts from Python source (no HTML elements found). None of these are bugs — they are the limit of static analysis without running the app.
- **Step 0 open issues (not fixed in Steps 4/5)** — (1) Laravel `frontend_fw=None`: Blade-rendered apps have no JS frontend framework; Step 4 produces no routes. (2) Electron/React SPA with no router: Step 0 correctly classifies but Step 5 gets 0 elements since the full component tree is not traversed. (3) Monorepos containing Android sub-apps (e.g. AttendanceMS): Java is counted in `languages` from Android source, which is correct but may mislead — it is not Spring Boot Java.
- **Step 6 concurrent LLM calls** — `asyncio.gather` fires one Haiku call per requirement (L1a + L1b) simultaneously. Per-call `try/except` ensures one failure returns `[{}] * len(path)` (empty grounding, all E()=0) without aborting the other requirements. Unlike Steps 1–3 which make one large LLM call, Step 6 makes N small calls — typically 20–50 for a real project.
- **Step 6 `_candidate_routes` heuristic** — Before building the scoped inventory for a requirement's LLM call, node entity labels are matched against route paths by substring/word similarity (e.g. "Login Page" → "/login"). This limits the element inventory passed to the LLM to the most relevant routes. Root "/" is always included. For requirements with no node entities, the first 10 routes are used. The LLM still does the final resolution — `_candidate_routes` only determines which routes' element inventories are passed in the prompt.
- **Step 6 `page_inventory` source field** — `"playwright"` = live DOM from Step 5 (page accessible, E()=1.0 for matched elements/edges); `"route_elements"` = Step 4 static parse (auth-gated, boot-failed, or static_fallback routes — elements/edges E()=0.75, node E()=0.5); `"none"` = no evidence at all (E()=0.0). The source is propagated through grounding objects as `match_source` for deterministic scoring in Step 6b.
- **Step 7 advisory threshold** — `missing_l1a` and `missing_l1b` include requirements with `e_score < 0.5` (not `== 0.0`). This captures both fully missing (0.0) and partially found but weak (e.g. 0.4) requirements. Results sorted by e_score ascending so the worst gaps appear first.
- **Step 6 grounding node-matching root cause** — Haiku inconsistently maps human-readable page labels (e.g. "Employee List Page") to technical route paths (e.g. `/search`) when the label and route don't share words. This causes cascade failure: node=null → element=null → edge=null → E=0 for entire requirement. Three LLM prompt fixes applied: (1) Route list in grounding prompt now annotated with top-5 element labels so LLM can match by content: `- /search  [Employee ID, First Name, Last Name, Login ID]`; (2) `_candidate_routes` returns all routes when app has ≤10 routes (avoids silently omitting the relevant route from the element inventory); (3) System prompt node instruction rewritten to explicitly prefer content-based matching over literal name match.
- **Step 6 deterministic node fallback (`_match_node_to_route`)** — Haiku non-determinism and transient SSL errors both cause node match failures. Root fix: `_match_node_to_route()` is a deterministic Python fallback using word-overlap scoring with semantic category hints — route path word overlap scores 4×, element content overlap capped at 3, plus structural bonuses: labels with list/search words → `_ROUTE_LIST_PATHS` route match +4; detail/edit labels + dynamic route +4; `_ROUTE_AUTH_PATHS` suppresses list/detail bonuses; home labels + "/" +3. Minimum score threshold 3 rejects false positives. The fallback runs **outside** the try/retry loop (initialized before the loop, applied after it) so it fires regardless of LLM success or failure. PascalCase labels ("SearchEmployeePage") split via `_SPLIT_CAMEL_RE`; state-variant parentheticals ("(filtered)") stripped before matching. Fallback only fires when LLM returned null — does not override successful LLM matches.
- **Step 5 npm boot on Windows** — `asyncio.create_subprocess_exec` uses Windows `CreateProcess` which cannot run `.cmd` files (npm on Windows is `npm.cmd`) without `cmd /c`. All npm commands now wrapped via `_wrap_npm_cmd()` on Windows. `_npm_install_if_needed()` also runs `npm install --prefer-offline` when `node_modules/` is absent (common when zip excludes it). Port poll timeout increased 30s → 60s for extra install+boot time.
- **Step 5 npm SSL fix** — `NODE_TLS_REJECT_UNAUTHORIZED=0` does NOT work with npm 11.x (it uses undici for HTTP, not Node's built-in TLS stack). The correct flag is `--strict-ssl=false` passed directly to the npm install command. `_npm_install_if_needed` now passes `--strict-ssl=false` so npm can fetch packages through corporate proxies with self-signed certificates. Without this, npm install fails silently, node_modules is never created, npm run dev fails immediately, and all routes fall through to `boot_failed` static fallback.
- **Step 5 / confirm.py absolute path fix** — `extract_to` is stored in the job JSON as a relative path (`uploads\job_id\extracted`). When FastAPI background tasks call `step5_app_crawler.run()`, the relative path must be resolved to absolute before use. Fix: `confirm.py` calls `.resolve()` before passing `extract_to` to the background task; `step5_app_crawler.run()` also calls `extract_to = Path(extract_to).resolve()` at the top.
- **Step 5 Playwright sync API fix** — uvicorn's event loop on Windows is a `SelectorEventLoop` which does NOT support `asyncio.create_subprocess_exec`. Playwright's async API (`async_playwright`) calls `asyncio.create_subprocess_exec` internally to launch the browser driver process, raising `NotImplementedError` silently (caught by the outer `except Exception`). Fix: replaced `async_playwright` + async Playwright calls with `sync_playwright` (Playwright's sync API) wrapped in `asyncio.to_thread`. This runs the entire crawl in a thread pool, completely bypassing the event loop's subprocess restriction. All `await page.xxx()` calls become synchronous `page.xxx()` calls inside `_crawl_routes_sync`. The `_npm_install_if_needed` subprocess is similarly wrapped with `asyncio.to_thread(subprocess.run, ...)` instead of `asyncio.create_subprocess_exec`. The dev server start uses `subprocess.Popen` (non-async) directly.
- **`/api/jobs` KeyError** — `list_jobs` crashed with `KeyError: 'job_id'` on legacy job files missing that field. Fixed: `if j and j.get("job_id")` guard + `.get()` with defaults for all summary fields. `get_job` now catches `json.JSONDecodeError` and returns `None` instead of raising (handles partially-written job files from crashed runs).
- **Step 5 non-SSR full-stack boot** — `_bootstrap_commands` for `full_stack_web_app` with `service_layout != "separate_frontend_backend"` attempted `_backend_spec` first. When `template_engine is None` (SPA frontend, no SSR), the backend spec would find a Spring Boot `mvnw.cmd` and return it, causing a `boot_failed` (Spring Boot needs a real DB/env). Fix: the `else` branch now checks `template_engine is None and frontend_fw` first; if true, goes directly to `_find_frontend_dir` + `_npm_cmd` to boot the SPA. SSR apps (`template_engine` set) still go through `_backend_spec` as before.
- **Step 5 file input label extraction** — `<input type="file">` has no `aria-label`, `placeholder`, or `textContent`. Playwright's JS extractor silently dropped file inputs. Fix: in `_JS_EXTRACT_ELEMENTS`, when `type === 'file'` and `rawLabel` is empty, walk to the previous sibling `<label>` element (or the parent element's first `<label>`), and use its `textContent` (trailing `:` stripped) as the label.
- **Step 5 ARIA role element capture** — Modern React apps (Tailwind, MUI, shadcn) render buttons, tabs, and dropdowns as `<div role="button">`, `<div role="tab">`, etc. The original `querySelectorAll('input, button, select, textarea, a[href]')` missed all of these. Fix: `_JS_EXTRACT_ELEMENTS` refactored into a shared `addEl(el, elemType, subtype)` helper; Pass 2 iterates 9 ARIA roles (`button`, `link`, `checkbox`, `radio`, `switch`, `tab`, `combobox`, `searchbox`, `menuitem`) and calls `addEl` for each non-native element found. Deduplication key uses `elemType` (not raw tag) so a `<div role="button">Submit</div>` and `<button>Submit</button>` collapse to the same entry.
- **Step 5 networkidle wait** — `wait_until="load"` fires before React's `useEffect` data-fetch cycle completes, so async-loaded content (product lists, employee tables) was missing from the element snapshot even when the backend is running. Fix: after `page.goto(url, wait_until="load")`, call `page.wait_for_load_state("networkidle", timeout=5_000)` as a best-effort wait — allows async fetches to complete and DOM to re-render before snapshot. The inner timeout is intentionally short (5s); apps with continuous polling or WebSocket connections that never reach networkidle silently fall through to a 500ms settle and proceed. Outer `goto` timeout increased 10s → 15s.
- **Step 6 false-negative root causes and deterministic fallbacks** — Four categories of false negatives were identified and fixed: (1) **Root "/" route not matchable for "add/create" labels**: `_match_node_to_route` now gives a +2 bonus when `route == "/"`, the label contains add/create/new words, and the route's element inventory also contains those words — closes the gap from zero path-word overlap. (2) **Conditionally-rendered elements missing from Playwright DOM** (e.g. Delete/Edit buttons that only appear when backend data loads): `_build_page_inventory` now merges `route_elements` entries not found by Playwright into the inventory for Playwright-accessible pages, tagged with `_fallback_source: "route_elements"`. `_resolve_element_source()` resolves the authoritative source per matched label from `_playwright_labels` set — playwright-DOM elements score E=1.0, merged route_elements entries score E=0.5. (3) **LLM grounding failures for elements** (LLM inconsistently misses elements present in inventory): `_match_element_in_inventory()` is a new deterministic word-overlap fallback applied in Pass 2 of `_ground_requirement` after the LLM call; uses the last resolved node route as context and fuzzy-matches label words against inventory elements, then raw `route_elements` if still unmatched. (4) **Navigation edges always E=0** (generic labels like "navigation link"/"exit path" never LLM-matched): Pass 3 auto-scores navigation edges from `nav_inventory` when adjacent node routes are known — prev→next if nav_graph has that edge; any reachable target if only prev_route known; any source pointing to next_route if only next_route known. (5) **Data edge endpoints not matched**: Pass 4 infers HTTP verb from edge label keywords (submit/update→PUT, delete→DELETE, create/upload→POST, etc.) and keyword-matches against `implementation_units`; accepts a lone candidate even with score=0 when the verb uniquely identifies one endpoint.
- **Step 6 dot-notation label pollution** — React `value={product.name}` JSX patterns were extracted by Step 4 as element labels `"product.name"`, `"product.brand"` etc. because the state-variable reference is the only text available when placeholder is dynamic. Shallow import expansion spread these labels to every route that imports the component (e.g. `UpdateProduct.jsx` labels appearing in `/add_product`'s inventory). The LLM would pick `product.name` over the Playwright-visible `Product Name`, causing E=0.5 instead of E=1.0. Fix: `_DOT_LABEL_RE = re.compile(r"^\w+\.\w+")` — labels matching this pattern are filtered out in `_build_page_inventory` (both the merged-extra list for Playwright pages and route_elements-only pages) and in the `route_elements_raw` fallback of `_match_element_in_inventory`. Dot-notation labels are never valid UI labels.
- **Step 6 form-confirmation promotion** — controlled React form inputs use `name` attribute as label (e.g. `"name"`, `"brand"`) when no `placeholder` is defined and `value=""` (edit forms that pre-populate from API state). These differ from the descriptive route_elements labels (`"Product Name"`, `"Enter your Brand"`). Fix: `_build_page_inventory` detects when Playwright confirmed genuine form inputs on a page (`_FORM_INPUT_SUBTYPES`); if so, all route_elements form entries on that page are added to `_playwright_labels` (promoted). `_resolve_element_source` then returns `"playwright"` → E=1.0. Promotion is suppressed when Playwright found only search/nav (no form inputs), so product-list pages with shallow-import form elements are not incorrectly promoted.
- **Step 6 exit-path OBV scoring inconsistency** — OBV CHECK-3 requirements ("User can leave X") scored E=0.5 even when Playwright confirmed live outbound navigation links on the page. Pass 3 auto-fallback always set `match_source = "navigation_graph"` regardless of whether Playwright observed the links. The same navbar links that gave OBV-005 `playwright_element` (E=1.0) via a lucky LLM match were ignored for OBV-003/004 because Pass 3 never checked Step 5 `outbound_links`. Fix: `run()` builds `playwright_exit_routes` — a frozenset of routes where Playwright found non-empty `outbound_links`. `_ground_requirement` receives this set as a new parameter (`playwright_exit_routes: frozenset = frozenset()`). In Pass 3 exit-path branch (`prev_route and not next_route`), if `prev_route in playwright_exit_routes`, the grounding record is written with `match_source = "playwright_element"` → E=1.0.

- **Step 11 Docker boot strategy** — Primary stack: Spring Boot (Maven/Gradle) + React (Vite/CRA/Angular/Next.js). Full boot pipeline:
  - **Pre-checks:** `_check_docker_available()` runs `docker info` first; port collision checked after dir detection (so detected ports are available).
  - **Layout detection:** `_find_dirs()` returns `(backend_dir, frontend_dir, frontend_type)`. Backend: any dir with `pom.xml`/`build.gradle`/`build.gradle.kts`. Frontend type: `"vite"` (vite.config*), `"angular"` (angular.json), `"nextjs"` (next.config*), `"cra"` (react-scripts in deps), `"generic"` (npm scripts). Searches root + 1 level deep + root-itself fallback for both backend and frontend.
  - **DB detection:** `_detect_db_type()` checks artifact IDs in pom.xml/build.gradle: `mariadb-java-client` → MariaDB, `mysql-connector-j`/`mysql-connector-java` → MySQL, `org.postgresql` → PostgreSQL. `_has_h2_dep()` covers H2 in-memory fallback. `_detect_spring_extra_env()` injects JWT_SECRET for jjwt/java-jwt/nimbus-jose-jwt, SPRING_MAIL_HOST for mail starters.
  - **Spring port detection:** `_detect_spring_port()` reads `src/main/resources/application.properties` → `server.port=XXXX` or `application.yml` → `server: port: XXXX`; default 8080. Used in compose port mapping AND vite proxy target.
  - **Frontend port detection:** `_detect_frontend_port()` reads vite.config `server: { port: XXXX }` or package.json `--port XXXX` flag; informational only (Dockerfiles still force `--port 5174`).
  - **API call style detection:** `_detect_api_call_style()` scans `.js/.ts/.tsx/.jsx` source (skipping node_modules/dist/build) and classifies how the frontend calls the backend: `"env_based"` (`import.meta.env.VITE_*` / `process.env.REACT_APP_*` / `NEXT_PUBLIC_*`), `"relative"` (`fetch('/api/...')` / `axios.get('/...')`), `"hardcoded"` (`http://localhost:PORT` literal), `"unknown"`. Priority: env_based > relative > hardcoded.
  - **Env var name scanning:** `_scan_env_var_names()` finds every `VITE_*`/`REACT_APP_*`/`NEXT_PUBLIC_*` name actually used in source. `_compose_yaml()` injects all of them as build args (union with fixed fallbacks `VITE_API_URL`, `REACT_APP_API_URL`, `NEXT_PUBLIC_API_URL`). Prevents apps using non-standard names (e.g. `VITE_API_BASE_URL`) from compiling with `undefined` as the API base.
  - **Vite proxy patching:** `_patch_vite_config(sb_frontend, spring_port, inject_proxy)` — (1) rewrites any `http://localhost:8xxx/9xxx` in existing proxy entries to `http://backend:{spring_port}`; (2) copies `server.proxy` → `preview.proxy` if `preview.proxy` absent (`vite preview` ignores `server.proxy`); (3) when `inject_proxy=True` (api_style="relative" or "hardcoded") and no proxy block exists, injects a catch-all `'/'` preview proxy with HTML bypass.
  - **Hardcoded origin stripping:** `_strip_hardcoded_origin(sb_frontend, port)` — when `api_style="hardcoded"`, removes `http://localhost:{port}` from all `.jsx/.tsx/.js/.ts` source files, converting absolute URLs to relative paths (e.g. `http://localhost:8080/api/x` → `/api/x`). Combined with the injected preview proxy, this routes all API calls through Vite preview → no cross-origin requests → Spring Boot CORS config never involved.
  - **Tailwind v4 CSS patching:** `_patch_tailwind_css(sb_frontend)` — detects `@tailwindcss/postcss` or `@tailwindcss/vite` in deps + v3-style `@tailwind base/components/utilities` directives in CSS. Replaces the directive block with `@import "tailwindcss"` (v4 syntax). Without this patch, Tailwind v4 silently produces a 0-byte CSS file.
  - **Sandbox warnings:** all three patch functions return a human-readable warning string when they fire. Warnings collected in `sandbox_warnings: list[str]` and included in the Step 11 result. Frontend `SandboxResult.tsx` renders an amber warning panel listing each patch applied, noting it represents a real defect in the submission.
  - **Compose port logic:** `_compose_yaml()` receives `spring_port`, `api_style`, `hardcoded_api_port`. Always exposes `BACKEND_HOST_PORT(8081):{spring_port}` for health polling. For `api_style="hardcoded"`: no longer exposes the hardcoded port separately (origin stripping + proxy eliminates the need for direct browser→backend calls). No extra port for relative/env_based.
  - **Dockerfiles:** Backend: Maven multi-stage (`maven:3.9-eclipse-temurin-21-alpine` build stage + `eclipse-temurin:21-jre-alpine` runtime); fat-JAR detected via `jar tf "$j" | grep "^BOOT-INF/"`. Gradle: prefers `./gradlew bootJar`. Frontend: 5 templates — Vite (build args for all detected env var names), CRA (PORT=5174), Angular (npx ng serve --port 5174), Next.js (PORT=5174), Generic. All standardise on internal port 5174.
  - **Timeouts:** `BUILD_TIMEOUT_S=420` (Maven download), `BOOT_TIMEOUT_S=240` (MySQL init + Spring Boot start), `FRONTEND_BOOT_TIMEOUT_S=60`.
  - **Sandbox dir:** `(Path(__file__).parent.parent / "jobs" / job_id / "sandbox").resolve()` — absolute path.
  - **Output adds** `db_type`, `frontend_type`, `spring_port`, `api_style`, `sandbox_warnings` fields to Step 11 result schema.
  - **UI:** `SandboxResult.tsx` — Try Again button after `boot_failed`; Run Again button after Tear Down (both call `onRetry` prop from `App.tsx`); amber warnings panel shows `sandbox_warnings` with explanation that each is a real submission defect.
  - Trigger: manual `POST /api/jobs/{job_id}/sandbox`; job status: `step_11_running` → `step_11_complete` | `step_11_error`.
- **State-variant trailing nodes/elements omitted from paths** — Trailing state-result entities at the end of a path (e.g. `Employee List Page (updated)` after a submit edge, or `filtered employee list` after a filter element) were being generated by Steps 1 and 3, appearing as `primary: false` secondaries that dragged down the secondary average and double-counted the containing page. Fix: Step 1 and Step 3 prompts updated to say "OMIT them entirely — path terminates at the last interaction element or edge." `_validate_path` in `utils.py` also strips trailing state-variant nodes (parenthetical labels) post-LLM as a deterministic safety net. Result-state elements (non-parenthetical labels like "filtered employee list") are handled by the prompt change only.

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

1. Build Step 9 — Test Generator (LLM converts Step 8.5 ACs into Playwright/Pytest scripts in Step 11's test_results schema)
2. Complete Step 11 — wire test execution once Step 9 output is available

---

## Known limitations / future scope

### Microservices
The evaluator is designed for **self-contained applications with user-facing flows**. Microservices architectures are out of scope for the MVP for two reasons:
1. Individual services are rarely self-contained enough to evaluate against user-story-level requirements — most are internally-facing and flows span multiple services
2. Steps 5 (L2 Inventory), 9 (Test Generator), and 11 (Sandbox) assume one running app with one base URL and a UI to crawl

**Future implementation:** Microservices support is a post-MVP in-place extension — do not clone the repo. The branch point is `project_type == "microservices"` from Step 0's job JSON, which already flows through the pipeline. Steps 5, 9, and 11 will need a microservices implementation path. To keep this retrofit additive (not a rewrite), ensure the **output schemas** of Steps 5, 9, and 11 remain stable and Playwright-specific logic does not leak into downstream step inputs.
