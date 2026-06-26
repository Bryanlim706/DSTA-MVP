"""Step 8.5 — AC Generation.

Hybrid deterministic+LLM generation of acceptance criteria for selected requirements.

Deterministic: goal kind classification (data > structural > navigation > presence),
AC slot set + weight fractions per goal kind, acw mathematics (last AC absorbs rounding).

LLM (Haiku, one call per requirement, concurrent): fills in Given/When/Then prose + test data
for each predetermined slot at intent level.

Per-req caching: req_ids already present in step_8_5 are skipped on re-confirm.
"""
import asyncio
import json
import re

import anthropic

from pipeline.utils import _classify_edge_kind

MODEL = "claude-haiku-4-5-20251001"

_CREATE_KEYWORDS = frozenset(["create", "add", "new", "insert", "register", "submit", "upload"])
_UPDATE_KEYWORDS = frozenset(["update", "edit", "change", "save", "modify", "rename", "set"])
_DELETE_KEYWORDS = frozenset(["delete", "remove", "clear", "cancel", "archive"])

_PRIORITY_WEIGHT = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

_AC_SYSTEM_PROMPT = """\
You are an acceptance criteria author. Given a software requirement and predetermined AC slots,
write the Given/When/Then prose for each slot.

CRITICAL RULES:
1. Write at the INTENT level — what the user does and what must be true afterward. NOT click-by-click steps.
2. The path entities are a grounding hint only — Step 9 renders concrete Playwright/API flows.
3. For DATA goal — create verb: introduce a unique token (e.g. a random string) in Given so the test can verify the entity exists afterward. Persist check re-fetches and re-checks.
4. For DATA goal — update verb: seed an existing entity in Given, change one field to a unique token, assert the new value is stored.
5. For DATA goal — delete verb: seed a token-identified entity in Given, delete it, assert it is gone afterward.
6. Edge case AC: assert the system enforces its essential precondition (e.g. required field missing → operation fails, error is visible, nothing was created/changed). Verify via the unique token being absent.
7. For STRUCTURAL goal: happy_path asserts the result reflects the operation; edge_case asserts an empty/no-match result state.
8. For NAVIGATION goal: happy_path asserts the destination is reached.
9. For PRESENCE goal: happy_path asserts the page or element renders.
10. For BEHAVIORAL goal: fires_when_due asserts entity STATE changes when the condition is met (assert via API/DB state, not UI); not_before_due asserts state is unchanged when condition is NOT yet met.
11. Keep each Given/When/Then to 1–3 sentences. Be concise and unambiguous.

Return a JSON array — one object per slot, in the same order as the slots provided:
[{"given": "...", "when": "...", "then": "..."}]

Return JSON only — no markdown fences."""


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _classify_goal_kind(path: list[dict]) -> str:
    """Precedence: data > structural > navigation > presence."""
    edges = [e for e in path if e.get("type") == "edge"]
    for edge in edges:
        if _classify_edge_kind(edge.get("label", "")) == "data":
            return "data"
    for edge in edges:
        if _classify_edge_kind(edge.get("label", "")) == "structural":
            return "structural"
    for edge in edges:
        if _classify_edge_kind(edge.get("label", "")) == "navigation":
            return "navigation"
    return "presence"


def _classify_data_verb(path: list[dict]) -> str:
    """Sub-classify data goal as create / update / delete."""
    for entity in path:
        if entity.get("type") == "edge":
            words = set(re.findall(r"\b\w+\b", entity.get("label", "").lower()))
            if words & _DELETE_KEYWORDS:
                return "delete"
            if words & _CREATE_KEYWORDS:
                return "create"
            if words & _UPDATE_KEYWORDS:
                return "update"
    return "create"


def _ac_slots(goal_kind: str) -> list[dict]:
    """Return deterministic AC slots for the goal kind.
    Each slot has {type, frac} where fracs sum to 1.0.
    """
    if goal_kind == "data":
        return [
            {"type": "happy_path",  "frac": 0.5},
            {"type": "persistence", "frac": 0.3},
            {"type": "edge_case",   "frac": 0.2},
        ]
    if goal_kind == "structural":
        return [
            {"type": "happy_path", "frac": 0.7},
            {"type": "edge_case",  "frac": 0.3},
        ]
    if goal_kind == "behavioral":
        return [
            {"type": "fires_when_due",  "frac": 0.6},
            {"type": "not_before_due",  "frac": 0.4},
        ]
    # navigation or presence
    return [{"type": "happy_path", "frac": 1.0}]


def _compute_acws(slots: list[dict], weight: float) -> list[float]:
    """Compute individual acw values that sum exactly to weight (last absorbs rounding)."""
    acws: list[float] = []
    running = 0.0
    for i, slot in enumerate(slots):
        if i == len(slots) - 1:
            acw = round(weight - running, 2)
        else:
            acw = round(slot["frac"] * weight, 2)
        acws.append(acw)
        running += acw
    return acws


def _ac_id(req_id: str, pos: int) -> str:
    """Format AC id from req_id + 1-based position."""
    if req_id.startswith("BEH-"):
        return f"AC-{req_id}-{pos}"
    # REQ-001 → AC-001-1; OBV-001 → AC-OBV-001-1; GEN-001 → AC-GEN-001-1
    parts = req_id.split("-", 1)
    tag = parts[0]
    num = parts[1] if len(parts) > 1 else "000"
    if tag == "REQ":
        return f"AC-{num}-{pos}"
    return f"AC-{tag}-{num}-{pos}"


def _test_type(goal_kind: str, test_strategy: dict) -> str:
    if goal_kind == "behavioral":
        return "behavioral"
    primary = (test_strategy.get("primary") or "").lower()
    is_api_only = "api" in primary and "playwright" not in primary and "e2e" not in primary
    if is_api_only and goal_kind == "data":
        return "api"
    return "e2e"


# ---------------------------------------------------------------------------
# LLM prose generation (one call per requirement)
# ---------------------------------------------------------------------------

def _build_req_message(req: dict, goal_kind: str, data_verb: str | None, slots: list[dict]) -> str:
    desc = req.get("description", "")
    path = req.get("path", [])

    path_lines = []
    for entity in path:
        etype = entity.get("type", "")
        label = entity.get("label", "")
        primary = entity.get("primary", True)
        path_lines.append(f"  [{etype}] {label} (primary={primary})")

    slot_descriptions = {
        "happy_path":    "Happy path — the feature works correctly end-to-end",
        "persistence":   "Persistence — data is durably stored and survives a re-fetch",
        "edge_case":     "Edge case — the system enforces its essential precondition (e.g. required field missing → error + nothing created/changed)",
        "fires_when_due":   "Fires when due — behavioral trigger condition IS met; entity STATE changes (assert via API/DB)",
        "not_before_due":   "Not before due — behavioral trigger condition is NOT yet met; entity STATE is unchanged",
    }

    lines: list[str] = []
    lines.append(f"## Requirement: {desc}")
    lines.append(f"Goal kind: {goal_kind}" + (f" ({data_verb})" if data_verb else ""))
    lines.append("")
    if path_lines:
        lines.append("Path (grounding hint — do NOT copy labels literally):")
        lines.extend(path_lines)
        lines.append("")

    lines.append("## AC Slots (fill in Given/When/Then for each, in order):")
    for i, slot in enumerate(slots, 1):
        slot_desc = slot_descriptions.get(slot["type"], slot["type"])
        lines.append(f"Slot {i} — {slot_desc}")
    lines.append("")
    lines.append(
        'Return JSON array with exactly '
        f'{len(slots)} objects: [{{"given":"...","when":"...","then":"..."}}]'
    )
    return "\n".join(lines)


def _parse_gwt(text: str, slots: list[dict]) -> list[dict]:
    bracket_pos = text.find("[")
    if bracket_pos == -1:
        return []
    raw = text[bracket_pos:]
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        last = raw.rfind("},")
        if last == -1:
            return []
        try:
            items = json.loads(raw[: last + 1] + "]")
        except json.JSONDecodeError:
            return []

    if not isinstance(items, list):
        return []

    result = []
    for i, item in enumerate(items):
        if i >= len(slots):
            break
        if not isinstance(item, dict):
            continue
        result.append({
            "given": str(item.get("given", "")).strip(),
            "when":  str(item.get("when", "")).strip(),
            "then":  str(item.get("then", "")).strip(),
        })
    return result


async def _generate_acs_for_req(
    req: dict,
    goal_kind: str,
    data_verb: str | None,
    test_strategy: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    path = req.get("path", [])
    weight = float(req.get("weight", 2.0))
    req_id = req.get("req_id", "REQ-000")
    desc = req.get("description", "")

    is_behavioral = goal_kind == "behavioral"
    req_type = "behavioral" if is_behavioral else ("l1a" if req.get("tag") in ("stated", "obvious", "generated", "custom") else "l1b")

    slots = _ac_slots(goal_kind)
    acws = _compute_acws(slots, weight)
    ttype = _test_type(goal_kind, test_strategy)

    # LLM call for GWT prose
    try:
        user_msg = _build_req_message(req, goal_kind, data_verb, slots)
        response = await client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=_AC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw_text = response.content[0].text if response.content else ""
        gwt_items = _parse_gwt(raw_text, slots)
    except Exception:
        gwt_items = []

    # Build AC list — pad with placeholder if LLM returned fewer than expected
    acs = []
    for i, slot in enumerate(slots):
        gwt = gwt_items[i] if i < len(gwt_items) else {"given": "", "when": "", "then": ""}
        acs.append({
            "ac_id": _ac_id(req_id, i + 1),
            "given": gwt["given"],
            "when":  gwt["when"],
            "then":  gwt["then"],
            "acw":   acws[i],
            "type":  slot["type"],
        })

    return {
        "req_id":   req_id,
        "description": desc,
        "type":     req_type,
        "goal_kind": goal_kind,
        "l1cx":     weight,
        "test_type": ttype,
        "acceptance_criteria": acs,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(
    selected_ids: list[str],
    step3_5: dict,
    step8: dict,
    client: anthropic.AsyncAnthropic,
    existing_step8_5: dict | None = None,
    weight_overrides: dict[str, float] | None = None,
) -> dict:
    """Generate ACs for selected_ids. Skips req_ids already cached in existing_step8_5.

    weight_overrides: req_id → weight from UI priority selector; applied before acw math.
    """
    test_strategy = (step3_5.get("project_context") or {}).get("test_strategy") or {}

    # Build lookup of all selectable requirements
    all_reqs: dict[str, dict] = {}
    for r in step3_5.get("confirmed_requirements", []):
        all_reqs[r["req_id"]] = r
    for r in step3_5.get("advisory_requirements", []):
        all_reqs[r["req_id"]] = r
    for r in step8.get("behavioral_requirements", []):
        all_reqs[r["req_id"]] = r

    # Per-req cache: req_ids already in step_8_5
    cached: dict[str, dict] = {}
    if existing_step8_5:
        for ac_item in existing_step8_5.get("acceptance_criteria", []):
            cached[ac_item["req_id"]] = ac_item

    to_generate = [rid for rid in selected_ids if rid not in cached]

    # Build per-req metadata for generation; apply weight overrides from UI
    tasks = []
    for rid in to_generate:
        req = all_reqs.get(rid)
        if not req:
            continue
        if weight_overrides and rid in weight_overrides:
            req = {**req, "weight": weight_overrides[rid]}
        is_behavioral = rid.startswith("BEH-")
        goal_kind = "behavioral" if is_behavioral else _classify_goal_kind(req.get("path", []))
        data_verb = _classify_data_verb(req.get("path", [])) if goal_kind == "data" else None
        tasks.append((req, goal_kind, data_verb))

    # Concurrent LLM calls — per-call try/except (safe default = empty GWT)
    async def safe_gen(req, goal_kind, data_verb):
        try:
            return await _generate_acs_for_req(req, goal_kind, data_verb, test_strategy, client)
        except Exception:
            slots = _ac_slots(goal_kind)
            acws = _compute_acws(slots, float(req.get("weight", 2.0)))
            rid = req.get("req_id", "")
            is_behavioral = rid.startswith("BEH-")
            req_type = "behavioral" if is_behavioral else (
                "l1a" if req.get("tag") in ("stated", "obvious", "generated", "custom") else "l1b"
            )
            return {
                "req_id": rid,
                "description": req.get("description", ""),
                "type": req_type,
                "goal_kind": goal_kind,
                "l1cx": float(req.get("weight", 2.0)),
                "test_type": _test_type(goal_kind, test_strategy),
                "acceptance_criteria": [
                    {"ac_id": _ac_id(rid, i + 1), "given": "", "when": "", "then": "",
                     "acw": acws[i], "type": slot["type"]}
                    for i, slot in enumerate(slots)
                ],
            }

    new_results = await asyncio.gather(*[safe_gen(r, gk, dv) for r, gk, dv in tasks])

    # Merge cached + newly generated, preserving selected_ids order
    new_by_id = {item["req_id"]: item for item in new_results}
    final = []
    for rid in selected_ids:
        if rid in cached:
            final.append(cached[rid])
        elif rid in new_by_id:
            final.append(new_by_id[rid])

    total_acs = sum(len(item.get("acceptance_criteria", [])) for item in final)
    llm_model = MODEL

    return {
        "acceptance_criteria": final,
        "selected_ids": selected_ids,
        "total_acs": total_acs,
        "llm_model": llm_model,
        "error": None,
    }
