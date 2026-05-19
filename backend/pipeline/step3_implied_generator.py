import asyncio
import json

import anthropic

from pipeline.utils import _extract_nodes_from_paths, _identify_root_node, _is_state_variant, _validate_path

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
VALID_CATEGORIES = {"sop", "inf"}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Generate implied user-facing functions in two structured passes.

Each output is a complete function with a traversal path (entry + body + exit baked in). The path is the Playwright test sequence for this function.

---

CONFIDENCE → PLACEMENT (direct decision):
≥ 0.80 → placement: "l1a"   (goes into completeness scoring, Section 1 of confirmation)
< 0.80 → placement: "l1b"   (advisory only, Section 2 of confirmation)

strength (l1b only): ≥ 0.60 → "strongly_implied" | ≥ 0.40 → "medium" | < 0.40 → "weak"

---

PASS 1 — SOP-TRIGGERED FUNCTIONS

For each node that appears in Step 1 stated functions, check whether any pattern below applies. Generate the corresponding function if it is not already covered by a stated or obvious function.

DEDUPLICATION RULES — skip a pattern if any of these apply:
1. A stated function already covers the exact same interaction type on the same page (same verb + same object, even if worded differently). "filter by size" stated → do not generate "view filter options" — same action, different label.
2. An obvious function (OBV-xxx) already covers navigation TO or FROM a node. Do not generate another "access X" or "open X" or "close X" function for the same node — the obvious functions are authoritative for connectivity.
3. A new-page SOP pattern (auth → profile page; preferences → settings page; etc.) fires on a node that already EXISTS as a stated node with stated sub-functions. If the page already exists, the pattern is satisfied — do not re-generate its contents as new functions.
4. The function would only assert that a page/element exists as a prerequisite for interactions already stated. Do not generate "User can view list" or "User can select item" when the stated functions already have those as primary path entities.

Do NOT skip just because functions share elements — edit-item and delete-item both touch the same list item but are distinct interactions. When in doubt, generate.

Fires ONLY on nodes from Step 1 stated functions — NOT on nodes you generate in this pass.

PATTERN TABLE:

Stated node type → Generate these functions (confidence):
- List node (shows multiple items of same type):
    filter by attribute (~0.82), search (~0.80), sort (~0.68), edit item (~0.72), delete item (~0.65)
- Detail node (shows single item):
    edit (~0.75), delete (~0.70)
- Auth present (login or register stated):
    account management / profile page (~0.87)
- Named changeable status field:
    cross-status overview page (~0.75), filter-by-status element (~0.82)
- Temporal field (dates, deadlines on listed items):
    time-scoped view / calendar view (~0.75)
- Mutable records (edit/update stated):
    audit / history page (~0.60)
- User-configurable preferences stated:
    settings page (~0.82)
- Time-sensitive deadlines or thresholds:
    notification surface (~0.65)
- Multi-user / per-user data stated:
    user profile / identity page (~0.82)

VAGUE FUNCTION UNPACKING:
Functions marked vague: true in Step 1 are priority unpack targets. Apply ALL applicable patterns against their node and generate specific child functions. Set unpacks: "<parent_req_id>" on each child.

category: "sop"

---

PASS 2 — DOMAIN INFERENCE

Read the project_summary and all stated functions. Ask two questions:
1. What functions would a regular user of this specific app return to repeatedly that Pass 1 didn't cover?
2. What functions complete the primary user workflow end-to-end that aren't yet covered?

Pure open-ended domain reasoning — no pattern checklist.
Do NOT re-generate functions already produced in Pass 1 or already stated in Step 1. Before writing each item, confirm it is genuinely new.

category: "inf"

---

PATH CONSTRUCTION RULES (both passes):

1. Every function must have a complete path with entry + body + exit.
   - If introducing a page NOT in Step 1: first path entity MUST be an edge from an existing stated page (never null, never fabricated origin).
   - Include the body elements the user interacts with.
   - Include an exit edge back to an existing stated page.

2. Primary entity flags:
   - SOP list/detail element functions (filter, edit, delete): element = primary, containing page = primary: false
   - SOP element + submit edge: both element and edge are primary
   - New page introductions: entry edge + destination page = both primary; exit edge = primary: false
   - Multi-hop flows: all entities primary
   - State-variant destination nodes ("Task List Page (filtered)"): ALWAYS primary: false

---

OUTPUT SCHEMA:

[{
  "req_id": "GEN-001",
  "description": "User can [action]",
  "path": [
    {"type": "edge",    "label": "navigate to account",  "primary": true,  "from": "Dashboard", "to": "Account Page"},
    {"type": "node",    "label": "Account Page",          "primary": true},
    {"type": "element", "label": "profile information",  "primary": true,  "ui_node": "Account Page"},
    {"type": "element", "label": "change password form", "primary": true,  "ui_node": "Account Page"},
    {"type": "edge",    "label": "return to dashboard",  "primary": false, "from": "Account Page", "to": "Dashboard"}
  ],
  "source": "generated",
  "tag": "generated",
  "category": "sop",
  "reasoning": "Auth pattern — login stated (REQ-001); no account management page in stated or obvious reqs",
  "unpacks": null,
  "depends_on": ["REQ-001"],
  "confidence_score": 0.88,
  "confidence_reason": "Login stated; account management is a standard paired function in authenticated apps",
  "placement": "l1a",
  "priority": "high",
  "strength": null,
  "weight": 3.0,
  "testable": true,
  "functional_area": "auth"
}]

FIELD NOTES:
- unpacks: parent REQ-xxx id if this decomposes a vague Step 1 function; null otherwise
- placement: "l1a" if confidence_score ≥ 0.80, "l1b" otherwise (NOT "l1_recommendation")
- strength: null for l1a; "strongly_implied" / "medium" / "weak" for l1b per bands above
- priority and weight: set for l1a items; for l1b items set weight from strength (strongly_implied=3.0, medium=2.0, weak=1.0)

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
            vague_tag = " [VAGUE — priority unpack target]" if r.get("vague") else ""
            lines.append(f"{i}. [{r.get('req_id', f'{prefix}-{i:03d}')}] {r['description']}{vague_tag}")
        return "\n".join(lines)

    # Show node inventory for SOP pass
    nodes = _extract_nodes_from_paths(step1_requirements)
    nodes_str = ", ".join(nodes) if nodes else "(none)"

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend: {frontend} | Backend: {backend}\n"
        f"{summary_line}"
        f"\n=== DISCOVERED PAGES (Step 0) ===\n{pages_str}\n\n"
        f"{root_section}"
        f"=== STATED FUNCTIONS (Step 1 — do not regenerate) ===\n"
        f"{fmt_funcs(step1_requirements, 'REQ')}\n\n"
        f"=== STATED NODE INVENTORY (for SOP pattern matching) ===\n"
        f"{nodes_str}\n\n"
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
        # Search for the last complete entry before the error position first,
        # then fall back to searching the full string (handles tail truncation).
        last_close = text.rfind("},", 0, e.pos)
        if last_close == -1:
            last_close = text.rfind("},")
        if last_close != -1:
            parsed = json.loads(text[:last_close + 1] + "]")
        else:
            raise
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-array JSON")
    return parsed


def _validate_and_normalise(
    items: list,
    step1_requirements: list,
    step2_requirements: list,
) -> tuple[list, int]:
    all_reqs = step1_requirements + step2_requirements
    valid_req_ids = {r.get("req_id", "") for r in all_reqs}
    stated_lower = {r["description"].lower() for r in all_reqs}
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

        if desc.lower() in stated_lower:
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

        # Remove old field if LLM still emits it
        item.pop("l1_recommendation", None)

        item["tag"] = "generated"
        item["source"] = "generated"
        item.setdefault("testable", True)
        item.setdefault("functional_area", "general")

        raw_deps = item.get("depends_on", [])
        item["depends_on"] = [d for d in (raw_deps if isinstance(raw_deps, list) else []) if d in valid_req_ids]

        # Validate unpacks pointer
        unpacks = item.get("unpacks")
        if unpacks and unpacks not in valid_step1_ids:
            item["unpacks"] = None
        else:
            item.setdefault("unpacks", None)

        valid.append(item)

    for i, item in enumerate(valid, start=1):
        item["req_id"] = f"GEN-{i:03d}"

    return valid, dropped


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
                max_tokens=8000,
                system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _build_user_message(
                    step0_result, step1_requirements, step2_requirements, project_summary
                )}],
            )
            raw_items = _parse_llm_response(response.content[0].text)
            requirements, dropped = _validate_and_normalise(raw_items, step1_requirements, step2_requirements)
            sop = sum(1 for r in requirements if r.get("category") == "sop")
            inf = sum(1 for r in requirements if r.get("category") == "inf")
            return {
                "requirements": requirements,
                "total_count": len(requirements),
                "sop_count": sop,
                "inference_count": inf,
                "llm_model": model,
                "dropped_count": dropped,
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
        "llm_model": model, "dropped_count": 0, "error": str(last_exc),
    }
