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
- LLM (claude-haiku) extracts only explicitly stated requirements; every item must include a verbatim source quote
- Source quote verification uses whitespace-normalized comparison (`_norm()`) — collapses all whitespace to single space before substring check, so LLM quote normalization (newlines → spaces) doesn't cause false drops
- JSON truncation recovery: if response is cut off mid-array, recovers items up to last complete `},`
- `excluded_docs_count` in result shows how many spec docs were found but dropped (MAX_DOCS hit)
- `functional_area` field on each requirement for cascade advisory grouping
- **Prompt design (graph model):** Extracts requirements grounded in sentences that name a specific UI element — a page/screen (by name or HTML filename), a named form, a named button/link, or a named UI component (nav bar, sidebar, data table). Subjects that are backend files, databases, or automatic processes are always skipped. Two sides of the same behavior = one requirement. `critical` flags root requirements with many dependents.
- **Extraction rule:** Extract when the sentence names a specific page, screen, form, button, or UI component as the subject or focus. Skip when the subject is app.py, a database, an automatic behavior, or a data field. Source quote must be one verbatim sentence containing that named element.

### Step 2 — Obvious Requirement Generator (COMPLETE)
- LLM generates requirements so fundamental users expect them but never write them down
- Deduplicates against Step 1 stated requirements (semantic, not just string-match)
- `functional_area` field on each requirement; passed with descriptions in user message for better semantic dedup
- `discovered_pages` from Step 0 passed to LLM as ground-truth node inventory (codebase files)
- **Prompt design (graph model):** 6-check graph traversal — (1) build node list from stated + discovered pages, (2) entry paths per node, (3) exit paths per node (mechanism-agnostic: back/breadcrumb/navbar/sidebar), (4) observable outcomes per stated operation, (5) invocation controls per stated capability, (6) status toggle only if explicit sort phrase quoted. Hard stops: auth guards, empty states, error messages, session management, filter/sort controls (Step 3), anything phrased "System must X when Y".
- **Parser:** handles LLM YES/NO reasoning text before JSON array via bracket_pos search.

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- Upload page: drag-and-drop zip + requirements textarea, file size display, validation
- Results: ClassificationResult (Step 0), RequirementsResult (Step 1), ObviousRequirementsResult (Step 2)
- Each requirement row expands to show source quote / reasoning + functional_area badge
- Job list endpoint `GET /api/jobs` lets you find the latest job_id without copying from the frontend

### Backend infrastructure (COMPLETE)
- Python 3.12 + FastAPI
- `POST /api/upload` — validates zip + requirements, creates job, starts background pipeline
- `GET /api/jobs/{job_id}` — returns job JSON
- `GET /api/jobs` — lists recent jobs (most-recent-first, default limit 10)
- Job store: one JSON file per job in `./jobs/{job_id}.json`
- Uploads stored in `./uploads/{job_id}/project.zip`
- Pipeline runs Steps 0 → 1 → 2 as async background task; status tracked in job JSON

---

## What has NOT been built yet

- Step 3 — L1b Implied Enhancement Generator
- Step 3.5 — Human Confirmation UI (pipeline pauses at `waiting_for_confirmation`)
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

1. Build Step 3 — L1b Implied Enhancement Generator (`backend/pipeline/step3_implied_generator.py`)
2. Build Step 3.5 — Human Confirmation UI (POST /api/jobs/{id}/confirm, frontend review table)
3. Build Step 4 — Repo Parser (outputs `languages`, `api_endpoints`, `database_models`)

---

## Known limitations / future scope

### Microservices
The evaluator is designed for **self-contained applications with user-facing flows**. Microservices architectures are out of scope for the MVP for two reasons:
1. Individual services are rarely self-contained enough to evaluate against user-story-level requirements — most are internally-facing and flows span multiple services
2. Steps 5 (L2 Inventory), 9 (Test Generator), and 11 (Sandbox) assume one running app with one base URL and a UI to crawl

**Future implementation:** Microservices support is a post-MVP in-place extension — do not clone the repo. The branch point is `project_type == "microservices"` from Step 0's job JSON, which already flows through the pipeline. Steps 5, 9, and 11 will need a microservices implementation path. To keep this retrofit additive (not a rewrite), ensure the **output schemas** of Steps 5, 9, and 11 remain stable and Playwright-specific logic does not leak into downstream step inputs.
