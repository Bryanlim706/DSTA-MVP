import asyncio
import json

import anthropic

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Find graph connectivity gaps — pages with no way in or no way out — based on the stated functions.

Each output is a NAVIGATION FUNCTION with a path array. The navigation edge is always primary; surrounding nodes are context (primary: false).

Work through the 3 checks IN ORDER:

---

CHECK 1 — EXTRACT THE NODE LIST

From the stated functions, collect every unique page/screen label from path entities with type "node", excluding state-variant nodes (labels with a parenthetical like "filtered", "sorted", "updated"). Also include pages from discovered page files. Deduplicate. This is your node list.

---

CHECK 2 — ENTRY PATHS (how does the user GET to each node?)

For each node EXCEPT the root/home page:
Does any stated function's path contain an edge (type: "edge") whose "to" field names this node?
→ YES: skip — entry already stated
→ NO: generate a navigation function

Navigation function for CHECK 2:
{
  "description": "User can navigate to [Node]",
  "path": [
    {"type": "edge", "label": "navigation link", "primary": true, "from": null, "to": "[Node]"},
    {"type": "node", "label": "[Node]", "primary": false}
  ],
  "reasoning": "CHECK 2 — [Node] has no stated inbound navigation"
}

(from: null = mechanism-agnostic source)

---

CHECK 3 — EXIT PATHS (how does the user LEAVE each node?)

For each node:
Does any stated function's path contain an edge (type: "edge") whose "from" field names this node?
→ YES: skip
→ NO: generate a navigation function

Navigation function for CHECK 3:
{
  "description": "User can leave [Node]",
  "path": [
    {"type": "node", "label": "[Node]", "primary": false},
    {"type": "edge", "label": "exit path", "primary": true, "from": "[Node]", "to": null}
  ],
  "reasoning": "CHECK 3 — [Node] has no stated exit path"
}

(to: null = mechanism-agnostic destination)

---

THERE ARE ONLY 3 CHECKS. Every item must cite CHECK 2 or CHECK 3 in its reasoning.

NEVER GENERATE:
- Invocation controls (buttons or forms for stated capabilities)
- Observable outcomes (displays, confirmations, status indicators)
- Auth guards, session checks, login redirects
- Empty states, error messages, validation feedback
- Anything phrased "when Y" or "after Y"

RULES:
1. depends_on: REQ-XXX ids of stated functions that make this navigation necessary
2. reasoning: must start with "CHECK 2 —" or "CHECK 3 —" and name the specific node
3. priority: critical = absence makes app non-functional; high = core navigation; medium = supporting
4. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
5. functional_area: "navigation"

Output ONLY a JSON array (no markdown fences, no preamble):
[{
  "req_id": "OBV-001",
  "description": "User can navigate to Profile Page",
  "path": [
    {"type": "edge", "label": "navigation link", "primary": true, "from": null, "to": "Profile Page"},
    {"type": "node", "label": "Profile Page", "primary": false}
  ],
  "source": "obvious",
  "reasoning": "CHECK 2 — Profile Page has no stated inbound navigation",
  "tag": "obvious",
  "depends_on": ["REQ-005"],
  "priority": "high",
  "weight": 3.0,
  "testable": true,
  "functional_area": "navigation"
}]"""


def _is_state_variant(label: str) -> bool:
    return "(" in label and label.rstrip().endswith(")")


def _extract_nodes_from_paths(step1_requirements: list) -> list[str]:
    """Return unique non-state-variant node labels from all Step 1 function paths."""
    seen = {}
    for func in step1_requirements:
        for entity in func.get("path", []):
            if entity.get("type") == "node":
                label = str(entity.get("label", "")).strip()
                if label and not _is_state_variant(label) and label not in seen:
                    seen[label] = True
    return list(seen.keys())


def _extract_edges_from_paths(step1_requirements: list) -> list[dict]:
    """Return all edge entities from Step 1 function paths."""
    edges = []
    for func in step1_requirements:
        for entity in func.get("path", []):
            if entity.get("type") == "edge":
                edges.append(entity)
    return edges


def _identify_root_node(step1_requirements: list, discovered_pages: list) -> str | None:
    unique_nodes = _extract_nodes_from_paths(step1_requirements)

    if len(unique_nodes) == 1:
        return unique_nodes[0]

    is_single_file_spa = (
        len(discovered_pages) == 1
        and any(p.lower() in ("index.html", "index.htm") for p in discovered_pages)
    )
    if is_single_file_spa and unique_nodes:
        return unique_nodes[0]

    home_names = {"home", "landing", "index", "main", "dashboard", "root"}
    for func in step1_requirements:
        if func.get("priority") == "critical":
            for entity in func.get("path", []):
                if entity.get("type") == "node" and entity.get("primary"):
                    label = str(entity.get("label", ""))
                    if any(h in label.lower() for h in home_names):
                        return label

    return None


def _build_user_message(step0_result: dict, step1_requirements: list) -> str:
    project_type = step0_result.get("project_type", "unknown")
    frontend = step0_result.get("frontend_framework") or "None"
    backend = step0_result.get("backend_framework") or "None"

    discovered = step0_result.get("discovered_pages") or []
    pages_str = ", ".join(discovered) if discovered else "(none found)"

    root_node = _identify_root_node(step1_requirements, discovered)
    root_section = ""
    if root_node:
        root_section = (
            f"=== ROOT / HOME PAGE ===\n"
            f"'{root_node}' is the application entry point.\n"
            f"Do NOT apply CHECK 2 to it — it has no page before it.\n"
            f"Do NOT invent a phantom landing page to navigate from.\n\n"
        )

    # Format stated functions with their edge inventory for connectivity checking
    if step1_requirements:
        func_lines = []
        for i, r in enumerate(step1_requirements, start=1):
            vague_tag = " [VAGUE]" if r.get("vague") else ""
            func_lines.append(
                f"{i}. [{r.get('req_id', f'REQ-{i:03d}')}] {r['description']}{vague_tag}"
            )
        stated = "\n".join(func_lines)

        # Show edge inventory so the LLM can check connectivity without re-parsing paths
        edges = _extract_edges_from_paths(step1_requirements)
        edge_lines = []
        for e in edges:
            from_ = e.get("from") or "?"
            to_ = e.get("to") or "?"
            edge_lines.append(f"  {from_} → {to_}")
        edges_str = "\n".join(edge_lines) if edge_lines else "  (none stated)"

        nodes = _extract_nodes_from_paths(step1_requirements)
        nodes_str = ", ".join(nodes) if nodes else "(none)"
    else:
        stated = "(none)"
        edges_str = "  (none stated)"
        nodes_str = "(none)"

    return (
        f"=== PROJECT CONTEXT ===\n"
        f"Project type: {project_type}\n"
        f"Frontend: {frontend} | Backend: {backend}\n\n"
        f"=== DISCOVERED PAGE FILES (from codebase) ===\n"
        f"{pages_str}\n\n"
        f"{root_section}"
        f"=== STATED FUNCTIONS (Step 1) ===\n"
        f"{stated}\n\n"
        f"=== NODE INVENTORY (extracted from function paths) ===\n"
        f"{nodes_str}\n\n"
        f"=== STATED EDGES (from function paths) ===\n"
        f"{edges_str}\n\n"
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

        # Validate and normalise path
        path = item.get("path")
        if not isinstance(path, list) or len(path) == 0:
            dropped += 1
            continue
        clean_path = []
        for entity in path:
            if not isinstance(entity, dict):
                continue
            if entity.get("type") not in {"node", "element", "edge"}:
                continue
            # Default primary: edges are primary, nodes are context in nav functions
            entity.setdefault("primary", entity.get("type") == "edge")
            clean_path.append(entity)
        if not clean_path:
            dropped += 1
            continue
        item["path"] = clean_path

        priority = item.get("priority", "high")
        if priority not in WEIGHT_MAP:
            priority = "high"
        item["priority"] = priority
        item["weight"] = WEIGHT_MAP[priority]
        item["tag"] = "obvious"
        item["source"] = "obvious"
        item.setdefault("testable", True)
        item.setdefault("functional_area", "navigation")

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
