# Plan: Functional Correctness (FCor) — Behavioral schema fix + Steps 8–13 (white-box test execution)

> **This file is the sole source of truth for the correctness-phase implementation.**
> It is self-contained: read it top to bottom before implementing. It covers the behavioral
> schema fix (prerequisite), Step 8 (AC generation), and the white-box test-generation /
> execution / scoring design (Steps 9–13) agreed in design discussion.

---

## Context

The pipeline is complete through **Step 7.5** (FCom + FA, the *presence* phase). It auto-chains
Steps 0→7.5 in [confirm.py](backend/api/routes/confirm.py); terminal status is `step_7_5_complete`.
The existing **Step 11 Docker sandbox** ([step11_sandbox.py](backend/pipeline/step11_sandbox.py)) can
boot a full app + real DB but has **no tests to run** — `test_results: []` always.

This plan builds the **correctness (FCor) phase**: does each implemented requirement actually *behave*
correctly when executed? FCor is orthogonal to FCom — it requires running the app and executing tests.

**Core architectural decision (white-box, agreed in discussion):** tests are generated against the
**actual codebase + the running sandbox**, not guessed from requirement labels. This is far more
reliable than blind locator generation. Reliability is preserved for a *scoring* system by four
disciplines below.

**Behavioral requirements are FCor-only.** Autonomous system behaviors (auto-reset, scheduled
notifications, session/cache expiry — no UI, no user trigger) are **excluded from FCom presence
scoring** (static presence-detection of a scheduled job is unreliable and would inject false zeros)
and **hidden from the 0–7.5 UI panels**. They live in a **separate `behavioral_requirements` list
from extraction onward — a distinct channel, not an in-band flag** — so no FCom step has to remember
to filter them and none can accidentally leak in. They are *not assumed present* — `stated ≠ implemented ≠
working` (L1≠L3≠L4). Instead they are verified **solely by execution** in the correctness phase:
Step 8 emits time/state ACs, Step 11 runs them, and un-simulatable cases resolve to `blocked`
(confidence penalty) — never a faked pass. See Part A.

---

## Design principles (apply throughout Steps 9–13)

1. **White-box plumbing, black-box assertions.** Locators, navigation, and test setup (auth, seed
   data) are derived from reading the real source + live DOM — so selectors are real, not guessed.
   The **assertion** ("Then") is derived from the AC's *intent*, never from the implementation —
   otherwise the test just mirrors the code and cannot catch bugs.
2. **Deterministic via frozen artifact.** Generation is an LLM pass (stochastic), but the **stored
   generated script is the artifact**, and the score is tied to re-running *that script* + its trace.
   Never regenerate to re-score.
3. **Failure triage — a red line ≠ a broken feature.** Every failure is classified:
   `pass` / `fail` (feature genuinely broken) / `blocked` (setup or prerequisite failed — not the
   app's fault, lowers confidence not score) / `flaky` (inconsistent → run 3×, score = fraction).
   A bounded 1–2× locator-repair retry runs *before* marking `fail`, to absorb "the test was wrong".
4. **AC-block granularity.** Each AC becomes its own tagged test block (`test('AC-003-1', …)` /
   `def test_ac_003_1():`). The runner's JSON reporter then yields per-AC pass/fail directly — maps
   1:1 onto FCor's AC sub-weights. No stack-trace/line parsing. Respect dependencies: a failed
   prerequisite AC marks its dependents `blocked` (cascade), not independently failed.

---

## Pipeline reordering (important)

Today: `…7.5 (terminal)` → **[manual]** Step 11 boots Docker → tears down.

New correctness flow:
- **Auto-chain:** `…7.5 → Step 8 (AC gen)` → new terminal `step_8_complete`. Step 8 is pure intent —
  no sandbox needed.
- **[Manual] "Run Correctness Tests" button** launches one sandbox-scoped orchestration unit that boots
  the sandbox **once** and keeps it up across generation + execution:
  `boot sandbox → Step 9 (generate) → Step 10 (validate) → Step 11 (execute) → Step 13 (score) → tear down`.

The boot logic already exists in [step11_sandbox.py](backend/pipeline/step11_sandbox.py); it must be
refactored so boot and teardown bracket Steps 9–11 (boot → … → finally teardown) instead of boot→teardown
with nothing between.

---

## Part A — Behavioral requirements schema fix (PREREQUISITE — do first)

**Problem:** Autonomous behaviors (auto-reset, scheduled notifications, cache/session expiry) fail
Step 1's extraction gate and vanish. They have no navigable UI home, so they can't be presence-scored
reliably. The fix routes them into a **separate `behavioral_requirements` list at extraction** — a
distinct channel, not an in-band flag — so they never flow through the FCom pipeline at all, and
re-enter only at Step 8 (time/state ACs + execution) as their only verification path.

**Boundary (design decision):** a behavioral reaction that is a *property of an existing capability*
("session cleared on logout" — logout is already a requirement) stays an **AC** of that requirement.
Only *orphan autonomous behaviors* with no parent capability and no UI trigger become
`type: "behavioral"` **requirements**. Matches PLAN.md validity gate (lines 204–221).

**Schema change — Step 1 emits a separate `behavioral_requirements` list** alongside `requirements`,
carried as its own field through Step 3.5 (`step_3_5.behavioral_requirements`) into Step 8. No in-band
`type` flag is threaded through the FCom steps — the separate list *is* the channel.

1. **Step 1** — [step1_req_extractor.py](backend/pipeline/step1_req_extractor.py): extend
   `LLM_SYSTEM_PROMPT` extraction gate with a clause capturing orphan autonomous behaviors (LLM tags
   the item `behavioral`, minimal path = affected data edge / entity node, `vague: false`). In
   `_validate_and_normalise`, **partition** the validated items into two **mutually exclusive** lists —
   every item goes to **exactly one**:
   - functional → `requirements` (sequenced `REQ-001…`)
   - behavioral → a new **`behavioral_requirements`** list (sequenced `BEH-001…` — distinct prefix
     makes accidental inclusion visually obvious)

   A behavioral item is **removed from / never placed in `requirements`** — it is **not** duplicated
   across both lists, and `requirements` ends up containing **zero** behavioral items. Sequencing
   happens *after* the split, so `REQ-` numbering stays contiguous (no gaps). The Step 1 output
   envelope gains the `behavioral_requirements` field alongside `requirements`.
2. **Steps 2 & 3** — unchanged. They read `step_1.requirements` (functional only) and never see the
   behavioral list. No edit.
3. **Step 3.5** — [confirm.py](backend/api/routes/confirm.py): carry `step_1.behavioral_requirements`
   straight through into **`step_3_5.behavioral_requirements`** (a separate field — **never merged into
   `confirmed_requirements`**). No `type` field on `ConfirmedRequirement` is needed. Passed through
   read-only for now (user review/deletion can be added to the confirm body later).
4. **Steps 4, 5, 6 & 7 — no change (none touched).**
   - **Steps 4 & 5** never read the requirements list at all — they consume `project_context` + the
     codebase — so behavioral reqs are simply irrelevant to them.
   - **Steps 6 & 7** read `confirmed_requirements`/`advisory_requirements`, which now contain **zero**
     behavioral items, so behavioral never reaches FCom — nothing to filter.
   Nothing to change anywhere across 4–7; this is the robustness payoff of the separate channel.
5. **UI (Steps 0–7.5)** — behavioral reqs are hidden from the FCom/FA result panels and the L1a/L1b
   confirmation flow. They stay reviewable in the Step 3.5 confirmation table under a separate
   **"Behavioral — correctness-only"** group (rendered from `behavioral_requirements`), and surface in
   the Step 8 + correctness panels.

---

## Part B — Step 8: Acceptance Criteria Generator

**New file:** `backend/pipeline/step8_ac_generator.py` (LLM step; template =
[step7_5_fa_advisor.py](backend/pipeline/step7_5_fa_advisor.py)). Pure intent — runs without the sandbox.

- **Inputs:** `step_3_5.confirmed_requirements` (functional L1a — path, `weight` = L1Cx) **and**
  `step_3_5.behavioral_requirements` (behavioral); `step_6.mapped` (read `e_score` per `req_id` for
  *functional* eligibility); `step_3_5.project_summary`.
- **Eligibility (S):**
  - *Functional* reqs — generate ACs only for `e_score >= 0.5` (from `step_6.mapped`; matches Step 7's
    missing<0.5 boundary and PLAN.md "x ∈ L3"). E()=0.4/0.0 → `skipped_requirements` (gap already in FCom).
  - *Behavioral* reqs — **always eligible** (no E() gate; they bypass FCom). Read from the separate
    `step_3_5.behavioral_requirements` list.
- **Generation:** one Haiku call per eligible requirement, concurrent via `asyncio.gather` + per-call
  `try/except` safe default (mirror Step 6 `run()`). Per requirement, Given/When/Then ACs with per-AC `acw`:
  - `type == "functional"` → `happy_path` + `persistence` + `edge_case`
  - `type == "behavioral"` → **time/state ACs** (Given precondition, When [time elapses / condition met],
    Then [system state changes]) — no UI interaction assumed
- **Deterministic weight normalization:** rescale `acw` in Python so they sum **exactly** to the
  requirement's `weight` (same philosophy as Step 1 recomputing weight from priority). Sequential `ac_id`s
  (`AC-003-1…` for functional, `AC-BEH-001-1…` for behavioral).
- **Weighting (`l1cx`):** a requirement's `l1cx` is its locked `weight` — for functional reqs the
  Step 3.5 priority weight (critical 4 / high 3 / medium 2 / low 1); for behavioral reqs the **same
  priority→weight from Step 1**, fixed (read-only — not user-adjustable at 3.5 in this build). Because
  behavioral reqs are out of FCom, their weight matters **only** for FCor and the CP penalty, never FCom.
- **`test_type` per requirement** (for Step 9):
  - *Functional* — `e_score == 1.0 → "e2e"`; `0.75 / 0.5 → "api"`.
  - *Behavioral* — `test_type: "behavioral"`, `e_score: null` (no FCom E(); Step 9/11 use the
    time/state harness — clock/job-trigger hooks).
- **Output** (`step_results.step_8`):
  ```
  acceptance_criteria: [ { req_id, description, type, l1cx, test_type, e_score,
                           acceptance_criteria: [ {ac_id, given, when, then, acw, type} ] } ],
  skipped_requirements: [ {req_id, e_score, reason} ],
  total_acs, llm_model, error
  ```

---

## Part C — Step 9: White-box Test Generator (against codebase + running sandbox)

**New file:** `backend/pipeline/step9_test_generator.py`. Runs **after the sandbox is booted**.

- **Inputs:** `step_8.acceptance_criteria`; the **codebase** (extracted source — real component text,
  input `name`/`placeholder`/`data-testid`, routes, endpoints, auth flow, fixtures/seed scripts);
  per-route **live DOM snapshots** from the just-booted sandbox (Playwright snapshot — cheap, deterministic,
  not an open agent loop); `step_3_5.project_context` (`test_strategy`, frameworks);
  `step_4.implementation_units` (endpoint verbs/paths for API tests).
- **Grounding priority:** (1) codebase source → locators, navigation, **setup** (auth/seed);
  (2) live DOM snapshot → confirm the "When" trigger elements as actually rendered;
  (3) AC intent → the "Then" assertion (**never** from code — discipline #1).
- **Output:** one tagged test block per AC; assertions prefer **data the test itself introduces**
  (`getByText(uniqueValue)`) so post-operation results need no pre-known selector. Test type:
  `e2e` → Playwright E2E (+ API); `api` → API only. Framework by `project_context.test_strategy`
  (React/Vue/Angular → Playwright TS; Python → Pytest; Node/Express → Jest/Supertest).
- **Frozen artifact** (`step_results.step_9`):
  ```
  test_files: [ { req_id, ac_id, test_type, framework, filename, code, setup_notes? } ],
  total_tests, llm_model, error
  ```
  Files are also written into the sandbox test dir for execution; the stored `code` is the
  reproducible artifact.

---

## Step 10 — Oracle Validator (design; build in the execution pass)

**New file:** `backend/pipeline/step10_oracle.py` (rule-based + LLM). Guards discipline #1 before
execution. **Rejects** tests that: assert nothing (existence-only), echo the implementation instead of
the AC intent, don't actually exercise their AC, or skip required persistence/edge-case checks.
Output: validated subset + rejection log `{ac_id, reason}`. Rejected ACs → `blocked` (untestable),
their weight rolls into CP at Step 13.

---

## Step 11 — Execution + Triage (extends existing sandbox)

Refactor [step11_sandbox.py](backend/pipeline/step11_sandbox.py): boot once → hold up across Steps 9–10
→ **execute** the validated scripts → tear down in `finally`.

- Run via the framework's headless runner with **JSON reporter**; parse per-AC results (discipline #4).
- **Triage** each result: `pass` / `fail` / `blocked` / `flaky` (run 3×, `pass_i = passes/3`).
  Setup/dependency failure → `blocked`; failed prerequisite AC → dependents `blocked` (cascade).
- **Bounded repair loop:** on a locator-class failure, give the LLM the error + a fresh DOM snapshot,
  regenerate *only that block's locators* (max 1–2×), re-run. Absorbs "test was wrong" before `fail`.
- **Behavioral (time/state) ACs:** attempt automation via clock/job-trigger hooks where the app exposes
  them; otherwise mark `blocked` (→ CP) rather than faking a pass — the honest outcome for behaviors
  that can't be simulated in-test (e.g. "auto-reset at midnight").
- Save traces/screenshots/logs as evidence (feeds Step 12 / Step 15).
- **Output** keeps the existing schema plus populated `test_results`:
  `{ req_id, ac_id, result, reason, duration_ms }`.

---

## Step 13 — FCor Scorer (design)

**New file:** `backend/pipeline/step13_fcor_scorer.py` (formula only, no LLM):
```
S   = { x ∈ L1a | E(x) ≥ 0.5 }            (eligible, backend-implemented)
S*  = S \ { x | all ACs blocked }          (testable subset)
FCor = Σ(pass_i × acw_i) / Σ(acw_i)        [i ∈ ACs of S*]
CP   = Σ_blocked_L1Cx / Σ_all_L1Cx          (confidence penalty, reported separately)
```
Behavioral reqs are excluded from FCom but **enter FCor's eligible set directly** (they have ACs by
construction, not via an E() gate); their `blocked` time/state ACs roll into CP.
Output: FCor ratio + per-requirement AC breakdown + CP.

---

## Pipeline chaining + frontend wiring

**Backend** — [confirm.py](backend/api/routes/confirm.py):
- `_run_step7_5` chains into a new `_run_step8` (auto). New statuses
  `step_8_running` → `step_8_complete` (new auto-terminal). Step 8 instantiates `AsyncAnthropic()`
  like `_run_step6`.
- New **manual** endpoint `POST /api/jobs/{job_id}/correctness` (sibling to the sandbox route in
  [sandbox.py](backend/api/routes/sandbox.py)) → orchestrates boot → Step 9 → 10 → 11 → 13 → teardown.
  Statuses: `step_9_running` → `step_10_running` → `step_11_running` → `step_13_running` →
  `step_13_complete` (+ `*_error`). Sandbox boot reuses existing step11 boot logic.

**Frontend types** — [types/index.ts](frontend/src/types/index.ts): add a `behavioral_requirements`
array to `Step1Result` and `Step35Result` (separate from `requirements`/`confirmed_requirements`);
add `Step8Result`, `Step9Result`, `Step10Result`, `Step13Result`; add `step_8?…step_13?` to
`StepResults`; add the new statuses to `JobStatus`.

**Frontend app** — [App.tsx](frontend/src/App.tsx): add loading flags; update `terminalStatuses`
(line 264) to `step_8_complete` (auto-terminal) and `step_13_complete`/`step_13_error` (correctness
terminal); add a **"Run Correctness Tests"** button gated on `step_8_complete` (parallel to the existing
sandbox button, lines 121/214–223); render new result components; update the status caption (lines 133–139).

**Frontend components (new):** `ACResult.tsx` (Step 8 — per-req AC tables with `acw` and a "Σ acw = L1Cx"
check, behavioral badge), `TestGenResult.tsx` (Step 9 — collapsible per-AC code), `FCorResult.tsx`
(Steps 11/13 — per-AC pass/fail/blocked/flaky matrix, FCor %, CP). Follow the
[FA75AdvisorResult.tsx](frontend/src/components/FA75AdvisorResult.tsx) card + skeleton pattern. Check
[Sidebar.tsx](frontend/src/components/Sidebar.tsx) for a step-label list to extend.

**Tests** (`backend/tests/test_stepN_*.py`, mock the Anthropic client like the Step 7.5 tests):
- `test_step8_ac_generator.py` — acw rescales to exactly `weight`; E<0.5 skipped; behavioral → time/state ACs
- `test_step9_test_generator.py` — one block per AC; assertions from AC not code; framework by project_context
- `test_step10_oracle.py` — rejects assert-nothing / code-echo tests
- `test_step13_fcor_scorer.py` — FCor formula; blocked → CP, excluded from S*; cascade blocking
- Step 1 / Step 3.5 behavioral split — behavioral items land in `behavioral_requirements` (`BEH-…`),
  never in `requirements`/`confirmed_requirements`; confirm.py carries the list into `step_3_5`
  (assert Steps 6/7 inputs are unaffected — no behavioral leak)

---

## Build phases / scope

**Phase 1 — presence-side (no Docker):** Part A (behavioral fix: Step 1 splits out a
`behavioral_requirements` list; confirm.py carries it into `step_3_5`; ConfirmationTable shows a
read-only behavioral group; **Steps 6/7 untouched**), Part B (Step 8 AC generator — functional +
behavioral ACs, auto-chained), `ACResult.tsx`. New auto-terminal `step_8_complete`.

**Phase 2 — correctness execution unit (Docker, manual trigger):** sandbox boot refactor, Step 9
white-box generator, Step 10 oracle, Step 11 execution+triage+repair, Step 13 FCor scorer, the
`/correctness` endpoint + chaining, `TestGenResult.tsx` + `FCorResult.tsx`.

Build and verify Phase 1 first; it is independently shippable.

---

## Critical files

Rows tagged **new** are net-new files. **All other rows already exist in code and are modified in
place** — i.e. the already-implemented files this plan touches are: Step 1, confirm.py,
ConfirmationTable.tsx, sandbox.py, step11_sandbox.py, types/index.ts, App.tsx, Sidebar.tsx. (Steps 6
and 7 are **not** touched.)

| File | Change |
|---|---|
| [step1_req_extractor.py](backend/pipeline/step1_req_extractor.py) | behavioral extraction clause; split output into `requirements` + `behavioral_requirements` (`BEH-…`) |
| [confirm.py](backend/api/routes/confirm.py) | carry `behavioral_requirements` step_1→step_3_5; `_run_step8` auto-chain |
| [ConfirmationTable.tsx](frontend/src/components/ConfirmationTable.tsx) | read-only "Behavioral — correctness-only" group |
| [sandbox.py](backend/api/routes/sandbox.py) | new `/correctness` orchestration endpoint |
| [step11_sandbox.py](backend/pipeline/step11_sandbox.py) | boot-hold-execute-teardown refactor + triage + repair |
| `backend/pipeline/step8_ac_generator.py` | **new** |
| `backend/pipeline/step9_test_generator.py` | **new** (white-box) |
| `backend/pipeline/step10_oracle.py` | **new** |
| `backend/pipeline/step13_fcor_scorer.py` | **new** |
| [types/index.ts](frontend/src/types/index.ts), [App.tsx](frontend/src/App.tsx) | types, statuses, wiring |
| `frontend/src/components/{ACResult,TestGenResult,FCorResult}.tsx` | **new** |

---

## Verification

1. **Unit tests:** `cd backend && venv\Scripts\activate && pytest tests/ -q` — all green.
2. **Phase 1 E2E:** run backend + frontend; upload a project whose requirements include a behavioral
   line (e.g. *"Tasks auto-reset to 'todo' every midnight"*). Confirm requirements; watch the job chain
   `…7.5 → step_8_complete`. Inspect job JSON (`GET /api/jobs/{job_id}`):
   - Step 1: behavioral line appears in `behavioral_requirements` as `BEH-001` (NOT in `requirements`)
   - Step 3.5: `step_3_5.behavioral_requirements` populated; `confirmed_requirements` contains no
     `BEH-` ids; Steps 6/7/FCom completely unaffected (no behavioral leak)
   - Step 8: each functional req's `acw` sums to its `weight` (E<0.5 skipped); the behavioral req has
     time/state ACs and is always eligible (no E() gate)
3. **Phase 2 E2E:** click **Run Correctness Tests** on a Spring Boot + React sample. Verify: sandbox
   boots once; Step 9 scripts have real locators (from source) + AC-intent assertions; one test block
   per AC; Step 11 produces per-AC `pass/fail/blocked/flaky`; a deliberately broken feature → `fail`,
   a missing-login flow → `blocked` (not fail); FCor % + CP render.
4. **Reproducibility:** re-run execution on the **stored** Step 9 script → identical FCor.

---

## Docs (confirm before committing)

CLAUDE.md's git workflow requires PLAN.md + CLAUDE.md updates in the same commit as schema/step changes.
**Do not edit the project's PLAN.md without explicit user go-ahead** (standing user feedback) — confirm
at commit time. Doc deltas: `type: "behavioral"` field; Step 8/9/10/13 schemas; the Step-9-after-boot
reorder; new statuses (`step_8_complete`, `step_13_complete`); the `/correctness` endpoint.
