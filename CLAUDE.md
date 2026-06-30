# CLAUDE.md — Software Quality Evaluator

Evaluates **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user requirements. Scores are formula-driven — LLM explains results, never overrides them. See `PLAN.md` for full pipeline design and scoring formulas.

---

## What has been built

### Step 0 — Project Type & Scope Classifier (COMPLETE)
- User uploads `.zip` + requirements text via React frontend; backend creates job, runs Step 0 in background
- Rule-based first (config files + extension counts); LLM (claude-haiku, prompt caching) only when confidence is medium or rules produce no match
- `test_strategy` always formula-derived from `project_type` + `backend_framework` — LLM never overrides it
- Root-level Python check: Python configs only at depth 2+ are ignored — prevents sub-service `requirements.txt` from falsely determining `backend_framework`
- SSR detection: Flask/Django/Express/PHP + `templates/`/`views/` → `full_stack_web_app`. Engine-specific extensions (`.ejs`, `.twig`, `.blade.php`, `.pug`, `.hbs`, `.njk`, `.jinja2`) are unambiguous SSR signals regardless of directory
- SPA frontend suppresses SSR: when `frontend_fw` ∈ `_SPA_FRAMEWORKS` (React, Vue, Angular, Svelte, etc. — not Next.js/Nuxt/SvelteKit/Remix/Gatsby), `template_engine` forced to `null` — prevents Thymeleaf from being reported for Spring Boot + React projects
- Service layout flex matching: `_matches` checks `startswith`/`endswith` with `-`/`_`/` ` separators — "frontend src", "Ecommerce-Frontend" match "frontend". SPA in frontend-named subdir + non-frontend backend → `"separate_frontend_backend"`
- Service layout zip-wrapper unwrap: single root wrapper dir (e.g. `SpringBoot-Reactjs-Ecommerce-main/`) triggers one-level deeper scan so `top_dirs` of size 1 doesn't block keyword matching
- Java full-stack (JS + Java): React/Angular/Vue + Spring Boot/Quarkus/Micronaut + `pom.xml`/`build.gradle` → `full_stack_web_app` at `high` confidence without LLM
- Java full-stack (SSR): Spring Boot + `build.gradle.kts` + HTML templates in `src/main/resources/templates/` → `full_stack_web_app`, `template_engine = "Thymeleaf"`. Only fires when no SPA frontend detected
- Mobile apps: React Native / Expo → `mobile_app` (not `frontend_only`)
- Production deps only: `backend_fw_js` uses `dependencies` not `devDependencies` — prevents Express dev mock servers from misclassifying a React SPA as `backend_api_only`
- IGNORE_DIRS: `examples`, `demo`, `sample`, `demos`, `samples`, `assets` excluded from file walk
- Static site: HTML present + no backend language → `static_site` at `medium` confidence without LLM
- React confidence: `react` in deps but no `.jsx`/`.tsx` source files → `medium` confidence → LLM review
- `_discover_pages()` finds page filenames from file tree: HTML in `templates/`/`views/`, `.tsx/.jsx/.vue/.svelte` in `pages/`/`screens/`, SSR template extensions, Android `*Activity.java/kt`
- Tests: `backend/tests/test_step0_classifier.py` — 12 fixtures, all passing

**Output** (`step_results.step_0`):
```
project_type, frontend_framework, frontend_tooling, backend_framework,
template_engine, service_layout, server_routes_detected,
confidence, reasoning, test_strategy,
config_files_found, llm_used, llm_model, discovered_pages, runtime (electron only)
```
`primary_language` is NOT in Step 0 — Step 4 produces the authoritative `languages` array.

### Step 1 — Stated Requirement Extractor (COMPLETE)
- Scans zip for README (depth ≤ 2) + spec docs (keyword-matched .md/.rst/.txt); ignores `.claude`, `.cursor`, `.github`, `.vscode`, `.idea`
- MAX_DOCS = 30, MAX_CHARS_PER_DOC = 12000
- LLM (claude-haiku) extracts stated requirements as **functions** ("User can [action]") + `project_summary` (2–3 sentences) in one call. Every function requires a verbatim source quote
- **Extraction gate (actor + action):** qualifies only if the user is the subject performing a deliberate UI action. Observation statements ("User sees error") and system-triggered behaviors ("System hashes passwords") fail — routed to Step 8, not here
- **Screenshot pages:** `### Page Name` heading immediately followed by a screenshot image → single-node function "User can access [Page Name]"
- **Function+path model:** each function has `path: PathEntity[]` — `{type: node|element|edge, label, primary: bool, ui_node?, from?, to?}`. `primary: true` = entity asserted by this function (scored if absent); `primary: false` = context already asserted by another function
- **State-variant nodes** (parentheticals like "(filtered)", "(updated)") omitted from path arrays entirely — `_validate_path` strips any that slip through post-LLM
- Source quote verification: whitespace-normalized (`_norm()`) — collapses all whitespace to single space
- JSON truncation recovery: recovers items up to last complete `},` if response is cut off
- `functional_area` field on each function for cascade advisory grouping
- `project_summary` passed to Step 3 for INF domain inference

### Step 2 — Obvious Requirement Generator (COMPLETE)
- LLM finds graph connectivity gaps: pages unreachable (CHECK 2) or with no exit (CHECK 3)
- Node inventory built from Step 1 path arrays via `_extract_nodes_from_paths()` (state-variant labels excluded). `discovered_pages` from Step 0 shown to LLM as page-file context
- **Output format:** CHECK 2 → `edge {primary: true, from: null}` + destination node `{primary: false}`; CHECK 3 → source node `{primary: false}` + exit edge `{primary: true, to: null}`
- `_validate_and_normalise`: drops items whose `reasoning` doesn't start with "CHECK 2" or "CHECK 3"; enforces null from/to; rebuilds description from path (LLM cannot invent specific pages)
- **Root node detection:** (1) only one stated node in all paths → root; (2) `discovered_pages = ["index.html"]` + at least one stated node → first node is root. Root injected as `=== ROOT / HOME PAGE ===` — LLM skips CHECK 2 for it
- `depends_on` lists the REQ-XXX ids that make each obvious function necessary
- Parser handles LLM YES/NO reasoning text before JSON array via bracket_pos search

### Step 3 — Generated Requirement Generator (COMPLETE)
- LLM generates L1a candidates (confidence ≥ 0.80) and L1b advisory items (< 0.80)
- **Pass 1 — SOP (`category: "sop"`):** Conservative — fires only on pattern table, no freelancing. Patterns: list node → filter ~0.82, search ~0.80, sort ~0.68; detail node → edit ~0.85 (L1a), delete ~0.82 (L1a); create/add stated → edit ~0.85, delete ~0.82; auth present → account management ~0.87; named changeable status → cross-status overview ~0.75, filter-by-status ~0.82; temporal field → time-scoped view ~0.75; mutable records → audit/history ~0.60; preferences → settings ~0.82; deadlines → notification ~0.65; multi-user → profile ~0.82
- **Pass 2 — INF (`category: "inf"`):** Reads `project_summary` + stated functions. Bold (0.50–0.70) across 7 angles: (1) recurring use, (2) workflow/onboarding, (3) data management, (4) domain standards, (5) discoverability/help, (6) user control/settings, (7) overview/insight
- **Pass 3 — dedup (`_dedup_generated`):** Separate LLM call; receives full set (stated + obvious + all generated); drops duplicates, sub-steps, and generated-vs-generated redundancy. **Fails open** — any parse error keeps all generated. Generation passes carry no dedup prose — all dedup centralised here
- **Path construction:** elements/edges always `primary: true`; nodes always `primary: false` (exception: sole-purpose page-exists function → node is `primary: true`). State-variant trailing nodes/elements omitted entirely
- **Confidence → placement:** ≥0.80 → `l1a`; 0.60–0.79 → `l1b` strongly_implied (w=3.0); 0.40–0.59 → `l1b` medium (w=2.0); <0.40 → `l1b` weak (w=1.0)
- `depends_on`: REQ-xxx IDs only — OBV-xxx are not valid targets. Validated against `valid_step1_ids` in `_validate_and_normalise`
- LLM emits only 8 fields (`description`, `path`, `category`, `confidence_score`, `reasoning`, `priority`, `depends_on`, `functional_area`); deterministic fields computed in Python
- **Root node detection:** same as Step 2 — injects `=== ROOT / HOME PAGE ===` to prevent phantom landing page generation

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- **PathDisplay component:** shared path badge renderer — node=sky, element=violet, edge=amber; secondary entities at 40% opacity; edges show `from → to`
- Components: `ClassificationResult` (Step 0), `RequirementsResult` (Step 1), `ObviousRequirementsResult` (Step 2), `GeneratedRequirementsResult` (Step 3, L1a green / L1b yellow panels), `ConfirmationTable` (Step 3.5), `RepoParserResult` (Step 4), `AppCrawlerResult` (Step 5), `MappingResult` (Step 6), `ScoringResult` (Step 7), `FA75AdvisorResult` (Step 7.5), `CorrectnessConfirmation` (Step 8/8.5), `ACResult` (Step 8.5), `SandboxResult` (Step 11)
- `GET /api/jobs` lets you find latest `job_id` without copying from the frontend

### Backend infrastructure (COMPLETE)
- Python 3.14 + FastAPI (port 8000)
- `POST /api/upload` — validates zip + requirements, creates job, starts Steps 0–3 background chain
- `GET /api/jobs/{job_id}` — returns job JSON; `GET /api/jobs` — lists recent jobs
- `POST /api/jobs/{job_id}/terminate` — cancels pipeline. **All step chains go through `task_registry.launch(job_id, coro)`** (Steps 0–3, 4–7.5, 8/8.5, 11). `task_registry.cancel(job_id)` raises `CancelledError` (a `BaseException`) at the current `await`, force-aborting in-flight LLM calls. `except Exception` handlers don't swallow it — `terminated` status survives. `asyncio.to_thread` work (Step 5, Step 11 docker) finishes naturally; `finally` tears down. `job_store.is_terminated()` guards prevent late steps writing `step_X_complete` over `terminated`
- Frontend Terminate button: `terminated` + `step_3_5` present → results stay visible; `terminated` without `step_3_5` → `LoadingView` with `isTerminated=true`. Confirmed-stage termination: `ConfirmationTable` stays visible, action bar replaced by "Pipeline terminated" notice
- Job store: one JSON file per job in `./jobs/{job_id}.json`
- Pipeline: Steps 0→1→2→3 chain (terminal: `step_3_complete`); Steps 4→5→6→7→7.5 chain after confirmation (terminal: `step_7_5_complete`)

---

### Step 3.5 — Human Requirement Confirmation + Data Consolidation (COMPLETE)
- Pipeline pauses at `waiting_for_confirmation`; `POST /api/jobs/{job_id}/confirm` writes result and resumes
- **Single consolidation point** — Steps 4+ read only from `step_3_5`. `depends_on` and `source_quote` looked up server-side by `req_id` — frontend does not pass them
- `ConfirmationTable.tsx`: Section 1 (L1a pre-included, priority dropdown updates weight live), Section 2 (L1b promotable), Section 3 (inline add → `CUSTOM-001` IDs)
- Action bar: **Skip** (stated + obvious only, `skipped=true`) and **Confirm (N in score)**

**Output** (`step_results.step_3_5`):
```
confirmed_requirements[] (req_id, description, path[], depends_on, source_quote, weight),
advisory_requirements[] (req_id, description, path[], strength, weight, confidence_score),
project_context {project_type, frontend_framework, frontend_tooling, backend_framework,
  template_engine, service_layout, server_routes_detected, discovered_pages, test_strategy, runtime},
project_summary, confirmed_at, skipped, l1a_count, promoted_count, deleted_count, added_count
```

### Step 4 — Repo Parser (COMPLETE)
- No LLM — Tree-sitter AST + regex. Triggered after Step 3.5 confirmation. Reads `step_3_5.project_context`
- **Tree-sitter 0.25 API:** `Query(lang, pattern)` + `QueryCursor(query).matches(node)` — `lang.query()` is deprecated. Language + Query objects created once at module import, not per-file
- **JSX vs TSX queries:** `.jsx`/`.js` files use `_Q_JS_ROUTE_*` compiled against `_LANG_JS`; `.tsx` uses `_Q_TSX_ROUTE_*` against `_LANG_TSX` — silently returns nothing if mismatched
- **Spring Boot:** `_backend_spec` and `_find_frontend_dir` search root + 2 levels deep (projects often extracted into a wrapper directory)
- **Endpoint extraction:** Flask/FastAPI (tree-sitter `decorated_definition`); Django (`urls.py` regex); Spring Boot (class-level `@RequestMapping` base + method-level `@GetMapping` etc., Kotlin regex fallback); Express/NestJS (`.js/.ts` regex)
- **`_build_route_to_files`:** single pass — discovers routes AND maps them to source files. Priority: Next.js pages/ → Next.js app/ → SvelteKit → React Router JSX + `createBrowserRouter` → Vue/Angular Router → SSR endpoint fallback → static HTML fallback. `_expand_with_shallow_imports` adds 1-level-deep child imports for element extraction
- **`route_elements`:** L3 element inventory. `_strip_comments()` runs before extraction (removes `{/* */}` JSX block comments + `//` line comments — dead/commented-out code causes false matches). Button labels: `rsplit('>', 1)` to skip past `=>` in arrow functions; JSX ternaries resolved to first quoted string. Input `_JSX_INPUT_RE`: uses `(?:[^>{}]|\{(?:[^{}]|\{[^{}]*\})*\})*?` so `>` inside `{...}` doesn't terminate the match (fixes `onChange={(e)=>...}` silently dropping `placeholder`)
- **Flask/Django SSR `frontend_routes`:** falls back to GET endpoint paths (not template filenames) when `frontend_fw` is empty — template files (layouts/partials/macros) would appear as fake routes and `/` root was missing
- **React SPA / Electron:** `App.tsx`/`App.jsx` added to `route_to_files['/']` so `_extract_route_elements` reads real JSX, not the empty HTML shell
- **Blade/Jinja/Twig form actions:** `{{ route('...') }}` expressions → `path=None` in `implementation_units`
- **`navigation_graph`:** L3 nav graph from `<Link to>`, `<a href>`, `navigate()`, `router.push()`, `history.push()`
- **`implementation_units`:** `api_endpoints` wrapped as `kind: "api_endpoint"` + HTML `<form method="POST/PUT/DELETE">` in SSR templates as `kind: "form_handler"`. Step 6 unlinked uses `[u for u in implementation_units if u["kind"] == "api_endpoint"]`
- Route normalisation: starts with `/`, no trailing `/` (except root `/`), deduplicated per strategy
- Tests: `backend/tests/` — see test files in project structure

**Output** (`step_results.step_4`):
```
frontend_routes[] ({path, dynamic, params[]}),
implementation_units[] (kind, method, path, file, handler),
route_elements {route: [{type, subtype, label}]},
navigation_graph {route: [target_routes]},
route_to_files {route: [files]}, important_files[],
database_models[], existing_tests[], languages[],
total_endpoints, total_routes, error
```

### Step 5 — App Crawler (COMPLETE)
- No LLM — Playwright live crawl only; L3 element inventory owned by Step 4
- **Windows SelectorEventLoop fix:** `sync_playwright` wrapped in `asyncio.to_thread` — uvicorn's `SelectorEventLoop` cannot run subprocesses, so async Playwright would silently fail. Dev server uses `subprocess.Popen` (non-async). npm commands wrapped via `_wrap_npm_cmd()` (`cmd /c` required for `.cmd` files on Windows)
- **npm SSL (npm 11.x):** `--strict-ssl=false` flag on npm install. `NODE_TLS_REJECT_UNAUTHORIZED=0` does NOT work — npm 11.x uses undici (not Node's TLS stack). Without this, npm install fails silently → `boot_failed`
- **Ports** (avoid DSTA collision on 8000/5173): Vite→5174, CRA→3000, backend→8001, Flask→5001, Express→3001, static→8082
- **`extract_to` path fix:** stored as relative path in job JSON → `confirm.py` calls `.resolve()` before passing to background task; `step5_app_crawler.run()` also calls `Path(extract_to).resolve()` at top
- **Playwright SSL:** `browser.new_context(ignore_https_errors=True)`; httpx port-poll client: `verify=False`
- **boot_failed:** if port doesn't respond within 60s, ALL routes become `static_fallback` with `reason: "boot_failed"` — no partial crawl
- **Non-SSR full-stack boot:** when `service_layout != "separate_frontend_backend"`, checks `template_engine is None and frontend_fw` first → boots SPA directly via `_find_frontend_dir` + `_npm_cmd`. SSR apps (`template_engine` set) go through `_backend_spec`. Without this, Spring Boot `mvnw.cmd` would be found and attempted, causing `boot_failed`
- Port poll: httpx GET every 1.5s, 60s timeout (extra install+boot time)
- Playwright crawl: `page.goto(route, wait_until="load")` → `page.wait_for_load_state("networkidle", timeout=5_000)` best-effort (silently proceeds for polling/WebSocket apps) → 400ms settle. JS injected to extract interactive elements; label priority: aria-label → placeholder → textContent → title → name
- **File `<input type="file">` label:** walks to previous sibling `<label>` or parent's first `<label>` (no aria-label/placeholder/textContent available)
- **ARIA role capture:** Pass 2 in `_JS_EXTRACT_ELEMENTS` iterates 9 roles (`button`, `link`, `checkbox`, `radio`, `switch`, `tab`, `combobox`, `searchbox`, `menuitem`) — captures `<div role="button">` etc. that native `querySelectorAll` misses. Dedup key uses `elemType` (not raw tag)
- Accessibility check: final URL path matches requested route → `accessible: true`; redirect to /login etc. → `accessible: false, reason: "auth_required"`
- Auth-gated/unvisitable routes: `_static_page()` with `discovered_by: "static_fallback"` and `elements: []`; Step 6 falls back to Step 4 `route_elements` (E=0.75 for elements/edges, 0.5 for nodes)
- `_npm_install_if_needed`: runs `npm install --prefer-offline --strict-ssl=false` when `node_modules/` absent

**Output** (`step_results.step_5`):
```
pages[] (route, title, discovered_by, accessible, elements[], outbound_links[], api_calls_observed[]),
unvisitable_routes[] (route, reason), total_pages, error
```
Element schema: `{type, subtype, label, selector, visible}` — `elements: []` for `static_fallback` pages

### Step 6 — Entity Mapper (COMPLETE)
- LLM (claude-haiku) — one call per requirement (L1a + L1b), concurrent via `asyncio.gather`. Per-call `try/except` returns `[{}] * len(path)` (E=0 for all entities) on failure without aborting others
- **Step 6a (grounding):** scoped inventory per requirement (candidate routes from node labels, elements from `page_inventory`, `implementation_units`, `nav_inventory`); LLM matches each path entity to an inventory item
- **Grounding prompt improvements:** routes annotated with top-5 element labels; all routes included when app has ≤10 routes (avoids silently omitting the relevant route); node instruction prioritises content-based matching over literal name match
- **Step 6b (scoring):** deterministic piecewise E() by entity type:

| Entity type | Playwright (L2) | L3 only | None |
|---|---|---|---|
| node | 1.0 (accessible) | 0.5 (static_fallback) | 0.0 |
| element | 1.0 | 0.75 (route_elements) | 0.0 |
| navigation_edge | 1.0 | 0.75 (nav_graph) | 0.0 |
| structural_edge | 1.0 | 0.75 (route_elements) | 0.0 |
| data_edge | 1.0 (endpoint+trigger) | 0.75 (endpoint only) | 0.4 (trigger only) / 0.0 |

- **Aggregation:** `E(req) = 0.7×[primary_avg] + 0.3×[secondary_avg]` (α=1.0 if no secondary)
- **Edge classification** (`_classify_edge_kind` in `utils.py`): data keywords (submit/add/create/delete/update/save/…) → `data_edge`; structural (filter/search/sort/drag/reorder) → `structural_edge`; else → `navigation_edge`
- **`_match_node_to_route()` deterministic fallback:** word-overlap scoring; runs OUTSIDE the try/retry loop (fires regardless of LLM success/failure); only fires when LLM returned null. PascalCase split via `_SPLIT_CAMEL_RE`; state-variant parentheticals stripped. Bonuses: list/search labels → `_ROUTE_LIST_PATHS` +4; detail/edit + dynamic route +4; home + "/" +3; `_ROUTE_AUTH_PATHS` suppresses list/detail bonuses. Threshold 3 rejects false positives
- **`page_inventory`:** Playwright-accessible pages use live DOM (source=`playwright`, E=1.0); static_fallback/auth-gated fall back to `route_elements` (source=`route_elements`, E=0.75)
- **Conditionally-rendered elements** (e.g. Delete/Edit buttons that only appear when backend data loads): `_build_page_inventory` merges `route_elements` entries not found by Playwright, tagged `_fallback_source: "route_elements"`. `_resolve_element_source()` checks `_playwright_labels` set → E=1.0 or 0.75
- **`_match_element_in_inventory()`:** deterministic word-overlap fallback applied in Pass 2 after LLM call; uses last resolved node route as context
- **Navigation edges (Pass 3):** auto-scored from `nav_inventory` when adjacent routes known — prev→next if nav_graph has edge; any reachable target if only prev_route known; any source pointing to next_route if only next_route known
- **Data edges (Pass 4):** infers HTTP verb from label keywords (submit/update→PUT, delete→DELETE, create/upload→POST); accepts lone candidate even with score=0 when verb uniquely identifies one endpoint
- **`_DOT_LABEL_RE`:** filters `product.name`-style labels from `_build_page_inventory` and `_match_element_in_inventory` — dot-notation labels are never valid UI labels
- **Form-confirmation promotion:** when Playwright confirms genuine form inputs (`_FORM_INPUT_SUBTYPES`) on a page, all `route_elements` form entries on that page added to `_playwright_labels` → E=1.0. Suppressed when Playwright found only search/nav
- **Exit-path OBV (CHECK-3):** `run()` builds `playwright_exit_routes` frozenset (routes with non-empty `outbound_links`). Pass 3 exit-path branch: if `prev_route in playwright_exit_routes` → `match_source = "playwright_element"` → E=1.0
- **`_candidate_routes` heuristic:** node labels matched against routes by substring/word similarity; root "/" always included; all routes when app has ≤10; limits element inventory scope for LLM call
- **Unlinked detection:** `unlinked_l2` = accessible routes matched by no L1a node entity; `unlinked_l3` = `api_endpoint` implementation_units matched by no L1a data edge
- Tests: `backend/tests/test_step6_entity_mapper.py` — 59 tests, all passing

**Output** (`step_results.step_6`):
```
mapped[] (req_id, description, e_score, entity_scores[]),
unlinked_l2[] (route, title, note), unlinked_l3[] (method, path, handler, file, note),
llm_model, error
```

### Step 7 — FCom/FA Scorer (COMPLETE)
- No LLM — pure Python formula
- **FCom:** `∑(E×weight) / ∑weight` over all L1a confirmed requirements
- **FA:** same formula over all L1b advisory requirements
- **Advisories:** `missing_l1a`/`missing_l1b` = requirements with `e_score < 0.5`, sorted ascending. `unlinked_routes`/`unlinked_endpoints` passed through from Step 6
- Tests: `backend/tests/test_step7_scorer.py` — 15 tests, all passing

**Output** (`step_results.step_7`):
```
fcom, fa,
fcom_detail (numerator, denominator, requirement_count), fa_detail,
fcom_advisory (missing_l1a[], unlinked_routes[], unlinked_endpoints[]),
fa_advisory (missing_l1b[]), error
```

### Step 7.5 — Positive-Grounded FA Advisor (COMPLETE)
- LLM (claude-haiku) — one call; reads Steps 3.5, 4, 5 directly (does NOT depend on Step 6)
- Generates Type B advisory: improvement suggestions grounded in actual codebase (models, endpoints, UI) vs Type A domain-normative patterns from Step 7
- Dedup against L1b: all Step 3 advisory L1b items (capped at 25) included in user message
- Positive inventory: `database_models`, `api_endpoints` from `implementation_units`, `frontend_routes`, Step 5 live elements (up to 15 pages × 6 labels)
- **Array extraction:** parser is fence/prose-tolerant — slices from first `[` to **last** `]` (drops trailing ` ```json ` fence Haiku reliably adds). Falls back to `_recover_truncated`: brace-aware walk tracking string state + object depth, truncates after last complete top-level object
- Suggestion IDs renumbered sequentially after parsing regardless of LLM output
- Tests: `backend/tests/test_step7_5_fa_advisor.py` — 26 tests, all passing

**Output** (`step_results.step_7_5`):
```
suggestions[] (suggestion_id, description, grounded_in{models[], endpoints[], rationale},
  l1a_connection, priority),
total_count, llm_model, error
```

### Step 8 — Behavioral Requirement Generator (COMPLETE)
- LLM (claude-haiku). `POST /api/jobs/{job_id}/behavioral` — requires `step_7_5` complete; caches on re-POST; status `step_8_running` → `step_8_complete`
- **Orphan autonomous behaviors:** extracts state changes/triggered actions that occur WITHOUT user-initiated UI action (auto-reset, scheduled notifications, session/cache expiry, background sync). These correctly fail Step 1's actor+action gate; live here as `BEH-xxx`
- **Negative grounding:** prompt includes all confirmed + advisory requirements + all `api_endpoints` from `step_4.implementation_units` — LLM skips behaviors with a matching user-triggerable endpoint
- `req_id` counter uses `len(results)+1` (not enumerate) so invalid/skipped items don't offset BEH numbering
- Every BEH requirement gets fixed path `[{type: "node", label: "System", primary: True}]`
- Priority weights: critical=4.0, high=3.0, medium=2.0, low=1.0
- Tests: `backend/tests/test_step8_behavioral_gen.py` — 17 tests, all passing

**Output** (`step_results.step_8`):
```
behavioral_requirements[] (req_id, description, path, priority, weight, source_quote),
llm_model, error
```

### Step 8.5 — AC Generator (COMPLETE)
- Hybrid deterministic + concurrent LLM. `POST /api/jobs/{job_id}/acs` `{selected_ids: [...]}`. Per-req caching — re-POST merges new IDs. Status `step_8_5_running` → `step_8_5_complete`
- **FCor orthogonality:** reads only `step_3_5` + `step_8` — never reads Step 6 `e_score`
- **Goal kind** (`_classify_goal_kind`): scans path edges by keyword precedence data > structural > navigation > presence (no edges). `BEH-xxx` prefix → `behavioral`
- **Data verb sub-classification:** delete > create > update precedence on edge labels
- **AC slot sets:**
  - `data` → [happy_path 0.5, persistence 0.3, edge_case 0.2]
  - `structural` → [happy_path 0.7, edge_case 0.3]
  - `navigation` / `presence` → [happy_path 1.0]
  - `behavioral` → [fires_when_due 0.6, not_before_due 0.4]
- **`_compute_acws`:** `acw_i = round(frac_i × W, 2)`; last AC absorbs rounding remainder so `Σacw == W` exactly
- **AC ID format:** REQ-001 → AC-001-1; OBV-001 → AC-OBV-001-1; GEN-005 → AC-GEN-005-3; BEH-001 → AC-BEH-001-1; CUSTOM-001 → AC-CUSTOM-001-1
- **`_test_type`:** behavioral → `"behavioral"`; data + API-only test strategy (no "e2e") → `"api"`; else → `"e2e"`
- `_classify_edge_kind` shared in `pipeline/utils.py`; Step 6 imports from there
- Placeholder GWT: missing LLM slots filled with `"[LLM did not generate this AC]"` so output length always matches slot count
- Tests: `backend/tests/test_step8_5_ac_generator.py` — 46 tests, all passing

**Output** (`step_results.step_8_5`):
```
acceptance_criteria[] (req_id, description, type, goal_kind, l1cx, test_type,
  acceptance_criteria[]: {ac_id, given, when, then, acw, type}),
selected_ids, total_acs, llm_model, error
```

**Correctness screen navigation:**
- Hash routing: `#<jobId>` = presence view (Steps 0–7.5); `#<jobId>/correctness` = correctness screen (Steps 8/8.5)
- `canRunCorrectness = !!(step_results.step_7_5)` — sidebar FCor header glows (`animate-pulse`, indigo) when unlocked
- `handleNavCorrectness()`: sets hash, sets stage to `'correctness'`, fires `generateBehavioral()` (POST /behavioral)
- Hash restore on mount: `view === 'correctness'` + `step_7_5` present → sets stage to `'correctness'`

## What has NOT been built yet

- Steps 9–10, 12–17 (see PLAN.md)
- Step 11 test execution (Docker boot is complete; test scripts require Steps 9–10)

---

### Step 11 — Sandbox (COMPLETE — Docker boot only)
- `POST /api/jobs/{job_id}/sandbox`. Primary stack: Spring Boot (Maven/Gradle) + React (Vite/CRA/Angular/Next.js)
- **Detection:** `_find_dirs()` searches root + 1 level deep + root-itself fallback. `_detect_db_type()` checks pom.xml/build.gradle artifact IDs (mariadb/mysql/postgresql). `_detect_spring_port()` reads `application.properties`/`.yml` (default 8080). `_detect_api_call_style()` classifies as `env_based`/`relative`/`hardcoded`/`unknown`; scans `.js/.ts/.tsx/.jsx` skipping node_modules/dist/build. `_scan_env_var_names()` finds every `VITE_*`/`REACT_APP_*`/`NEXT_PUBLIC_*` used in source — all injected as Docker build args
- **Patches (each returns warning string → `sandbox_warnings[]` — each is a real submission defect):**
  - `_patch_vite_config`: rewrites `http://localhost:8xxx` in proxy entries → `http://backend:{spring_port}`; copies `server.proxy` → `preview.proxy`; injects catch-all `'/'` preview proxy when api_style="relative"/"hardcoded"
  - `_strip_hardcoded_origin`: when api_style="hardcoded", removes `http://localhost:{port}` from all source files → relative paths; combined with proxy = no CORS issues
  - `_patch_tailwind_css`: detects v4 deps + v3-style `@tailwind` directives → replaces with `@import "tailwindcss"` (v4 syntax); without this Tailwind v4 produces 0-byte CSS
- **Dockerfiles:** Backend: Maven multi-stage (`maven:3.9-eclipse-temurin-21-alpine` + `eclipse-temurin:21-jre-alpine`); Gradle: `./gradlew bootJar`. Frontend: 5 templates (Vite/CRA/Angular/Next.js/Generic), all standardise on internal port 5174
- **Timeouts:** BUILD=420s, BOOT=240s (MySQL init + Spring Boot), FRONTEND_BOOT=60s
- Job status: `step_11_running` → `step_11_complete` | `step_11_error`

**Output** (`step_results.step_11`):
```
status, db_type, frontend_type, spring_port, api_style, sandbox_warnings[], error
```

---

## Key technical decisions

- **AsyncAnthropic + `cache_control: ephemeral`** on system prompts — fast/cheap for repeated LLM calls across pipeline steps
- **Step 0 uses tool use** (not free-form JSON) — `CLASSIFICATION_TOOL` with enum-constrained schemas; `tool_choice` forces the tool; Python plucks each LLM field by name; all other fields computed deterministically
- **JSON files per job** in `./jobs/` — no database for MVP; easy to inspect mid-session
- **Async background task** (FastAPI `BackgroundTasks`) — upload returns immediately with `job_id`; frontend polls
- **Python 3.14** — venv at `backend\venv`; pydantic-core installs from prebuilt wheel (no Rust toolchain needed)
- **Formula-driven scores** — FCom/FA: `∑(E×w)/∑w`, output 0–1. Step 17 multiplies by 5 for display. LLM never overrides
- **Weight chain** — L1a weight from priority (critical=4, high=3, medium=2, low=1), editable at Step 3.5. L1b weight from `confidence_score` → strength (≥0.80→l1a; 0.60–0.79→3.0; 0.40–0.59→2.0; <0.40→1.0). `confidence_score` not used in any formula after this point
- **Step 3.5 as consolidation gate** — Steps 4+ read only from `step_3_5`; Steps 0–3 outputs fully subsumed
- **Test strategy rule** — for `backend_api_only`, primary is always the HTTP-level test tool (Pytest API / Supertest / JUnit MockMvc / PHPUnit / RSpec), never a unit test runner. Secondary is `null` for API-only; backend tool for full-stack (Playwright primary + backend secondary)
- **Function+path model** — requirements are "User can [action]" functions with `path: PathEntity[]`. `primary: true` = scored if absent. `E(req) = 0.7×primary_avg + 0.3×secondary_avg`
- **FCom / FA / FCor orthogonal** — Steps 4–7 = presence (no test execution). Steps 8–11 = correctness. FCom locked after Step 7; FCor never updates E() scores. `_classify_edge_kind` shared via `utils.py`
- **task_registry.launch()** — all step chains registered; `cancel()` raises `CancelledError` (BaseException, not swallowed by `except Exception`); force-aborts in-flight LLM calls
- **5 entity types** — node, element, navigation_edge, data_edge, structural_edge. L3 (Step 4 static) = 0.75, L2 (Step 5 Playwright) = 1.0. Structural edges never check `implementation_units`
- **Step 5 is passive crawl only** — Playwright visits routes on page load; does NOT fill forms or click buttons. `api_calls_observed` is supplementary only, not an E() source. **Step 9 does NOT use Step 5 selectors** — Step 9 generates `getByRole`/`getByText`/`getByPlaceholder` locators from path entity labels via LLM (CSS selectors from Playwright DOM are unreliable due to CSS-in-JS/component libraries)
- **playwright install chromium** — must be installed in DSTA backend venv: `NODE_TLS_REJECT_UNAUTHORIZED=0 python -m playwright install chromium`. Stored in `C:\Users\Owner\AppData\Local\ms-playwright\`

---

## Project structure

```
c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\
  backend/
    main.py                          # FastAPI entry point (port 8000)
    .env                             # ANTHROPIC_API_KEY, UPLOAD_DIR, JOBS_DIR (not committed)
    .env.example
    requirements.txt
    api/routes/
      upload.py                      # POST /api/upload — starts Steps 0–3
      jobs.py                        # GET /api/jobs, GET /api/jobs/{job_id}
      confirm.py                     # POST /api/jobs/{job_id}/confirm — starts Steps 4–7.5
      correctness.py                 # POST /api/jobs/{job_id}/behavioral, /acs
      sandbox.py                     # POST /api/jobs/{job_id}/sandbox
    pipeline/
      step0_classifier.py
      step1_req_extractor.py
      step2_obvious_generator.py
      step3_implied_generator.py
      step4_repo_parser.py
      step5_app_crawler.py
      step6_entity_mapper.py
      step7_scorer.py
      step7_5_fa_advisor.py
      step8_behavioral_gen.py
      step8_5_ac_generator.py
      step11_sandbox.py
      utils.py                       # _classify_edge_kind, _validate_path, shared helpers
    storage/
      job_store.py
    tests/
      test_step0_classifier.py       # 12 fixtures
      test_step6_entity_mapper.py    # 59 tests
      test_step7_scorer.py           # 15 tests
      test_step7_5_fa_advisor.py     # 26 tests
      test_step8_behavioral_gen.py   # 17 tests
      test_step8_5_ac_generator.py   # 46 tests
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob(), generateBehavioral(), generateACs()
      types/index.ts                 # Job, Step0Result…Step85Result, BehavioralRequirement, ACRequirementResult, etc.
      pages/UploadPage.tsx
      components/
        ClassificationResult.tsx
        RequirementsResult.tsx
        ObviousRequirementsResult.tsx
        GeneratedRequirementsResult.tsx
        PathDisplay.tsx              # Shared path badge renderer
        ConfirmationTable.tsx
        RepoParserResult.tsx
        AppCrawlerResult.tsx
        MappingResult.tsx
        ScoringResult.tsx
        FA75AdvisorResult.tsx
        CorrectnessConfirmation.tsx
        ACResult.tsx
        SandboxResult.tsx
        Sidebar.tsx
      App.tsx                        # Stage state machine + hash routing (#jobId / #jobId/correctness)
  uploads/                           # Runtime — gitignored
  jobs/                              # Runtime — gitignored
  docs/
    step0-edge-case-audit.md
  PLAN.md
  CLAUDE.md
```

---

## How to run locally

### Backend (port 8000)
```bash
cd c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\backend
venv\Scripts\activate
uvicorn main:app --reload
```

### Frontend (port 5173)
```bash
cd c:\Users\Owner\OneDrive\Documents\GitHub\DSTA\frontend
npm run dev
```

**npm SSL (corporate proxy):** `npm config set strict-ssl false` or copy `package-lock.json` from a working machine.

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

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
- Design/formulas/output schemas changed → update `PLAN.md`
- Steps built/fixed/paths changed → update `CLAUDE.md`

Both files in the same commit as the code. The local `~/.claude/projects/*/memory/` directory is machine-local only — do not rely on it for cross-session rules.

---

## Next steps

1. Build Step 9 — Test Generator (LLM converts Step 8.5 ACs into Playwright/Pytest scripts in Step 11's test_results schema)
2. Complete Step 11 — wire test execution once Step 9 output is available

---

## Known limitations / future scope

**Laravel:** no PHP/web.php route parser or Eloquent model extractor; `frontend_routes=[]`, Step 5 returns non-fatal "No frontend routes" error.  
**React SPA / Electron (no router):** `frontend_routes=['/']`; `route_elements['/']` includes App component elements via shallow import expansion but misses deeper child components. Step 5 Playwright provides full L2 picture if app boots.  
**Flask SSR `route_to_files['/']`:** only contains `app.py` when root template is not named `index.html`; `route_elements['/']` extracts from Python source (no HTML elements).  
**Step 0 open issues:** (1) Laravel `frontend_fw=None` → Step 4 produces no routes; (2) Electron/React SPA with no router → Step 5 gets 0 elements; (3) Monorepos with Android sub-apps: Java counted in `languages` correctly but it is not Spring Boot Java.

### Microservices
Out of scope for MVP — pipeline assumes one app, one base URL, one UI. Extension point: `project_type == "microservices"` in Step 0 output. Steps 5, 9, 11 need a microservices path when built. Do not clone the repo — extend in place to keep output schemas stable.
