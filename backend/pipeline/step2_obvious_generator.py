import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Your job is to find gaps in the stated requirements by systematically checking the application graph — pages, navigation paths, and operation completeness.

Work through the 6 checks below IN ORDER. For each check, answer YES or NO, then generate a requirement only for each NO answer. Output your YES/NO reasoning first, then a JSON array of generated requirements at the end.

---

CHECK 1 — BUILD THE NODE LIST

List every page or screen in this application by combining:
(a) Pages named in the stated requirements
(b) Pages from the discovered page files (provided below)

Deduplicate: if the same page appears in both sources, list it once.
This is your node list. All subsequent checks operate on these nodes.

---

CHECK 2 — ENTRY PATHS (how does the user GET to each node?)

For each node (except the landing/home page): is there a stated requirement describing a button, link, navbar item, sidebar item, or any UI element that navigates TO it?

→ YES: skip
→ NO: generate { description: "System must provide a way to navigate to [node]." }

---

CHECK 3 — EXIT PATHS (how does the user LEAVE each node?)

For each node: is there at least one stated requirement describing a way to leave it — back button, breadcrumb, navbar, sidebar, or any navigation element?

Terminal pages (the home/dashboard with a persistent navbar count as having exit paths via the navbar).
→ YES: skip
→ NO: generate { description: "System must provide navigation away from [node]." }

Do NOT prescribe the mechanism (back button vs breadcrumb vs navbar) — that is a design decision.

---

CHECK 4 — OBSERVABLE OUTCOMES (can the user see what their action did?)

Go through the STATED REQUIREMENTS list item by item. For each stated requirement that describes a user-triggered operation — this includes any action that changes data, changes state, or produces visible output (add, edit, delete, upload, submit a form, filter, search, generate, mark complete, assign, confirm, save, start an analysis, or any other capability) — ask:

Is there another stated requirement that shows the user the result? This could be a view, list, table, status indicator, updated display, or any visible output confirming the operation happened.

→ YES (another stated requirement shows the result): skip
→ NO (no stated requirement shows the result): generate { description: "System must display the result of [operation] to the user." }

Note: filtering and searching produce visible output (filtered/searched results). If filtering is stated as a capability, a display of the filtered results is required.

---

CHECK 5 — OPERATION INVOCATION (can the user trigger each capability?)

Go through the STATED REQUIREMENTS list item by item. For each stated capability, ask:

Is there a stated requirement describing a UI control — button, form, toggle, dropdown, link, menu item — that lets the user invoke this capability from the relevant page?

If the stated requirement itself already describes the control that invokes it (e.g. "the plus button opens the add row form"), answer YES.
→ YES: skip
→ NO: generate { description: "System must provide a control to invoke [capability] from [page]." }

---

CHECK 6 — STATUS CHANGE CONTROL (HARD RULE)

Before generating anything for this check, you MUST quote an EXACT phrase from the stated requirements that describes items being sorted or ordered by status (e.g. "sink to the bottom", "prioritised at the top", "sorted by status"). If you cannot quote such a phrase, output nothing for this check — no exceptions.

→ No quotable sorting phrase: SKIP entirely, generate nothing
→ Sorting phrase exists AND a user-controllable status change is already stated: skip
→ Sorting phrase exists AND no status change control is stated: generate { description: "System must allow users to change the status of a [item]." }

---

NEVER GENERATE (hard stops — not covered by any check above):
- Auth guards, login redirects, session checks ("redirect when unauthenticated", "protect routes")
- Empty state messages ("show message when list is empty")
- Error messages, validation feedback ("show error when X fails")
- Data persistence, session management ("persist data across reloads")
- Anything phrased "System must X when Y" or "System must X if Y"

SEMANTIC DEDUPLICATION:
Do not regenerate anything semantically equivalent to a stated requirement. A form that invokes a stated capability IS that capability — do not generate "display login form" if login is already stated.

---

RULES
1. reasoning: state which check number and which stated requirement or node it addresses.
2. Generate as many requirements as the checks identify — there is no upper limit. Quality is the constraint: only generate items that answer a definitive NO to one of the checks above.
3. Priority: critical = absence makes app non-functional (max 1-2); high = core; medium = supporting.
4. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
5. functional_area: short snake_case.

Output your YES/NO check reasoning first, then:
Return a valid JSON array (no markdown fences):
[{
  "req_id": "OBV-001",
  "description": "System must [verb] [object]",
  "source": "obvious",
  "reasoning": "CHECK [N] — [node/operation] has no stated [entry/exit/invocation/outcome]",
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

    discovered = step0_result.get("discovered_pages") or []
    pages_str = ", ".join(discovered) if discovered else "(none found — infer pages from stated requirements only)"

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend framework: {frontend}\n"
        f"Backend framework: {backend}\n\n"
        f"=== DISCOVERED PAGE FILES (from codebase) ===\n"
        f"{pages_str}\n\n"
        f"=== STATED REQUIREMENTS (do not regenerate these) ===\n"
        f"{stated}\n\n"
        f"Apply the 6-check graph analysis to generate obvious requirements for this application."
    )


def _parse_llm_response(raw: str) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        # LLM emits YES/NO reasoning before the JSON array — skip to the first [
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
