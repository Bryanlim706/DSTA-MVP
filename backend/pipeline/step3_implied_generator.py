import asyncio
import json
import re
import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
VALID_CATEGORIES = {"sop_a", "sop_b", "inf_c", "inf_d", "inf_e", "structural_edge"}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Generate implied requirements across 5 categories + structural edges.

CONFIDENCE → PLACEMENT:
- ≥ 0.80 → l1_recommendation: "l1a" | 0.60–0.79 → "l1b" strength: "strongly_implied"
- 0.40–0.59 → "l1b" strength: "medium" | < 0.40 → "l1b" strength: "weak"

---

SOP-A — PATTERN-TRIGGERED NEW NODES (new pages/screens only)
Fire when trigger words appear in stated reqs AND no equivalent page exists.
- Auth trigger ("login","sign in","register","log out") → profile/account screen (conf ~0.85–0.92)
- Offline trigger ("offline","local storage","cached") → offline records screen (conf ~0.80–0.90)
- Multi-user trigger ("role","admin","per-user","my [data]") → user identity screen (conf ~0.75–0.88)
- Sync trigger ("sync","synchronize","upload pending") → sync status screen (conf ~0.60–0.75)
A button invoking an action does NOT satisfy a pattern — a result/status VIEW is distinct.
→ category: "sop_a"

SOP-B — RULE-TRIGGERED ELEMENTS WITHIN EXISTING NODES (elements, not new pages)
SCOPE: Only fires for page-level nodes that appear in the STATED REQUIREMENTS list (type=node from Step 1).
- Do NOT apply SOP-B to Step 1 elements (type=element) — elements are sub-components, not pages.
- Do NOT apply SOP-B to nodes you generate in SOP-A or INF-C during this pass. Those nodes get navigation paths via structural_edge only — applying SOP-B to them creates duplicate navigation requirements.
Do NOT duplicate stated requirements.
- List node (multiple items same type): filter ~0.82, search ~0.80, sort ~0.68, pagination ~0.50–0.75, edit item ~0.72, delete item ~0.65
- Detail node (single item): edit ~0.75, delete ~0.70
- Dashboard node (aggregates): date-range filter ~0.65, export ~0.50
- Status-field node (named changeable status OR page named "overview"/"summary"/"report" that aggregates items with status): filter-by-status ~0.82, bulk-update ~0.45
→ category: "sop_b"

INF-C — REASONING-BASED NEW NODES (open reasoning, anchored to specific req_ids)
Propose pages not covered by SOP-A. Ask: audit/history page for modified data? reports/analytics for tracked data? settings/preferences page? notifications page?
→ category: "inf_c"

INF-D — CONTEXTUAL ELEMENTS WITHIN EXISTING NODES (domain-specific, SOP-B didn't catch)
Must be traceable to specific L1a reqs. Confidence 0.40–0.75.
INF-D elements are UI controls or data displays a user can directly see or interact with — not behavioral outcomes of using those controls. Ask: "Is this something a user taps, reads, or fills in?" If yes, it belongs here. If it is what the system does in response (feedback, side-effect, state change), it belongs in acceptance criteria.
For action/form pages (any page whose name starts with a verb: "Take X", "Add X", "Record X", "Submit X", "Create X", "Edit X"): always consider what input fields the user must provide. Ask: does the action involve a subject/person being acted upon (→ selector/picker element)? does it require a date or time (→ date/time picker)? does it require a quantity or reference ID (→ number/text input)? Generate these as INF-D elements anchored to the action page node.
→ category: "inf_d"

INF-E — MISSING EDGES BETWEEN EXISTING NODES (beyond Step 2 minimum)
Cross-links, contextual links, shortcuts between nodes already in the graph. Do NOT re-generate Step 2 entry/exit paths.
→ category: "inf_e"

STRUCTURAL EDGES (do last)
For every new node from SOP-A or INF-C: if no stated entry path → generate one (conf 1.0); if no stated exit path → generate one (conf 1.0).
→ category: "structural_edge"

---

GENERATION GATE — apply to every item before including it:
"Can a user independently navigate to this, or directly invoke it (click, tap, fill, select) as a standalone UI entity that exists regardless of what the user just did?"
→ YES: include it — it is a page, panel, form, button, input, or interactive control with its own place in the UI.
→ NO: discard it — it is a Y-axis acceptance criterion, not a requirement. Items that only appear as a consequence of another action, describe HOW something works, or express a quality property have no dedicated UI home. The test: if the item cannot be described without the phrase "when X" or "after X", it is not a requirement.
DEDUPLICATION: skip anything semantically equivalent to stated or Step 2 requirements.

RULES:
1. depends_on: REQ-XXX or OBV-XXX ids this item depends on.
2. confidence_score: 0.0–1.0. confidence_reason: one sentence.
3. l1_recommendation / strength derived from confidence per bands above.
4. priority: l1a items only (critical/high/medium/low → weight 4/3/2/1).
5. weight: l1b items → strength-derived (strongly_implied=3, medium=2, weak=1).
6. functional_area: short snake_case.
7. category: "sop_a"/"sop_b"/"inf_c"/"inf_d"/"inf_e"/"structural_edge".

Output ONLY a JSON array (no markdown fences, no preamble text):
[{
  "req_id": "GEN-001",
  "description": "System must [verb] [object]",
  "source": "generated",
  "tag": "generated",
  "category": "sop_a",
  "reasoning": "Pattern A — login stated (REQ-001); no profile screen found in stated or obvious reqs",
  "depends_on": ["REQ-001"],
  "confidence_score": 0.88,
  "confidence_reason": "Login is stated; users universally expect a profile/account screen in authenticated apps",
  "l1_recommendation": "l1a",
  "priority": "high",
  "strength": null,
  "weight": 3.0,
  "testable": true,
  "functional_area": "auth"
}]"""


def _identify_root_node(step1_requirements: list, discovered_pages: list) -> str | None:
    node_reqs = [r for r in step1_requirements if r.get("type") == "node"]
    if len(node_reqs) == 1:
        return node_reqs[0].get("ui_node") or node_reqs[0].get("description")
    is_single_file_spa = (
        len(discovered_pages) == 1
        and any(p.lower() in ("index.html", "index.htm") for p in discovered_pages)
    )
    if is_single_file_spa and len(node_reqs) >= 1:
        return node_reqs[0].get("ui_node") or node_reqs[0].get("description")
    home_names = {"home", "landing", "index", "main", "dashboard", "root"}
    for r in node_reqs:
        if r.get("priority") == "critical":
            name = (r.get("ui_node") or r.get("description") or "").lower()
            if any(h in name for h in home_names):
                return r.get("ui_node") or r.get("description")
    return None


def _build_user_message(
    step0_result: dict,
    step1_requirements: list,
    step2_requirements: list,
    project_summary: str = "",
) -> str:
    project_type = step0_result.get("project_type", "unknown")
    frontend = step0_result.get("frontend_framework") or "None"
    backend = step0_result.get("backend_framework") or "None"

    def fmt(reqs, prefix):
        if not reqs:
            return "(none)"
        return "\n".join(
            f"{i}. [{r.get('req_id', f'{prefix}-{i:03d}')}] [{r.get('functional_area', 'general')}] {r['description']}"
            for i, r in enumerate(reqs, start=1)
        )

    discovered = step0_result.get("discovered_pages") or []
    pages_str = ", ".join(discovered) if discovered else "(none)"
    summary_line = f"Project purpose: {project_summary}\n" if project_summary else ""

    root_node = _identify_root_node(step1_requirements, discovered)
    if root_node:
        root_section = (
            f"=== ROOT / HOME PAGE ===\n"
            f"'{root_node}' is the application entry point (home/root page).\n"
            f"Do NOT generate INF-C nodes that treat it as a secondary page with a phantom home above it.\n"
            f"Do NOT generate INF-E navigation TO it from a page that does not exist in the stated requirements.\n\n"
        )
    else:
        root_section = ""

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend: {frontend} | Backend: {backend}\n"
        f"{summary_line}"
        f"\n=== DISCOVERED PAGES (Step 0) ===\n{pages_str}\n\n"
        f"{root_section}"
        f"=== STATED REQUIREMENTS (Step 1 — do not regenerate) ===\n"
        f"{fmt(step1_requirements, 'REQ')}\n\n"
        f"=== OBVIOUS REQUIREMENTS (Step 2 — do not regenerate) ===\n"
        f"{fmt(step2_requirements, 'OBV')}\n\n"
        f"Apply all 5 categories + structural edges."
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
    except json.JSONDecodeError:
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
    valid = []
    dropped = 0
    # Maps LLM-assigned GEN-XXX id → l1_recommendation for SOP-A/INF-C nodes,
    # used below to propagate l1b status to their structural edges.
    sop_inf_map: dict[str, str] = {}

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

        if conf >= 0.80:
            item["l1_recommendation"] = "l1a"
            item["strength"] = None
            priority = item.get("priority", "medium")
            if priority not in WEIGHT_MAP:
                priority = "medium"
            item["priority"] = priority
            item["weight"] = WEIGHT_MAP[priority]
        elif conf >= 0.60:
            item["l1_recommendation"] = "l1b"
            item["strength"] = "strongly_implied"
            item["weight"] = 3.0
            item.pop("priority", None)
        elif conf >= 0.40:
            item["l1_recommendation"] = "l1b"
            item["strength"] = "medium"
            item["weight"] = 2.0
            item.pop("priority", None)
        else:
            item["l1_recommendation"] = "l1b"
            item["strength"] = "weak"
            item["weight"] = 1.0
            item.pop("priority", None)

        item["tag"] = "generated"
        item["source"] = "generated"
        item.setdefault("testable", True)
        item.setdefault("functional_area", "general")

        raw_deps = item.get("depends_on", [])
        item["depends_on"] = [d for d in (raw_deps if isinstance(raw_deps, list) else []) if d in valid_req_ids]

        if item.get("category") in {"sop_a", "inf_c"}:
            orig_id = item.get("req_id", "")
            if orig_id:
                sop_inf_map[orig_id] = item["l1_recommendation"]

        valid.append(item)

    # Fix: structural edges must inherit their parent node's l1_recommendation.
    # A structural edge for an L1b node cannot itself be L1a.
    for item in valid:
        if item.get("category") == "structural_edge":
            gen_refs = re.findall(r'GEN-\d+', item.get("reasoning", ""))
            parent_l1 = next((sop_inf_map[r] for r in gen_refs if r in sop_inf_map), None)
            if parent_l1 == "l1b":
                item["l1_recommendation"] = "l1b"
                item["strength"] = "strongly_implied"
                item["weight"] = 3.0
                item.pop("priority", None)

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
                messages=[{"role": "user", "content": _build_user_message(step0_result, step1_requirements, step2_requirements, project_summary)}],
            )
            raw_items = _parse_llm_response(response.content[0].text)
            requirements, dropped = _validate_and_normalise(raw_items, step1_requirements, step2_requirements)
            sop = sum(1 for r in requirements if r.get("category", "").startswith("sop"))
            inf = sum(1 for r in requirements if r.get("category", "").startswith("inf"))
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
