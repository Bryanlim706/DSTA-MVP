import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Generate obvious functional requirements for a software application — capabilities so fundamental that any user expects them, yet so self-evident that nobody writes them down.

Each requirement you generate must be one of exactly two types. If an item does not fit either type, do not generate it.

---

TYPE A — RESULT OR STATE-CHANGE BRIDGE

A dedicated page, view, or interactive control that either:
(a) Shows the user the RESULT of a stated capability, making it observable and verifiable, OR
(b) Lets the user change a value that a stated capability depends on to function.

The key distinction is OUTPUT vs INPUT. Ask: is this the output side of a stated requirement, or the input/invocation side?

Generate (output or state-change — the result side):
- "User can view their task list" — the visible output of "user can add tasks"; without it the add cannot be confirmed
- "User can toggle a task's completion status" — the state change that makes "tasks sort by status" verifiable

Skip (input or invocation — this IS already the stated capability):
- "System displays a login form" — the form is how login is invoked, not its output; it is the stated login requirement
- "System provides a form to add categories" — the form is how add-category is invoked; it is the stated add requirement
- "System shows a registration form" — the form is the stated registration capability itself

---

TYPE B — NAVIGATION AFFORDANCE

A dedicated clickable element (button, link) that moves the user between screens the app already has, where no such navigation is covered by a stated requirement.

Generate:
- "User can navigate back to the home page from a category sub-page" — no back nav stated for sub-pages
- "User can reach the registration page from the login page" — entry point not stated

Skip:
- "System redirects unauthenticated users to login when accessing protected pages" — automatic behavior, not user-clickable
- "System redirects to login after logout" — automatic side-effect, not user-clickable

---

NEVER GENERATE

Behavioral properties — they occur automatically without a user-clickable element:
- Auth guards: redirecting unauthenticated users, blocking unauthorized access
- Session management: clearing sessions on logout, persisting sessions across reloads
- Data isolation: users seeing only their own data, server-side access control and authorization

Reactions — what the system does when a condition is met:
- Error feedback: "show error when login fails", "show error when duplicate category name"
- Validation responses: "show error when username already taken"
- Empty states: "show message when no items exist"
- Any item that naturally phrases as "System must X when Y"

---

SEMANTIC DEDUPLICATION

Do not regenerate any requirement that is semantically equivalent to a stated requirement, even if worded differently.

Form/capability identity: A form or page that is the interface through which a stated capability is invoked is NOT a new obvious requirement — it is the stated capability viewed from the UI angle. Login form = login requirement. Add-category form = add-category requirement. Skip these.

---

RULES

1. Only generate Type A or Type B items (defined above). If an item does not fit either type, do not generate it.

2. Do NOT generate: filtering, sorting, bulk operations, error handling, security behaviors, session behaviors, notifications, advanced settings. These belong in acceptance criteria or Step 3.

3. Semantic deduplication: see above.

4. Do not invent features beyond what the project type and stated requirements clearly imply.

5. Generate 3–10 requirements. A high-quality small set beats a large set with wrong items. If stated requirements already cover all obvious output views and navigation, generate fewer.

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
  "reasoning": "One sentence: which stated requirement this bridges to, and why it is required for that requirement to be user-verifiable",
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
