# Steps 4–6 Design Problems & Proposed Solutions

This document captures the structural reliability problems identified for Steps 4–6 and the design decisions made in response. Written for handoff context — read PLAN.md alongside this.

---

## What Steps 4–6 are supposed to do

**Step 4 (Repo Parser — COMPLETE):** Static Tree-sitter AST analysis of the uploaded codebase. Produces L3 inventory: `languages`, `api_endpoints` (method/path/handler/file), `frontend_routes`, `database_models`, `existing_tests`, `important_files`. No LLM.

**Step 5 (App Crawler — NOT YET BUILT):** Playwright dynamic crawl of the running app. Produces per-page element inventory: for each route, what inputs/buttons/links are visible, with CSS selectors. Also Tree-sitter static fallback for auth-gated pages. No LLM.

**Step 6 (Requirement → L2/L3 Mapper — NOT YET BUILT):** For each L1a requirement (and L1b for FA), determine whether it exists in the positive inventory. Produces E() score per requirement, which feeds Step 7's FCom/FA formulas.

---

## The Core Tension

L1a requirements carry `path: PathEntity[]` — an ordered traversal of UI entities the LLM inferred in Steps 1–3. These entities were generated from requirement text and project metadata, **before the codebase was analysed**. They represent the LLM's hypothesis about what UI pattern implements the requirement, not ground truth.

Step 6 must compare these hypothesis-based path entities against Step 5's ground-truth Playwright inventory. Three distinct reliability problems arise.

---

## Problem 1 — Path Entity Structural Mismatch

**The issue:**
The Step 1/3 LLM generates path entities based on the most common UI pattern for a given requirement type. For "User can add task description," it might generate:

```
[Task List Page] → navigate to → [Task Detail Page] → [description input] → [save button] → navigate back
```

But the actual app might implement this as:
- An **inline edit** directly on the task list row (no page navigation)
- A **modal popup** triggered by clicking the task (no separate page)
- An **accordion** that expands in place
- A **sidebar panel** that slides in

All of these are valid implementations of "User can add task description" but none of them match the path topology the LLM generated. The entity "Task Detail Page" doesn't exist in Step 5 because there is no detail page.

**Consequence:**
Step 6 looks for "Task Detail Page" as a node entity → not found in Step 5 → L2 score drops. The requirement is fully implemented in the app, but the scoring produces a false negative. FCom penalises the app for a missing requirement that's actually there.

**Key characteristic:**
This is a **structural** mismatch, not a vocabulary mismatch. No amount of fuzzy label matching fixes it — the entire path topology is wrong. The LLM assumed page navigation; the app uses a different interaction pattern.

---

## Problem 2 — Entity-Level Matching Fails for Collections and Compound UI

**The issue:**
Even when path topology is correct, element-level matching has a systematic failure case: requirements involving lists, tables, or compound components.

"User can view task list" generates a path entity `{type: "node", label: "task list"}`. Playwright returns individual `<li>` elements inside a `<ul>` — not a single "task list" entity. There is no DOM element labelled "task list"; it's a collection of items.

Similarly, "User can view dashboard" might expect a "dashboard" node, but Playwright finds several independent panels/widgets with no single container labelled "dashboard."

**Consequence:**
Entity-level matching produces false negatives for any requirement whose natural language entity label maps to a compound DOM structure rather than a single element.

---

## Problem 3 — Passive Crawl Cannot Observe Form Submission API Calls

**The issue:**
Step 5's Playwright crawl is **passive** — it visits each page on load and extracts visible elements. It does NOT fill forms, click submit buttons, or trigger user interactions. Therefore:

- `api_calls_observed` in Step 5 only captures GET requests triggered on page load
- POST/PUT/DELETE endpoints (form submissions, create/update/delete actions) are **never observed** by Playwright
- Any attempt to use `api_calls_observed` as L2 evidence for action-type requirements would systematically give those requirements L2-absent scores

**Consequence:**
If Step 6 uses `api_calls_observed` as the L2 evidence for API-call edge entities, all form-submission requirements get E() ≤ 0.5 by default (L3-only), even when the full flow is correctly implemented. This is a systematic bias that makes FCom unreliable for all mutating operations.

**Resolution decided:**
Do NOT use `api_calls_observed` for E() scoring. The L2 evidence for a mutating action is **the presence of the triggering UI element** (submit button, form inputs) on the relevant page — not the observed network call. The L3 evidence is Step 4's static endpoint list. `api_calls_observed` is kept only as a supplementary cross-check against Step 4, not as a scoring input.

---

## Problem 4 — Capability-Level LLM Judgment Is Unreliable

**The proposed fix for Problem 1 was:**
Instead of entity-level matching, ask the LLM: "Given this requirement description and this Step 5 page inventory, does the app satisfy this requirement?" This avoids topology assumptions.

**Why this also fails:**
"Does this inventory satisfy this requirement?" is an open-ended judgment call with no ground truth anchor. The LLM will produce confident-sounding answers that vary across runs and have no verifiable basis. There is no concrete evidence to point to — it's just the LLM's opinion. This trades structural brittleness for hallucinated confidence scores.

---

## Proposed Solution — Structured Functional Decomposition

**Core idea:**
Every L1a requirement can be decomposed into two things that ARE reliably detectable in Step 4/5 structured inventories:

- **Action**: what operation is being performed — `create / read / update / delete / navigate / display`
- **Object**: what data entity is being acted on — `task / user / comment / task.description`

"User can add task description" → `{action: update, object: task, attribute: description}`
"User can view task list" → `{action: read, object: task}`
"User can delete a comment" → `{action: delete, object: comment}`

**The LLM's role changes from judgment to extraction:**
Extracting `(action, object)` from a structured requirement description with a fixed vocabulary is a narrow, well-defined task where LLMs are consistently reliable. This is fundamentally different from "does this inventory satisfy this requirement?" (open-ended judgment, unreliable).

**L3 matching becomes deterministic:**
HTTP method maps to action: `POST → create`, `GET → read`, `PATCH/PUT → update`, `DELETE → delete`. URL path segments map to object: `/api/tasks → task`, `/api/tasks/:id/comments → comment`. Match `(action, object)` against Step 4 `api_endpoints` structurally. No LLM judgment needed for the match itself.

**L2 matching becomes topology-agnostic:**
Does Step 5 have an element of the right type associated with the right object, on any page? A `<textarea>` or `<input>` associated with tasks satisfies `update task.description` — regardless of whether it's inline, in a modal, on a detail page, or in a sidebar. Step 5 element `type + subtype + label` gives enough structure for this without assuming path topology.

**Path entities become context hints, not matching targets:**
If the path entity mentions "Task Detail Page," check `/tasks/:id` first. If not found, broaden to any page with task-related elements. Path entities guide the search but don't constrain it.

**Why this resolves all four problems:**
1. **Structural mismatch (Problem 1):** `(action: update, object: task)` matches whether the app uses a detail page, modal, or inline edit. Topology-agnostic by design.
2. **Collection matching (Problem 2):** `{action: read, object: task}` matches a list of task `<li>` elements — no single "task list" entity required.
3. **Passive crawl bias (Problem 3):** L2 evidence is element presence (inputs/buttons for the object), not observed network calls. The textarea existing IS the L2 evidence; the POST call doesn't need to be observed.
4. **LLM reliability (Problem 4):** LLM does extraction (narrow, reliable), not judgment (open-ended, unreliable).

---

## Decisions Already Made in PLAN.md

1. **Step 5 has no LLM** — pure Playwright crawl + Tree-sitter static fallback. Output is per-page element inventory, not named functions. No LLM summarisation step.

2. **Step 6 scores E() at requirement level, not entity level** — path entities guide the search but are not the atomic scoring unit.

3. **`api_calls_observed` is not used for E() scoring** — only for supplementary cross-check against Step 4.

4. **L1a/L1b are a spectrum** — FCom uses confirmed normative (L1a, human-locked at Step 3.5). FA uses probabilistic normative (L1b, LLM confidence-weighted). Same E() mechanism, different epistemic authority. Not "contamination" — shared positive evidence base with appropriate weighting.

5. **Step 7.5 (Positive-Grounded FA Advisor)** — planned but not yet designed. Takes Step 4/5 positive inventory + L1a context → LLM generates improvement suggestions grounded in actual codebase structure. Distinct from Step 7's Type A advisory (L1b gap items) — this is Type B (codebase-grounded suggestions the Step 3 LLM couldn't make without seeing the code).

---

## Open Questions for Next Session

1. **Functional decomposition schema:** Should `(action, object, attribute)` be extracted in Step 6 at scoring time, or should it be added as a structured field to each requirement at Step 3.5 (making Step 6's extraction deterministic)? Adding it at Step 3.5 is cleaner but requires a schema change.

2. **L2 score computation with decomposition:** When Step 5 finds a text input associated with tasks on `/tasks`, how is the L2 confidence computed? Binary (found/not found) or fractional (how well does the element evidence support the action+object)? The fractional approach is more informative but harder to implement reliably.

3. **Multi-object requirements:** "User can assign a task to a team member" involves two objects (task, user) and a relationship. The `(action, object)` decomposition is `{action: update, object: task, attribute: assigned_to, related_object: user}`. How does Step 6 handle the related object lookup in Step 4/5?

4. **Step 5 auth handling:** Most real apps gate the majority of pages behind auth. The Tree-sitter static fallback for auth-gated pages produces element lists without runtime verification. How much to trust static fallback for L2 scoring — the current plan discounts it × 0.5, but is that the right factor?

5. **Step 6 LLM call structure:** One LLM call per requirement (extract action+object, then structured lookup), or batch all requirements in one call? Batching is cheaper but extraction errors compound. Per-requirement is more reliable but expensive for large L1a sets.
