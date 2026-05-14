# Step 0 Classifier — Edge Case Audit

Results of the comprehensive 20-case audit of `backend/pipeline/step0_classifier.py`.
All items were evaluated against the actual rule decision tree.

---

## Audit Table

| # | Case | Status | Notes |
|---|---|---|---|
| 1 | Nested `frontend/package.json` + `backend/pom.xml` | ✅ Works | `service_layout = "separate_frontend_backend"` detected via top-dir names |
| 2 | Vite not treated as frontend framework | ✅ Works | `frontend_tooling = "Vite"` added as separate field |
| 3a | Spring Boot detected from `build.gradle` | ✅ Works | |
| 3b | Spring Boot detected from `build.gradle.kts` | ✅ Fixed | Added `build.gradle.kts` to CONFIG_FILES |
| 4 | Plain Java not mistaken for Spring Boot | ✅ Works | `"spring-boot"` substring check is specific |
| 5 | React dep-only with no `.jsx`/`.tsx` files | ✅ Fixed | Now returns `confidence = "medium"` → LLM review |
| 6 | Express/NestJS in `devDependencies` only | ✅ Fixed | `backend_fw_js` now uses production deps only |
| 7 | SSR apps (Flask/Express/PHP + templates) | ✅ Fixed (prev session) | `_has_html_views()` helper |
| 8 | Spring Boot + Thymeleaf SSR | ✅ Fixed | `java_ssr` guard bypasses LLM; deterministic at high confidence |
| 9 | Next.js/Nuxt/SvelteKit with server API routes | ✅ Fixed | `server_routes_detected = true` flag added |
| 10 | Static HTML/CSS/JS site | ✅ Fixed | Rule-based `static_site` detection (no LLM needed) |
| 11 | Electron `backend_framework = "Electron"` | ✅ Improved | `runtime = "Electron"` field added; `backend_framework` kept for compat |
| 12 | React Native / Expo classified as `frontend_only` | ✅ Fixed | `mobile_app` type assigned for Expo/React Native |
| 13 | Generated/build dirs causing false positives | ✅ Improved | `.gradle/` already filtered; `examples`, `demo`, `sample` added to IGNORE_DIRS |
| 14 | Multiple `package.json` files (workspace root) | ✅ Works | All merged; `js_deps_prod` now tracked separately |
| 15 | Mixed frontend frameworks | ✅ Acceptable | First-match in ordered dict; acceptable for MVP |
| 16 | Full-stack SSR frameworks (Laravel/Rails/Django) | ✅ Fixed (prev session) | `_has_html_views()` helper |
| 17 | Spring Boot serving built static assets | ⚠️ LLM fallback | `src/main/resources/static/` not treated as SSR; LLM handles |
| 18 | `examples/`/`docs/` causing false positives | ✅ Fixed | Added to IGNORE_DIRS |
| 19 | Missing config files (source-file detection) | ✅ Works | LLM fallback reads file tree and ext counts |
| 20 | README-only claims | ✅ Works | README content not used in rule logic |

---

## New Output Fields

All new fields are populated by deterministic helpers regardless of whether the
rule-based or LLM path produced the result.

| Field | Type | Description |
|---|---|---|
| `frontend_tooling` | `str \| null` | Build tool: `"Vite"`, `"Create React App"`, `"Webpack"`, `"Parcel"`, etc. |
| `template_engine` | `str \| null` | SSR engine: `"Thymeleaf"`, `"Jinja2"`, `"Blade"`, `"EJS"`, `"Handlebars"`, etc. |
| `service_layout` | `str` | `"single_project"`, `"separate_frontend_backend"`, `"monorepo"`, `"single_project_ssr"`, `"unknown"` |
| `server_routes_detected` | `bool` | True when Next.js/Nuxt/SvelteKit/Remix API route dirs are found |
| `runtime` | `str?` | Only set for Electron apps: `"Electron"` |

---

## Known Limitations

### Spring Boot serving compiled SPA (`src/main/resources/static/index.html`)
If a Spring Boot project compiles a React app into `src/main/resources/static/`, the
classifier cannot tell whether `index.html` was React-compiled or a plain HTML file.
Only LLM classification is attempted here. The LLM may or may not detect React.

**Why not fixed:** `public/` and `static/` are also used for favicons, robots.txt, and
marketing pages. Treating any `static/*.html` as a compiled SPA would cause false positives
in pure Spring Boot REST APIs that serve a landing page. The risk/reward ratio is too high
for a rule-based fix.

### Next.js / Nuxt / SvelteKit classified as `frontend_only`
These meta-frameworks are technically full-stack (they include server-side rendering and
API routes). However, the test strategy for `frontend_only` is Playwright E2E — identical
to what would be assigned for `full_stack_web_app`. The `server_routes_detected` flag now
surfaces when API routes are present, giving Step 2 and downstream steps context without
changing the classification type.

### Monorepo: Express serving pre-compiled SPA via `public/`
Express + `public/index.html` (React compiled separately) stays as `backend_api_only`.
The `public/` directory is intentionally excluded from the SSR view check — it also holds
favicons, robots.txt, and static assets in pure REST API projects.

### Mixed frontend frameworks
If `package.json` contains both React and Vue (unusual but possible in widget repos),
the first match in `FRONTEND_FRAMEWORKS` (ordered dict) wins. The classifier does not
inspect source files to arbitrate. This is an acceptable approximation for MVP.

---

## Verified Test Coverage

`backend/tests/test_step0_classifier.py` — 12 fixtures, all passing:

1. `test_springboot_react_vite_split` — separate frontend/backend dirs
2. `test_springboot_react_vite_root` — single root project
3. `test_springboot_gradle_kts_react` — Gradle Kotlin DSL
4. `test_springboot_thymeleaf_ssr` — SSR, deterministic, no LLM
5. `test_react_vite_only` — frontend-only with Vite tooling
6. `test_react_dep_only_no_source` — React dep without .jsx/.tsx → medium confidence
7. `test_static_html_site` — plain HTML/CSS/JS
8. `test_electron_react` — Electron + React + Vite
9. `test_expo_mobile_app` — React Native / Expo → mobile_app
10. `test_express_devdep_only` — Express in devDependencies → not misclassified
11. `test_nextjs_with_api_routes` — Next.js + server_routes_detected
12. `test_flask_jinja2_ssr` — Flask SSR with Jinja2 template inference
