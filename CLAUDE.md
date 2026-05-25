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
- **Route extraction:**
  - Next.js: file-based walk of `pages/` or `src/pages/`; App Router walk of `app/`
  - React Router (Vite/CRA): tree-sitter TSX queries for `<Route path="..." />` (self-closing + opening element); regex fallback for object-based `createBrowserRouter`
  - SvelteKit: `+page.svelte` file walk; Vue/Angular Router: regex on router config files
- **Model extraction:** SQLAlchemy/Django (`class X(Base):`), JPA (`@Entity`), TypeORM (`@Entity()`), Mongoose (`new Schema(...)`), Prisma (`.prisma` regex)
- **Test file detection:** glob patterns (`test_*.py`, `*.test.ts`, `*Test.java`, etc.)
- **Important files:** heuristic from entry-point names + endpoint-hosting files + router/model configs
- Job statuses: `confirmed` → `step_4_running` → `step_4_complete` (or `step_4_error`)
- Frontend polls for `step_4_complete` after confirmation; `RepoParserResult.tsx` shows loading skeleton then populated result

**Step 4 output fields** (stored in `step_results.step_4`):
```
languages, frontend_routes, api_endpoints (method/path/file/handler),
database_models, important_files, existing_tests,
total_endpoints, total_routes, error
```

## What has NOT been built yet

- Steps 5–17 (see PLAN.md for full pipeline)
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
    storage/
      job_store.py                   # JSON file job persistence + list_jobs()
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob()
      types/index.ts                 # Job, Step0Result, Step1Result, Step2Result, etc.
      pages/UploadPage.tsx           # Upload form
      components/
        ClassificationResult.tsx     # Step 0 result display
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
- **Java SSR rule** — `java_fw + _has_html_views()` bypasses the `return None` early guard so Spring Boot + Thymeleaf is classified deterministically at `high` confidence without LLM. `build.gradle.kts` added to CONFIG_FILES so Gradle Kotlin DSL is readable.
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
- **Step 4 route normalisation** — all frontend routes start with `/` and have no trailing `/` (except root `/`). Routes are deduplicated within each extraction strategy. Object-based `createBrowserRouter` routes only collected from files that import `react-router-dom`.

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

1. Build Step 5 — UI/API Inventory Generator (builds L2 via Tree-sitter static pass + Playwright dynamic crawl + LLM summarization)

---

## Known limitations / future scope

### Microservices
The evaluator is designed for **self-contained applications with user-facing flows**. Microservices architectures are out of scope for the MVP for two reasons:
1. Individual services are rarely self-contained enough to evaluate against user-story-level requirements — most are internally-facing and flows span multiple services
2. Steps 5 (L2 Inventory), 9 (Test Generator), and 11 (Sandbox) assume one running app with one base URL and a UI to crawl

**Future implementation:** Microservices support is a post-MVP in-place extension — do not clone the repo. The branch point is `project_type == "microservices"` from Step 0's job JSON, which already flows through the pipeline. Steps 5, 9, and 11 will need a microservices implementation path. To keep this retrofit additive (not a rewrite), ensure the **output schemas** of Steps 5, 9, and 11 remain stable and Playwright-specific logic does not leak into downstream step inputs.
