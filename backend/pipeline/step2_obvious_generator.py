import asyncio
import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Your job is to find graph connectivity gaps — pages that cannot be reached or cannot be left — in the application's stated requirements.

Work through the 3 checks below IN ORDER. For each check, reason explicitly YES/NO per node, then output a JSON array.

---

CHECK 1 — BUILD THE NODE LIST

List every page or screen in this application by combining:
(a) Pages named in the stated requirements
(b) Pages from the discovered page files (provided below)

Deduplicate: if the same page appears in both, list it once.
This is your node list. All subsequent checks operate on these nodes.

---

CHECK 2 — ENTRY PATHS (how does the user GET to each node?)

For each node EXCEPT the landing/home page:
Is there a stated requirement describing a button, link, navbar item, sidebar item, or any UI element that navigates TO this node?

→ YES: skip
→ NO: generate a requirement

---

CHECK 3 — EXIT PATHS (how does the user LEAVE each node?)

For each node:
Is there at least one stated requirement describing a way to leave it — back button, breadcrumb, navbar, sidebar, or any navigation element?

Terminal pages: home/dashboard with a persistent navbar count as having exit paths.
→ YES: skip
→ NO: generate a requirement. Do NOT prescribe the mechanism — that is a design decision.

---

THERE ARE ONLY 3 CHECKS. Do not invent CHECK 4, CHECK 5, or any other check. Every item in your JSON output must cite CHECK 2 or CHECK 3 in its reasoning. If your reasoning would cite any other check number, discard the item — it does not belong here.

NEVER GENERATE (hard stops — discard immediately, do not include in JSON):
- Invocation controls: buttons, checkboxes, or forms that invoke a stated capability. If "user can add a task" is stated, do NOT generate "System must provide a button/control/form to add a task." The control is implied by the capability itself.
- Observable outcomes: displays, confirmations, or status indicators showing the result of a stated operation. "System must display added item in the list" — discard. "System must show completion status" — discard.
- Auth guards, login redirects, session checks
- Empty state messages, error messages, validation feedback
- Anything phrased "System must X when Y"

TEST before including any item: ask "Is this a NAVIGATION GAP — a page with no way in (CHECK 2) or no way out (CHECK 3)?" If the answer is no, discard it.

RULES:
1. depends_on: list the REQ-XXX ids from stated requirements that make this requirement necessary.
2. reasoning: must start with "CHECK 2 —" or "CHECK 3 —" and name the specific node.
3. Priority: critical = absence makes app non-functional; high = core navigation; medium = supporting.
4. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
5. functional_area: short snake_case.

Output ONLY a JSON array (no markdown fences, no preamble text):
[{
  "req_id": "OBV-001",
  "description": "System must provide a way to navigate to [node].",
  "source": "obvious",
  "reasoning": "CHECK 2 — [node] has no stated inbound navigation element",
  "tag": "obvious",
  "depends_on": ["REQ-003"],
  "priority": "high",
  "weight": 3.0,
  "testable": true,
  "functional_area": "navigation"
}]"""


def _identify_root_node(step1_requirements: list, discovered_pages: list) -> str | None:
    """
    Returns the name of the root/home node when it can be determined unambiguously.
    The root node is exempt from CHECK 2 — it IS the entry point; there is no page before it.
    Heuristics (in priority order):
    1. Only one node-type requirement exists → that page is the root.
    2. discovered_pages contains only index.html (single-route SPA) → the sole stated node is root.
    3. A node whose ui_node matches a common home name and is marked critical.
    """
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


def _build_user_message(step0_result: dict, step1_requirements: list) -> str:
    project_type = step0_result.get("project_type", "unknown")
    frontend = step0_result.get("frontend_framework") or "None"
    backend = step0_result.get("backend_framework") or "None"

    if step1_requirements:
        stated = "\n".join(
            f"{i}. [{r.get('req_id', f'REQ-{i:03d}')}] [{r.get('functional_area', 'general')}] {r['description']}"
            for i, r in enumerate(step1_requirements, start=1)
        )
    else:
        stated = "(none)"

    discovered = step0_result.get("discovered_pages") or []
    pages_str = ", ".join(discovered) if discovered else "(none found — infer pages from stated requirements only)"

    root_node = _identify_root_node(step1_requirements, discovered)
    if root_node:
        root_section = (
            f"=== ROOT / HOME PAGE ===\n"
            f"'{root_node}' is the application entry point (home/root page).\n"
            f"Do NOT apply CHECK 2 to it — there is no separate page before it.\n"
            f"Do NOT invent a phantom landing page to navigate FROM.\n\n"
        )
    else:
        root_section = ""

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend framework: {frontend}\n"
        f"Backend framework: {backend}\n\n"
        f"=== DISCOVERED PAGE FILES (from codebase) ===\n"
        f"{pages_str}\n\n"
        f"{root_section}"
        f"=== STATED REQUIREMENTS (do not regenerate these) ===\n"
        f"{stated}\n\n"
        f"Apply all 3 checks to find navigation gaps."
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


def _validate_and_normalise(items: list, step1_requirements: list) -> tuple[list, int]:
    stated_lower = {r["description"].lower() for r in step1_requirements}
    valid_req_ids = {r.get("req_id", "") for r in step1_requirements}
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
        reasoning_up = reasoning.upper()
        if not (reasoning_up.startswith("CHECK 2") or reasoning_up.startswith("CHECK 3")):
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

        raw_deps = item.get("depends_on", [])
        item["depends_on"] = [d for d in (raw_deps if isinstance(raw_deps, list) else []) if d in valid_req_ids]

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
    last_exc = None
    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4096,
                system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _build_user_message(step0_result, step1_requirements)}],
            )
            raw_items = _parse_llm_response(response.content[0].text)
            requirements, dropped = _validate_and_normalise(raw_items, step1_requirements)
            return {"requirements": requirements, "total_count": len(requirements), "llm_model": model, "dropped_count": dropped}
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code == 529 and attempt < 2:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_exc = exc
            break
    return {"requirements": [], "total_count": 0, "llm_model": model, "dropped_count": 0, "error": str(last_exc)}
