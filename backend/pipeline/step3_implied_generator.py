import asyncio
import json

import anthropic

from pipeline.utils import _identify_root_node, _is_state_variant, _validate_path

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
VALID_CATEGORIES = {"sop", "inf"}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Generate implied user-facing functions in two structured passes.

Each output is a complete function with a traversal path (entry + body + exit baked in). The path is the Playwright test sequence for this function.

---

CONFIDENCE — calibrate confidence_score (0–1) carefully; it alone determines placement downstream:
≥ 0.80 → enters completeness scoring (Section 1 of confirmation)
< 0.80 → advisory only (Section 2); the lower the score, the weaker the implication

---

PASS 1 — SOP-TRIGGERED FUNCTIONS

For each Step 1 stated requirement, check whether any pattern in the table below applies, and generate it. Generate only patterns explicitly in the table — fire them on stated requirements only, never on functions you generate in this pass. Do not self-censor for overlap; a later pass removes duplicates.

A function is one complete user goal, not a step within it — navigate / fill / submit / confirm steps belong in its path[], never as separate functions.

MULTI-OBJECT TYPES: When the app manages multiple distinct named object types (e.g., "categories" AND "tasks"), fire all applicable patterns independently for EACH object type. "User can edit a task" and "User can edit a category name" are distinct — generate both. Never conflate two object types into one function.

PATTERN TABLE:

Stated node type → Generate these functions (confidence):
- List node (shows multiple items of same type):
    filter by attribute (~0.82), search (~0.80), sort (~0.68), edit item (~0.85), delete item (~0.82)
- Detail node (shows single item):
    edit (~0.85), delete (~0.82)
- Auth present (login or register stated):
    account management / profile page (~0.87)
- Named changeable status field:
    cross-status overview page (~0.75), filter-by-status element (~0.82)
- Temporal field (dates, deadlines on listed items):
    time-scoped view / calendar view (~0.75), overdue / due-soon alert surface (~0.72)
- Mutable records (add + delete both stated on same list node, OR edit/update stated):
    audit / history page (~0.60)
- User-configurable preferences stated:
    settings page (~0.82)
- Time-sensitive deadlines or thresholds (items with due dates on a list):
    notification surface (~0.65)
- Multi-user / per-user data stated:
    user profile / identity page (~0.82)
- Create / add stated for an entity type:
    edit item (~0.85), delete item (~0.82)

category: "sop"

---

PASS 2 — DOMAIN INFERENCE

Read the project_summary and all stated functions. Before generating any function, understand the purpose of this specific app, what it manages, and how it works — only generate functions consistent with its actual structure and intent. Then think about what a well-rounded, production-quality app in this domain would offer. Generate functions across ALL of these angles that Pass 1 did not cover:

1. RECURRING USE — What functions would a regular user return to repeatedly in normal workflow? (daily tasks, status checks, monitoring)
2. WORKFLOW COMPLETENESS — What functions complete the primary user workflow end-to-end? (onboarding, confirmation flows, completion states, getting-started guidance)
3. DATA MANAGEMENT — What functions help users manage, organise, or recover their data? (bulk operations, export, import, archive, restore, history)
4. DOMAIN STANDARDS — Name the app's domain from project_summary. Exhaustively list ALL standard features a top-tier competitor app in that domain offers that are NOT yet covered, and generate a function for each. Do not cap the count — comprehensive L1b coverage is what makes FA scoring meaningful. The point is to surface every gap, even if you're unsure the codebase implements them.
5. DISCOVERABILITY + HELP — What functions help users get oriented or get help? (help page, onboarding tour, empty-state guidance, keyboard shortcuts reference)
6. USER CONTROL — What functions give users control over their experience? (account settings, preferences, notification controls, display options, theme, language)
7. OVERVIEW + INSIGHT — What summary views, dashboards, or analytics would help users understand the state of their data at a glance?

Generate the 12–30 best functions across these angles. Prioritise genuine domain gaps not already covered by stated requirements; skip angles that are already well-covered.

Gate: only generate functions a user can independently navigate to or invoke — a page, form, modal, view, panel, or interactive feature. Do NOT generate system reactions or behavioral properties ("User sees validation error", "User receives confirmation message", "User is redirected when X") — those are acceptance criteria, not functions.

category: "inf"

---

PATH CONSTRUCTION RULES (both passes):

Entity types:
  node            — a page or screen
  element         — a UI control within a page: button, input, form, filter input, search bar, sort control. Structural interactions (filter, search, sort, drag) are always element — never navigation_edge.
  navigation_edge — a user-initiated page transition ("go to", "open", "navigate to")
  data_edge       — a user-initiated backend mutation ("submit", "save", "delete", "create")

PRIMARY flag — one rule for all functions:
- element, navigation_edge, data_edge → always primary: true
- node → always primary: false
- Exception: if the function has no element or edge (sole purpose is asserting a page exists), the node is primary: true

Page scope — two cases:

A. EXISTING PAGE (page already in Step 1):
   node (primary: false) → element(s) (primary: true) → data_edge if applicable (primary: true)
   Do NOT add entry or exit navigation edges — navigation to/from existing pages is already covered by stated and obvious functions.

B. NEW PAGE (page not in Step 1):
   navigation_edge (primary: true, from: existing stated page) → new page node (primary: false) → body elements (primary: true) → navigation_edge (primary: true, to: existing stated page)
   The entry navigation_edge must reference a real existing stated page — never null, never fabricated.

State-variant or result-state trailing entities: OMIT entirely. Path terminates at the last interaction element or edge — never at a post-interaction result state (no "Filtered List", no "Page (updated)").

---

OUTPUT SCHEMA — emit ONLY these fields. req_id, source, tag, placement, strength, weight, testable are computed downstream; do NOT emit them.

[{
  "description": "User can [action]",
  "path": [
    {"type": "node",      "label": "Task Page",   "primary": false},
    {"type": "element",   "label": "merge button", "primary": true,  "ui_node": "Task Page"},
    {"type": "data_edge", "label": "submit merge", "primary": true,  "from": "Task Page", "to": "Task Page"}
  ],
  "category": "sop",
  "confidence_score": 0.88,
  "reasoning": "Login stated (REQ-001); account management is a standard paired function in authenticated apps, absent from stated and obvious reqs",
  "priority": "high",
  "depends_on": ["REQ-001"],
  "functional_area": "auth"
}]

- reasoning: ONE concise sentence covering both why the function belongs and why the confidence level.
- priority: critical / high / medium / low — only needed when confidence_score ≥ 0.80.
- depends_on: REQ-xxx ids of stated functions this builds on; [] if none.

Output ONLY a JSON array (no markdown fences, no preamble)."""


def _build_user_message(
    step0_result: dict,
    step1_requirements: list,
    step2_requirements: list,
    project_summary: str = "",
) -> str:
    project_type = step0_result.get("project_type", "unknown")
    frontend = step0_result.get("frontend_framework") or "None"
    backend = step0_result.get("backend_framework") or "None"

    discovered = step0_result.get("discovered_pages") or []
    pages_str = ", ".join(discovered) if discovered else "(none)"
    summary_line = f"Project purpose: {project_summary}\n" if project_summary else ""

    root_node = _identify_root_node(step1_requirements, discovered)
    root_section = ""
    if root_node:
        root_section = (
            f"=== ROOT / HOME PAGE ===\n"
            f"'{root_node}' is the application entry point.\n"
            f"Do NOT generate functions that treat it as a secondary page with a phantom home above it.\n"
            f"Do NOT generate navigation TO it from a page that does not exist in the stated functions.\n\n"
        )

    def fmt_funcs(reqs, prefix):
        if not reqs:
            return "(none)"
        lines = []
        for i, r in enumerate(reqs, start=1):
            lines.append(f"{i}. [{r.get('req_id', f'{prefix}-{i:03d}')}] {r['description']}")
        return "\n".join(lines)

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend: {frontend} | Backend: {backend}\n"
        f"{summary_line}"
        f"\n=== DISCOVERED PAGES (Step 0) ===\n{pages_str}\n\n"
        f"{root_section}"
        f"=== STATED FUNCTIONS (Step 1 — do not regenerate) ===\n"
        f"{fmt_funcs(step1_requirements, 'REQ')}\n\n"
        f"=== OBVIOUS FUNCTIONS (Step 2 — do not regenerate) ===\n"
        f"{fmt_funcs(step2_requirements, 'OBV')}\n\n"
        f"Run Pass 1 (SOP patterns) then Pass 2 (domain inference)."
    )


def _parse_llm_response(raw: str) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        bracket_pos = text.find("[")
        if bracket_pos > 0:
            text = text[bracket_pos:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        # Walk backwards from the error position to find the last complete object.
        # The inner parse may also fail if },  appears inside a string value, so
        # we loop until we find a position that produces valid JSON.
        search_end = e.pos
        parsed = None
        while search_end > 0:
            last_close = text.rfind("},", 0, search_end)
            if last_close == -1:
                break
            try:
                parsed = json.loads(text[:last_close + 1] + "]")
                break
            except json.JSONDecodeError:
                search_end = last_close
        if parsed is None:
            raise
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-array JSON")
    return parsed


def _validate_and_normalise(
    items: list,
    step1_requirements: list,
    step2_requirements: list,
) -> tuple[list, int]:
    valid_step1_ids = {r.get("req_id", "") for r in step1_requirements}
    valid = []
    dropped = 0

    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        desc = str(item.get("description", "")).strip()
        if not desc:
            dropped += 1
            continue
        reasoning = str(item.get("reasoning", "")).strip()
        if not reasoning:
            dropped += 1
            continue

        conf = item.get("confidence_score")
        try:
            conf = float(conf)
            assert 0.0 <= conf <= 1.0
        except (TypeError, ValueError, AssertionError):
            dropped += 1
            continue
        item["confidence_score"] = conf

        if item.get("category") not in VALID_CATEGORIES:
            dropped += 1
            continue

        path = _validate_path(item.get("path"))
        if path is None:
            dropped += 1
            continue
        item["path"] = path

        # Placement from confidence
        if conf >= 0.80:
            item["placement"] = "l1a"
            item["strength"] = None
            priority = item.get("priority", "medium")
            if priority not in WEIGHT_MAP:
                priority = "medium"
            item["priority"] = priority
            item["weight"] = WEIGHT_MAP[priority]
        elif conf >= 0.60:
            item["placement"] = "l1b"
            item["strength"] = "strongly_implied"
            item["weight"] = 3.0
            item.pop("priority", None)
        elif conf >= 0.40:
            item["placement"] = "l1b"
            item["strength"] = "medium"
            item["weight"] = 2.0
            item.pop("priority", None)
        else:
            item["placement"] = "l1b"
            item["strength"] = "weak"
            item["weight"] = 1.0
            item.pop("priority", None)

        item["tag"] = "generated"
        item["source"] = "generated"
        item.setdefault("testable", True)
        item.setdefault("functional_area", "general")
        # reasoning now covers both rationale and confidence; back-fill the
        # display-only confidence_reason so frontend/types stay unchanged.
        if not item.get("confidence_reason"):
            item["confidence_reason"] = reasoning

        raw_deps = item.get("depends_on", [])
        item["depends_on"] = [
            d for d in (raw_deps if isinstance(raw_deps, list) else [])
            if isinstance(d, str) and d in valid_step1_ids
        ]

        valid.append(item)

    for i, item in enumerate(valid, start=1):
        item["req_id"] = f"GEN-{i:03d}"

    return valid, dropped


# --- Pass 3: dedicated deduplication filter ---
# A separate, single-purpose LLM call. Generation (Passes 1+2) optimises for
# recall; this pass is the precision gate. It sees the full set — stated +
# obvious + ALL generated — so it catches duplicates the generation passes
# structurally cannot: cross-list (generated vs obvious), step-of (a path step
# emitted as a function), and generated-vs-generated.
DEDUP_SYSTEM_PROMPT = """You are a deduplication filter for generated requirements. You receive three lists:
- STATED — functions the app explicitly has (ground truth)
- OBVIOUS — navigation functions already generated
- GENERATED — candidate functions to judge, each with an id

For EACH generated function output "keep" or "drop".

CRITICAL: Generated functions exist precisely to identify capabilities NOT in the stated requirements. "Not in stated requirements" is a KEEP signal, not a drop reason. Only drop when there is genuine semantic overlap with something already listed.

DROP it ONLY if:
1. SAME CAPABILITY as a STATED or OBVIOUS function — judged by meaning, not words. Ignore verb synonyms (edit = update = modify, delete = remove, view = see = browse) and location/container phrasing ("on a page", "from the detail page", "in a modal", "via a form"). "Navigate to X section" equals an obvious "navigate to X page". A refinement of a capability (filter/search/sort) is NOT the same capability as the base list view — "view all products" and "filter products" are distinct.
2. PART OF a stated/obvious function's flow — opening, filling, or submitting a form, confirming, cancelling, or navigating back are STEPS, not standalone functions. If "add employee" is stated, "submit employee form" is a step of it — drop.
3. REDUNDANT with another GENERATED function — keep the single clearest one, drop the rest.

KEEP anything that adds a genuinely new, independent capability — even if the app does not currently implement it and even if it seems unlikely. The purpose of this pass is to surface coverage gaps, not to validate what exists. When two features are genuinely distinct (e.g. an attendance report vs a payroll report), keep both.

Output ONLY a JSON array, one object per generated function in the same order:
[{"id": "GEN-001", "decision": "keep", "duplicate_of": null, "reason": "<short>"}]
Set duplicate_of to the id it duplicates or is a step of (null when kept). No markdown, no preamble."""


def _build_dedup_user_message(stated: list, obvious: list, generated: list) -> str:
    def fmt(reqs):
        if not reqs:
            return "(none)"
        return "\n".join(f"- [{r.get('req_id', '?')}] {r.get('description', '')}" for r in reqs)
    return (
        f"=== STATED ===\n{fmt(stated)}\n\n"
        f"=== OBVIOUS ===\n{fmt(obvious)}\n\n"
        f"=== GENERATED (judge each) ===\n{fmt(generated)}\n\n"
        f"Return one decision per generated function, in order."
    )


async def _dedup_generated(
    stated: list,
    obvious: list,
    generated: list,
    client: anthropic.AsyncAnthropic,
    model: str,
) -> tuple[list, list]:
    """Filter generated functions against stated/obvious/each-other. Returns
    (kept, drop_log). Fails open — on any error, keeps all generated."""
    if not generated:
        return generated, []
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            system=[{"type": "text", "text": DEDUP_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_dedup_user_message(stated, obvious, generated)}],
        )
        decisions = _parse_llm_response(response.content[0].text)
    except Exception:
        return generated, []
    drops = {
        d.get("id"): d for d in decisions
        if isinstance(d, dict) and str(d.get("decision", "")).strip().lower() == "drop"
    }
    kept = [g for g in generated if g.get("req_id") not in drops]
    drop_log = [
        {
            "id": g.get("req_id"),
            "description": g.get("description"),
            "duplicate_of": drops[g.get("req_id")].get("duplicate_of"),
            "reason": drops[g.get("req_id")].get("reason", ""),
        }
        for g in generated if g.get("req_id") in drops
    ]
    return kept, drop_log


async def run(
    step1_requirements: list,
    step2_requirements: list,
    step0_result: dict,
    client: anthropic.AsyncAnthropic,
    project_summary: str = "",
) -> dict:
    model = "claude-haiku-4-5-20251001"
    last_exc = None
    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=16000,
                system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _build_user_message(
                    step0_result, step1_requirements, step2_requirements, project_summary
                )}],
            )
            raw_items = _parse_llm_response(response.content[0].text)
            requirements, dropped = _validate_and_normalise(raw_items, step1_requirements, step2_requirements)
            # Pass 3 — dedicated deduplication against stated + obvious + each other.
            requirements, dedup_log = await _dedup_generated(
                step1_requirements, step2_requirements, requirements, client, model
            )
            for i, item in enumerate(requirements, start=1):
                item["req_id"] = f"GEN-{i:03d}"
            sop = sum(1 for r in requirements if r.get("category") == "sop")
            inf = sum(1 for r in requirements if r.get("category") == "inf")
            return {
                "requirements": requirements,
                "total_count": len(requirements),
                "sop_count": sop,
                "inference_count": inf,
                "llm_model": model,
                "dropped_count": dropped,
                "deduped_count": len(dedup_log),
                "dedup_log": dedup_log,
                "error": None,
            }
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code == 529 and attempt < 2:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_exc = exc
            break
    return {
        "requirements": [], "total_count": 0,
        "sop_count": 0, "inference_count": 0,
        "llm_model": model, "dropped_count": 0,
        "deduped_count": 0, "dedup_log": [], "error": str(last_exc),
    }
