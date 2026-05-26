# Steps 5–7 Architecture Decisions + Build Flow

## Context

Steps 0–4 and Step 3.5 are complete. The next phase is the FCom/FA scoring pipeline.

**The three sub-characteristics are orthogonal and scored independently:**
- **FCom/FA** — Steps 4–7 — *presence* — does the function exist at any layer? No app execution needed. Locked after Step 7. Never updated by Step 11.
- **FCor** — Steps 8–11 — *correctness* — does it behave correctly? Requires running the app and executing tests. Scored separately.

Step 11 test results feed FCor only. They do NOT update FCom E() scores.

**Design decisions settled:**
- **No action+object decomposition** — existing `path: PathEntity[]` is sufficient. `element` entities (primary) are the L2 matching target; `edge` entities (primary) drive L3 inference; `node` entities (secondary) are page anchors.
- **Step 5 uses Playwright from the start** — passive crawl visits each route and captures rendered elements. Static Tree-sitter fallback only for routes Playwright cannot access (auth-gated, redirect loops). Bootstrap is heuristic-based from Step 0 project type + framework.
- **Step 5 CSS selectors come from Playwright DOM, not source code** — source-extracted selectors (className, id) are unreliable (CSS-in-JS hash suffixes, component library abstraction). Step 9 generates Playwright locators (`getByRole`, `getByText`, `getByPlaceholder`) from path entity labels via LLM — does not read Step 5 selectors.
- **Step 6 computes final FCom E()** — per-entity piecewise functions using Step 5 L2 evidence + Step 4 L3 evidence. Not updated by Step 11.
- **Step 7 runs once** — after Step 6. FCom and FA scores are locked. FCor is scored by a separate mechanism after Step 11.

---

## Layer Mapping

| Step | Layer | Role | Evidence |
|---|---|---|---|
| Step 4 | L3 | Backend inventory (endpoints, routes, models) | Static code |
| Step 5 | L2 | UI element inventory per route | Playwright passive crawl; static Tree-sitter fallback for auth-gated routes |
| Step 6 | — | E() per requirement from L2 + L3 | Steps 4 + 5 |
| Step 7 | — | FCom + FA scores (locked) | Step 6 E() |
| Step 11 | L4 | Test execution → FCor score | Active Playwright E2E |

---

## E() Per Entity — Piecewise Functions (Step 6)

The Conceptual Model formula `E(L1x) = α × [∑ E(primary_i) / P] + (1−α) × [∑ E(secondary_j) / S]` uses per-entity E() values. Each entity type has a different evidence source and scoring function.

**`node` entity** (page/screen):

| Route in Step 4 | Step 5 page accessible (Playwright) | E(node) |
|---|---|---|
| ✓ | ✓ | 1.0 |
| ✓ | static fallback only | 0.5 |
| ✗ | — | 0.0 |

**`element` entity** (UI element — L2 signal only, no L3 equivalent):

| Found in Step 5 | E(element) |
|---|---|
| Playwright-confirmed (runtime rendered) | 1.0 |
| Static fallback only (source declared) | 0.5 |
| Not found | 0.0 |

**action `edge` entity** (edge label implies HTTP mutation — submit/create/delete/update/save):

| Endpoint in Step 4 | Triggering element in Step 5 | E(action_edge) |
|---|---|---|
| ✓ | ✓ | 1.0 |
| ✓ | not found | 0.5 |
| ✗ | ✓ | 0.4 |
| ✗ | ✗ | 0.0 |

**navigation `edge` entity** (navigate/go to/return — no HTTP mutation):
Not scored. Outbound link detection is unreliable for programmatic navigation (React Router `history.push()`). Navigation edges are excluded from P and S counts in the aggregation formula.

**Aggregation:**
```
E(req) = 0.7 × [∑ E(primary_i, excl nav edges) / P]
       + 0.3 × [∑ E(secondary_j, excl nav edges) / S]
```
If S = 0 (no secondary entities), α = 1.0 (100% primary weight).

---

## Build Order

### Phase 1 — Step 5: L2 UI Inventory (Playwright + static fallback)

**Purpose:** Per-route element inventory from the running app. Consumer: Step 6 (L2 presence signal for FCom). Step 9 is NOT a consumer — it generates locators from path entity labels via LLM, not from Step 5 selectors.

**App bootstrap** (heuristic from Step 0 `project_context`):
- `frontend_only` + Vite/CRA → `npm run dev` (or `npm start`)
- `backend_api_only` + FastAPI → `uvicorn main:app --port 8000`
- `backend_api_only` + Flask → `flask run`
- `backend_api_only` + Express → `npm start`
- `full_stack_web_app` → start backend first (per above), then frontend; wait for both ports
- Health check: poll until port responds (timeout 30s), then begin crawl

**Playwright passive crawl** (per route in Step 4 `frontend_routes`):
- Visit route, wait for network idle (`networkidle`)
- Extract all visible interactive elements: type, subtype, label (textContent / aria-label / placeholder / title / name — in priority order), CSS selector from Playwright's own locator
- Also capture page `document.title` and first `h1` text for page anchor matching in Step 6
- Record `accessible: true`, `discovered_by: "playwright"`
- Record `outbound_links` (href values of `<a>` tags visible on page)
- Record `api_calls_observed` (XHR/fetch GET requests on page load — supplementary only, not scored)
- If page redirects to login or returns 401/403: mark `accessible: false`, add to `unvisitable_routes`

**Static Tree-sitter fallback** (for routes in `unvisitable_routes` — auth-gated or unreachable):
- Walk source files from Step 4 `important_files` + route→file mapping
- Extract `<input>`, `<button>`, `<textarea>`, `<select>` with label attributes (placeholder, aria-label, name, textContent)
- Record `discovered_by: "static_fallback"`, `accessible: null`, `selector: null`

**Output schema** (`job["step_results"]["step_5"]`):
```json
{
  "pages": [
    {
      "route": "/tasks",
      "title": "Task List",
      "discovered_by": "playwright",
      "accessible": true,
      "elements": [
        { "type": "input",  "subtype": "text",   "label": "Add a task...", "selector": "input[placeholder='Add a task...']", "visible": true },
        { "type": "button", "subtype": "submit", "label": "Add",           "selector": "button.add-btn",                    "visible": true }
      ],
      "outbound_links": ["/settings"],
      "api_calls_observed": ["GET /api/tasks"]
    },
    {
      "route": "/admin",
      "title": null,
      "discovered_by": "static_fallback",
      "accessible": null,
      "elements": [
        { "type": "input", "subtype": "text", "label": "Search users", "selector": null, "visible": null }
      ],
      "outbound_links": [],
      "api_calls_observed": []
    }
  ],
  "unvisitable_routes": [
    { "route": "/admin", "reason": "auth_required" }
  ]
}
```

**Job status:** `step_4_complete` → `step_5_running` → `step_5_complete`

**Files to create:** `backend/pipeline/step5_crawler.py`

---

### Phase 2 — Step 6: E() Scorer

**Inputs:** `step_3_5.confirmed_requirements`, `step_3_5.advisory_requirements`, Step 5 `pages[]`, Step 4 `api_endpoints`.

**Step 6 process per requirement:**

1. **For each `node` entity** in `path[]`:
   - Look up entity label against Step 4 `frontend_routes` (fuzzy string match; LLM batch fallback for ambiguous cases)
   - Look up entity label against Step 5 `pages[]` (match on route + title + h1)
   - Assign E(node) per piecewise function above

2. **For each `element` entity** in `path[]`:
   - Identify the nearest node entity (page anchor) — the most recent `node` entity before this element in the path array
   - LLM batch call per page: given element entity labels for this page + Step 5 `elements[]` on matched page → `matched: true | false` per entity (no selector needed)
   - Assign E(element) per piecewise function above

3. **For each `edge` entity** in `path[]`:
   - Classify as action edge or navigation edge via HTTP verb heuristic: submit/add/create/delete/update/save/mark → action; navigate/go to/return/open → navigation
   - Navigation edges: skip (excluded from scoring)
   - Action edges: LLM batch call: edge label + requirement description + Step 4 `api_endpoints` → matched endpoint or null; also check if triggering element exists on the matched page (from Step 5)
   - Assign E(action_edge) per piecewise function above

4. **Aggregate** per formula: `E(req) = 0.7 × [primary avg] + 0.3 × [secondary avg]`, excluding navigation edges from counts.

**Unlinked detection:**
- `unlinked_l2`: Step 5 routes not matched by any L1a `node` entity
- `unlinked_l3`: Step 4 endpoints not matched as L3 signal for any L1a requirement

**Output schema** (`job["step_results"]["step_6"]`):
```json
{
  "mapped": [
    {
      "req_id": "REQ-001",
      "description": "User can add a to-do item",
      "e_score": 0.85,
      "entity_scores": [
        { "label": "Task List Page", "type": "node", "primary": false, "e": 1.0, "matched_route": "/tasks", "playwright_accessible": true },
        { "label": "add task input", "type": "element", "primary": true, "e": 1.0, "matched_page": "/tasks", "discovered_by": "playwright" },
        { "label": "Add button", "type": "element", "primary": true, "e": 1.0, "matched_page": "/tasks", "discovered_by": "playwright" },
        { "label": "submits task", "type": "edge", "primary": true, "e": 1.0, "matched_endpoint": "POST /api/todos", "triggering_element_found": true },
        { "label": "navigate to list", "type": "edge", "primary": true, "e": null, "skipped": "navigation_edge" }
      ]
    }
  ],
  "unlinked_l2": [],
  "unlinked_l3": []
}
```

**Job status:** `step_5_complete` → `step_6_running` → `step_6_complete`

**Files to create:** `backend/pipeline/step6_mapper.py`

---

### Phase 3 — Step 7: FCom/FA Scorer

Pure Python formula, no LLM. Runs once after Step 6. Scores are locked — not updated by Step 11.

**FCom:** `∑(E(req) × weight) / ∑(weight)` for all `confirmed_requirements`.
**FA:** Same formula over `advisory_requirements`.
**Unlinked advisory:** Pass through `unlinked_l2` and `unlinked_l3` from Step 6 for advisory output.

**Output schema** (`job["step_results"]["step_7"]`):
```json
{
  "fcom": 0.73,
  "fa": 0.41,
  "fcom_detail": {
    "numerator": 14.6,
    "denominator": 20.0,
    "requirement_count": 8
  },
  "fa_detail": {
    "numerator": 8.2,
    "denominator": 20.0,
    "requirement_count": 10
  },
  "unlinked_l2": [],
  "unlinked_l3": []
}
```

**Job status:** `step_6_complete` → `step_7_running` → `step_7_complete`

**Files to create:** `backend/pipeline/step7_scorer.py`

---

## Job Status Chain (full sequence)

```
confirmed
  → step_4_running → step_4_complete
  → step_5_running → step_5_complete
  → step_6_running → step_6_complete
  → step_7_running → step_7_complete
```

Each step triggers the next automatically via `BackgroundTasks` in FastAPI (same pattern as Step 4 trigger after Step 3.5 confirmation).

---

## Verification

After Phases 1–3:
- Upload a test zip through Step 3.5, confirm requirements, trigger Step 4
- Step 5 → Step 6 → Step 7 trigger automatically in sequence
- Inspect `step_5` job JSON: elements extracted per route, Playwright-confirmed for accessible routes
- Inspect `step_6` job JSON: `entity_scores[]` per requirement, E() values, unlinked lists populated
- Inspect `step_7` job JSON: FCom and FA scores in 0–1 range
- Verify E()=1.0 for a requirement where element + endpoint both found via Playwright
- Verify E()=0.5 for a requirement where element + endpoint found via static fallback only
- Verify E()=0.0 for a fabricated requirement with no matching element or endpoint
- Verify navigation-only OBV requirements: E(node)=1.0 if route found + Playwright accessible, 0.0 if route not found
- Verify navigation edges are excluded from P/S counts (do not lower the aggregate score)
