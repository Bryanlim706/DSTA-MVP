import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Generate obvious functional requirements for a software application — capabilities so fundamental that any user expects them, yet so self-evident that nobody writes them down.

Each requirement you generate represents something a user can do or experience in the application's interface. It will later be located in the codebase and automatically tested. Only generate items a user can directly interact with or navigate to.

---

CORE DISTINCTION: capabilities vs reactions

A CAPABILITY is something a user can directly navigate to, interact with, or observe. It has a dedicated place in the interface — its own page, form, button, or view. Generate these.

A REACTION is what the system does when or if something else happens. Reactions are test assertions on existing capabilities, not requirements. Do not generate them.

THE SIGNAL: If you find yourself writing "System must [do X] when [condition]" or "System must [do X] if [condition]" — that is a reaction. Skip it.

---

EXAMPLES

Generate these (capabilities — each is a dedicated user-facing feature):
- "User can view their task list" — a dedicated list view the user navigates to
- "User can delete a task" — a dedicated delete action the user can take
- "User can navigate back to the home page from a sub-page" — a dedicated back/home button
- "User can see their profile or account page" — a dedicated view the user navigates to

Skip these (reactions — they describe what happens when something else occurs):
- "System redirects to login when user is not authenticated" — reaction to auth state
- "Session is cleared when user logs out" — side effect of the logout action
- "Error is shown when a form is submitted with missing fields" — reaction to validation
- "Task list shows a message when no tasks exist" — reaction to an empty state
- "Data is saved to the database when the form is submitted" — reaction to form submission

---

GENERATION ANGLES

Angle 1 — Dependency connectors.
Look at each stated requirement and ask: what other capability must exist for this to be user-verifiable? If "user can add tasks" is stated but no list view is stated, the list view is obvious — without it, the user cannot confirm the add worked.

Angle 2 — App-type affordances.
What dedicated screens, views, or navigation elements would any user of this type of application expect to find, regardless of what is stated? Focus on structural gaps: pages that have no way out (missing back navigation), core views the user needs to orient themselves, entry points required by the app type.

---

RULES

1. Generate only capabilities — things a user can directly navigate to or interact with (see examples above).

2. Do NOT generate: nice-to-have features, filtering, sorting, bulk operations, export, notifications, advanced settings. Those are enhancements for a later step.

3. Semantic deduplication. If a stated requirement already covers a capability, even if worded differently, do not regenerate it. A login page is not a new capability — it is the stated login requirement. A registration page is not a new capability — it is the stated registration requirement.

4. Do not invent features beyond what the project type and stated requirements clearly imply.

5. Generate 5–15 requirements. If stated requirements already cover the obvious ones, generate fewer.

6. Priority:
   - critical: Absence makes the entire application non-functional for its primary purpose. Use for at most 1-2 requirements.
   - high: Core expected function. Use for most requirements.
   - medium: Supporting function.
   - low: Minor.

7. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0

8. functional_area: A short snake_case label for the feature group (e.g. "auth", "task_management"). Requirements that share the same page or backend model share the same label.

---

Return ONLY a valid JSON array. No markdown fences, no explanation, no other text:
[{
  "req_id": "OBV-001",
  "description": "System must [verb] [object]",
  "source": "obvious",
  "reasoning": "One sentence: why any user of this app type would take this for granted",
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
