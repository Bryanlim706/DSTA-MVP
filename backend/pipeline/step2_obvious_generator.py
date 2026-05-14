import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Your job is to check 5 specific gaps in the stated requirements and generate a requirement only when a gap exists.

Answer each check YES or NO. Then output a JSON array containing ONLY the requirements for your NO answers. If all answers are YES, output [].

---

CHECK 1 — HOME PAGE AFTER LOGIN
Does the stated list include ANY requirement that mentions a home page, main page, or describes features displayed on the home page?
Rule: If a requirement mentions "home page" or "home.html" — even when describing its content ("displays X on home page") — the home page IS stated. Answer YES and generate nothing.
→ YES (any requirement mentions home page, home.html, or main page): SKIP, generate nothing
→ NO (home page not mentioned anywhere in stated requirements): generate { description: "System must display a home page after successful login." }

CHECK 2 — OUTPUT VIEWS
For each stated add/create capability: is the created data shown in a stated list, table, or view?
A stated view counts when ANY requirement describes:
- A table, list, or navigation bar containing that data type (e.g. "table with goal columns", "navigation bar with all categories")
- A page that displays that data (e.g. "category page with goal data table")
If any of these patterns exist, answer YES for that data type — do NOT generate a separate view.
→ YES for all: no item generated
→ NO (data can only be added, nowhere to view it): generate { description: "System must display [type] in a list/view." }

CHECK 3 — STATUS CHANGE CONTROL
HARD RULE: Before generating anything for CHECK 3, you must quote an EXACT phrase from the stated requirements that describes items being SORTED or ORDERED by status (e.g. "sink to the bottom", "prioritised at the top", "sorted by status"). If you cannot quote such a phrase, you MUST output nothing for CHECK 3 — no exceptions, no substitutions.
A status column in a table is NOT sufficient. "Users can add goals with a status field" is NOT sufficient.
→ NO quotable sorting phrase: SKIP, output nothing for CHECK 3
→ YES (you can quote an explicit sort phrase): is there a stated status change control?
  → YES: no item generated
  → NO: generate { description: "System must allow users to change the status of a [item]." }

CHECK 4 — NAVIGATION TO ADD PAGES
For each stated add/create capability: is there a stated button, link, or UI element that invokes it?
Count as YES if any requirement describes a button, link, or page that allows users to do X from page Y — even if it does not explicitly say "navigate to". A stated button that triggers a capability IS the navigation.
→ YES for all: no item generated
→ NO (a create capability is stated but no button, link, or UI element to invoke it from any page): generate { description: "System must provide a way to reach [create page]." }

CHECK 5 — BACK NAVIGATION
For each stated sub-page or detail page (create/edit forms, category pages, etc.):
Is back or home navigation already stated for it?
→ YES for all: no item generated
→ NO for a page: generate { description: "System must provide back/home navigation from [page]." }

---

HARD STOP. Do not generate ANYTHING outside these 5 checks. Specifically excluded:
- Auth guards, login redirects, session checks → not a check above
- Empty state messages → not a check above
- Error messages, validation feedback → not a check above
- Data persistence, session management → not a check above
- Anything phrased "System must X when/if Y" → not a check above

If you are unsure whether something fits a check: it does not. Output nothing for it.

---

RULES
1. reason field: state which check (1–5) this item answers and which stated requirement it bridges.
2. Do not regenerate a stated requirement in different words.
3. Maximum 5 items. Fewer is correct when stated requirements are complete.
4. priority: critical = app unusable without it; high = needed; medium = helpful.
5. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
6. functional_area: short snake_case.

Return ONLY a valid JSON array. No markdown, no explanation:
[{
  "req_id": "OBV-001",
  "description": "System must [verb] [object]",
  "source": "obvious",
  "reasoning": "CHECK [N] — [which stated req] present, [gap] missing",
  "tag": "obvious",
  "priority": "high",
  "weight": 3.0,
  "testable": true,
  "functional_area": "task_management"
}]"""


def _build_user_message(step0_result: dict, step1_requirements: list) -> str:
    project_type = step0_result.get("project_type", "unknown")
    frontend = step0_result.get("frontend_framework") or "None"
    backend = step0_result.get("backend_framework") or "None"

    if step1_requirements:
        stated = "\n".join(
            f"{i}. [{r.get('functional_area', 'general')}] {r['description']}"
            for i, r in enumerate(step1_requirements, start=1)
        )
    else:
        stated = "(none)"

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend framework: {frontend}\n"
        f"Backend framework: {backend}\n\n"
        f"=== STATED REQUIREMENTS (do not regenerate these) ===\n"
        f"{stated}\n\n"
        f"Apply the gap-finding algorithm to generate obvious requirements for this application."
    )


def _parse_llm_response(raw: str) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        # Skip any reasoning text before the JSON array
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


def _validate_and_normalise(items: list, step1_requirements: list) -> tuple[list, int]:
    stated_lower = {r["description"].lower() for r in step1_requirements}
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

        if desc.lower() in stated_lower:
            dropped += 1
            continue

        priority = item.get("priority", "medium")
        if priority not in WEIGHT_MAP:
            priority = "medium"
        item["priority"] = priority
        item["weight"] = WEIGHT_MAP[priority]
        item["tag"] = "obvious"
        item["source"] = "obvious"
        item.setdefault("testable", True)
        item.setdefault("functional_area", "general")
        valid.append(item)

    for i, item in enumerate(valid, start=1):
        item["req_id"] = f"OBV-{i:03d}"

    return valid, dropped


async def run(
    step1_requirements: list,
    step0_result: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    model = "claude-haiku-4-5-20251001"

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
            system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_user_message(step0_result, step1_requirements)}],
        )
        raw_items = _parse_llm_response(response.content[0].text)
        requirements, dropped = _validate_and_normalise(raw_items, step1_requirements)
    except Exception as exc:
        return {
            "requirements": [],
            "total_count": 0,
            "llm_model": model,
            "dropped_count": 0,
            "error": str(exc),
        }

    return {
        "requirements": requirements,
        "total_count": len(requirements),
        "llm_model": model,
        "dropped_count": dropped,
    }
