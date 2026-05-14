import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are an obvious requirements generator for software quality evaluation (ISO 25010 Functional Suitability).

Given a project type and a list of already-stated requirements, generate ONLY obvious functional requirements — behaviours so fundamental that any user of this type of application expects them by default, yet would never think to write them down explicitly.

Generate from TWO angles:

**Angle 1 — Dependency connectors:** For each stated requirement, what must be true for it to be independently testable end-to-end? If a stated requirement produces an outcome the user cannot observe without another function, that observable function is obvious.
Example: if "user can add tasks" is stated, "user can view their list of tasks" is obvious — without visible output the add function cannot be user-verified.

**Angle 2 — App-type usability:** What navigation, structure, and affordance functions would any user of this app type expect to be present, regardless of what is stated? Think of things a user would only notice when missing.
Examples: navigation back to a parent page from any sub-page that has no navbar; empty states on list views (first-use experience); redirect to login when accessing a protected page without a session.

Rules:
1. A requirement belongs here only if a user could point to a distinct UI screen, button, or API endpoint that implements it.
2. DO NOT include: nice-to-have features, optimisations, bulk operations, sorting, filtering, export, notifications, advanced settings — these are "implied" (Step 3), not "obvious".
3. Do NOT regenerate any requirement that is semantically equivalent to a stated requirement, even if worded differently. Ask: "Does this describe the same user action and outcome as any stated requirement?" If yes, skip it. A login form existing is not a new function — it is the stated login requirement. A registration page existing is not a new function — it is the stated registration requirement.
4. Only generate requirements for features directly implied by the project type and stated requirements. Do not invent features beyond the app's evident purpose.
5. Generate 5–20 requirements. If stated requirements already cover the obvious ones, generate fewer (or return an empty array).
6. weight derives from priority: critical=4.0  high=3.0  medium=2.0  low=1.0
7. testable: set false only if the item cannot be expressed as a pass/fail behaviour.
8. DO NOT generate requirements about internal system behaviour — error handling messages, confirmation dialogs, data persistence mechanics, and form validation feedback are acceptance criteria of functional requirements, not standalone obvious functions.
9. Assign 'critical' ONLY if the requirement's absence makes the entire application non-functional for its primary purpose. Most core functions should be 'high'. Over-assigning 'critical' inflates the scoring denominator unfairly.
10. functional_area: assign a short snake_case label for the root feature this requirement belongs to. Requirements sharing the same UI component or backend module share the same label. Use "general" if it spans the whole app.

Return ONLY a valid JSON array — no markdown fences, no explanation, just raw JSON:
[{
  "req_id": "OBV-001",
  "description": "System must [verb] [object] — short imperative sentence",
  "source": "obvious",
  "reasoning": "One sentence: why a user of this app type would take this for granted",
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
        f"=== ALREADY STATED REQUIREMENTS (do not regenerate any of these) ===\n"
        f"{stated}\n\n"
        f"Generate obvious functional requirements for this application."
    )


def _parse_llm_response(raw: str) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    parsed = json.loads(text)
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
