import json
import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
VALID_CATEGORIES = {"sop_a", "sop_b", "inf_c", "inf_d", "inf_e", "structural_edge"}

LLM_SYSTEM_PROMPT = """You are a requirements analyst generating implied and obvious requirements for a web application. Items span both L1a (FCom-scored) and L1b (FA-scored), determined by confidence score.

CONFIDENCE → PLACEMENT:
- confidence ≥ 0.80 → l1_recommendation: "l1a"  (user prompted to add to confirmed requirements)
- confidence 0.60–0.79 → l1_recommendation: "l1b", strength: "strongly_implied"
- confidence 0.40–0.59 → l1_recommendation: "l1b", strength: "medium"
- confidence < 0.40    → l1_recommendation: "l1b", strength: "weak"

Work through the 5 categories + structural edges. Reason before each item.

---

SOP-A — PATTERN-TRIGGERED NEW NODES [fires on vocabulary]

Check stated requirements for trigger words. If a pattern fires AND no equivalent page is stated, generate the proposed node. These are new PAGES/SCREENS only.

Pattern A — Authentication
Trigger: "login", "sign in", "sign up", "register", "registration", "authentication", "log out"
Proposed: profile or account information screen
Typical confidence: 0.85–0.92

Pattern B — Offline data collection
Trigger: "offline", "without internet", "local storage", "cached", "offline [any operation]"
Proposed: screen to view records collected while offline
Typical confidence: 0.80–0.90

Pattern C — Multi-user with distinct roles or data
Trigger: "role", "admin", "teacher", "student", "per-user", "my [data type]"
Proposed: screen showing current user identity or role
Typical confidence: 0.75–0.88

Pattern D — Data synchronization
Trigger: "sync", "synchronize", "upload pending", "sync when connected"
Proposed: sync status or sync history screen
Typical confidence: 0.60–0.75

Rule: a button that INVOKES an action does NOT satisfy a pattern — a result/status VIEW is distinct.
→ category: "sop_a"

---

SOP-B — RULE-TRIGGERED NEW ELEMENTS WITHIN EXISTING NODES [fires on node-type detection]

For each existing node, identify its type from stated requirements, then apply the rule set.
Only generate for nodes that have stated Step 1 content. Generate ELEMENTS within pages, not new pages.

Node type detection:
- List/collection node: shows multiple items of the same type (contacts, tasks, records)
- Detail/view node: shows a single item's full details
- Dashboard/summary node: shows aggregate counts or summary statistics

LIST RULES (for list/collection nodes):
- Filter: confidence 0.80–0.88 (higher if items have filterable attributes like status/category/date)
- Search: confidence 0.78–0.85 (higher if list likely large)
- Sort controls: confidence 0.65–0.75
- Pagination: confidence 0.70–0.80 if data set likely large; 0.30–0.50 for small fixed sets

DETAIL RULES (for detail/view nodes):
- Edit control: confidence 0.70–0.82 (higher if edit capability exists elsewhere in L1a)
- Delete control: confidence 0.65–0.78 (higher if delete exists elsewhere in L1a)

DASHBOARD RULES (for dashboard/summary nodes):
- Date range filter: confidence 0.60–0.72
- Data export: confidence 0.45–0.60

STATUS-FIELD RULE (node shows items with a named, changeable status field):
- Filter by status: confidence 0.78–0.85
- Bulk status update: confidence 0.40–0.55

Do NOT generate elements already covered by stated requirements for that node.
→ category: "sop_b"

---

INF-C — REASONING-BASED NEW NODES [open LLM reasoning]

Reason over the full L1a graph. Propose new pages NOT covered by SOP-A patterns.
Must be anchored to specific L1a req_ids — do not invent from app type alone.

Ask: Is there data modified/deleted in L1a with no stated audit/history page?
      Is there data tracked over time with no stated reports/analytics page?
      Are there user-specific settings implied with no stated settings/preferences page?
      Are there implied events/alerts with no stated notifications page?

→ category: "inf_c"

---

INF-D — CONTEXTUAL NEW ELEMENTS WITHIN EXISTING NODES [open LLM reasoning]

Suggest elements within existing nodes that SOP-B rules did not catch — elements specific
to this app's domain, data model, or combination of existing stated elements.
Examples: CRM → export-to-CSV; scheduling app → calendar view; multi-language → language selector.
Only generate if traceable to specific L1a requirements for that node.
Confidence generally 0.40–0.75 (more speculative than SOP-B).

→ category: "inf_d"

---

INF-E — MISSING EDGES BETWEEN EXISTING NODES [open LLM reasoning]

Step 2 guarantees minimum connectivity (every node reachable and escapable).
INF-E asks: what navigation edges between EXISTING nodes do users reasonably expect beyond the minimum?
Types: cross-links between related siblings, contextual links, multi-level shortcuts.
Do NOT re-generate minimum entry/exit paths — Step 2 already covers those.
Confidence: closely related cross-links 0.65–0.80; shortcuts 0.40–0.60.

→ category: "inf_e"

---

STRUCTURAL EDGES FOR NEW NODES (do this last)

For every new node you generated in SOP-A or INF-C:
Check the stated and obvious requirements — is there already a stated entry path TO this node?
Is there already a stated exit path FROM this node?
If NO entry path stated → generate entry edge, confidence_score: 1.0
If NO exit path stated → generate exit edge, confidence_score: 1.0
→ category: "structural_edge"

---

NEVER GENERATE:
- Auth guards, login redirects, session checks
- Error messages, empty states, validation feedback
- Anything phrased "System must X when Y"
- Items already covered by stated or obvious requirements

DEDUPLICATION: Do not regenerate items semantically equivalent to stated or Step 2 requirements.

RULES:
1. depends_on: list REQ-XXX or OBV-XXX ids this item depends on.
2. confidence_score: 0.0–1.0 per guidance above.
3. confidence_reason: one sentence explaining the score.
4. l1_recommendation: "l1a" if ≥ 0.80, else "l1b".
5. strength: null for l1a; "strongly_implied"/"medium"/"weak" for l1b.
6. priority: for l1a items only — critical/high/medium/low (determines FCom weight).
7. weight: for l1a — priority-derived (4.0/3.0/2.0/1.0); for l1b — strength-derived (3.0/2.0/1.0).
8. functional_area: short snake_case.
9. category: one of "sop_a"/"sop_b"/"inf_c"/"inf_d"/"inf_e"/"structural_edge".

Output your reasoning per category first, then a JSON array (no markdown fences):
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


def _build_user_message(step0_result: dict, step1_requirements: list, step2_requirements: list) -> str:
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

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend: {frontend} | Backend: {backend}\n\n"
        f"=== DISCOVERED PAGES (Step 0) ===\n{pages_str}\n\n"
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

        valid.append(item)

    for i, item in enumerate(valid, start=1):
        item["req_id"] = f"GEN-{i:03d}"

    return valid, dropped


async def run(
    step1_requirements: list,
    step2_requirements: list,
    step0_result: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    model = "claude-haiku-4-5-20251001"
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_user_message(step0_result, step1_requirements, step2_requirements)}],
        )
        raw_items = _parse_llm_response(response.content[0].text)
        requirements, dropped = _validate_and_normalise(raw_items, step1_requirements, step2_requirements)
    except Exception as exc:
        return {
            "requirements": [], "total_count": 0,
            "sop_count": 0, "inference_count": 0,
            "llm_model": model, "dropped_count": 0, "error": str(exc),
        }

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
