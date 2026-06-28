import json
import re

import anthropic

_SYSTEM_PROMPT = """\
You are a software feature advisor. Given a codebase inventory (database models, \
API endpoints, frontend routes, live UI elements) and confirmed requirements, \
you identify improvement opportunities grounded in what actually exists.

Generate Type B positive-grounded suggestions — features that naturally extend \
the codebase's existing structure. Each suggestion must:
- Reference specific models, endpoints, or UI elements that appear in the inventory
- Extend existing functionality (not rewrite it)
- Not duplicate any confirmed L1a or advisory L1b requirement

Return a JSON array only — no markdown fences, no prose outside the JSON."""

_VALID_PRIORITIES = {"high", "medium", "low"}


def _build_user_message(step3_5: dict, step4: dict, step5: dict) -> str:
    project_summary = step3_5.get("project_summary") or "No project summary available."
    l1a = step3_5.get("confirmed_requirements", [])
    l1b = step3_5.get("advisory_requirements", [])

    models = step4.get("database_models", [])
    impl_units = step4.get("implementation_units", [])
    endpoints = [
        f"{u.get('method', '?')} {u.get('path', '?')}"
        for u in impl_units
        if u.get("kind") == "api_endpoint" and u.get("path")
    ][:40]
    routes = [r["path"] for r in step4.get("frontend_routes", [])]

    page_elements: list[str] = []
    for pg in step5.get("pages", [])[:15]:
        route = pg.get("route", "")
        elems = [
            e.get("label", "")
            for e in pg.get("elements", [])
            if e.get("label") and str(e["label"]).strip()
        ][:6]
        if elems:
            page_elements.append(f"  {route}: {', '.join(elems)}")

    lines: list[str] = []
    lines.append("## Project Summary")
    lines.append(project_summary)
    lines.append("")

    lines.append("## Confirmed L1a Requirements (already covered — do not duplicate)")
    for r in l1a:
        lines.append(f"- {r.get('req_id', '')} — {r.get('description', '')}")
    lines.append("")

    lines.append("## Advisory L1b Requirements (already suggested — do not re-suggest)")
    for r in l1b[:25]:
        lines.append(f"- {r.get('req_id', '')} — {r.get('description', '')}")
    lines.append("")

    lines.append("## Codebase Inventory")

    lines.append("### Database Models")
    lines.append(", ".join(models) if models else "None detected")
    lines.append("")

    lines.append("### API Endpoints")
    if endpoints:
        lines.extend(endpoints)
    else:
        lines.append("None detected")
    lines.append("")

    lines.append("### Frontend Routes")
    lines.append(", ".join(routes) if routes else "None detected")
    lines.append("")

    if page_elements:
        lines.append("### Live UI Elements (per page)")
        lines.extend(page_elements)
        lines.append("")

    lines.append(
        "## Task\n"
        "Generate 4–8 codebase-grounded improvement suggestions. "
        "Each suggestion must be a natural extension of what is already present in the inventory above — "
        "do NOT invent models, endpoints, or pages that don't exist.\n\n"
        "Focus on: data relationship extensions visible in the schema, missing CRUD dimensions on existing entities, "
        "cross-entity overview views, and workflow completeness gaps visible from the endpoint and UI structure.\n\n"
        "Return a JSON array only:\n"
        "[\n"
        "  {\n"
        '    "suggestion_id": "FA-POS-001",\n'
        '    "description": "User can ...",\n'
        '    "grounded_in": {\n'
        '      "models": ["Model1"],\n'
        '      "endpoints": ["GET /api/..."],\n'
        '      "rationale": "why this specific codebase structure suggests this feature"\n'
        "    },\n"
        '    "l1a_connection": "REQ-xxx or null",\n'
        '    "priority": "high|medium|low"\n'
        "  }\n"
        "]\n\n"
        "Return fewer suggestions if the codebase is very small or the inventory is sparse. "
        "Return the JSON array only — no other text."
    )

    return "\n".join(lines)


def _recover_truncated(raw: str) -> list:
    """Brace-aware recovery for a truncated/malformed JSON array.

    Walks ``raw`` (which must start at ``[``) tracking string state and object
    nesting depth, and truncates after the last *complete top-level* object.
    Unlike ``rfind("},")``, this is not fooled by nested objects (e.g. the
    ``grounded_in`` sub-object) that also end in ``},``.
    """
    depth = 0
    in_str = False
    escape = False
    last_obj_end = -1
    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = in_str
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_obj_end = i + 1
    if last_obj_end == -1:
        return []
    try:
        parsed = json.loads(raw[:last_obj_end] + "]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _extract_array(text: str) -> list:
    """Extract a JSON array from an LLM response.

    Tolerates markdown code fences and trailing prose by slicing from the first
    ``[`` to the last ``]`` before parsing; falls back to the raw tail, then to
    a brace-aware recovery for genuinely truncated responses.
    """
    start = text.find("[")
    if start == -1:
        return []
    end = text.rfind("]")
    candidates = []
    if end > start:
        candidates.append(text[start : end + 1])  # fence-/prose-stripped
    candidates.append(text[start:])  # raw tail
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return _recover_truncated(text[start:])


def _parse_response(text: str) -> list[dict]:
    items = _extract_array(text)
    if not isinstance(items, list):
        return []

    results = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        desc = item.get("description", "")
        if not isinstance(desc, str) or not desc.strip():
            continue

        suggestion_id = item.get("suggestion_id")
        if not isinstance(suggestion_id, str) or not re.match(r"FA-POS-\d+", suggestion_id):
            suggestion_id = f"FA-POS-{i:03d}"

        grounded = item.get("grounded_in", {})
        if not isinstance(grounded, dict):
            grounded = {}

        grounded_models = grounded.get("models", [])
        if not isinstance(grounded_models, list):
            grounded_models = []
        grounded_endpoints = grounded.get("endpoints", [])
        if not isinstance(grounded_endpoints, list):
            grounded_endpoints = []
        rationale = grounded.get("rationale", "")
        if not isinstance(rationale, str):
            rationale = ""

        priority = item.get("priority", "medium")
        if priority not in _VALID_PRIORITIES:
            priority = "medium"

        l1a_conn = item.get("l1a_connection")
        if l1a_conn is not None and not isinstance(l1a_conn, str):
            l1a_conn = None
        if isinstance(l1a_conn, str) and l1a_conn.lower() in ("null", "none", ""):
            l1a_conn = None

        results.append(
            {
                "suggestion_id": suggestion_id,
                "description": desc.strip(),
                "grounded_in": {
                    "models": [str(m) for m in grounded_models],
                    "endpoints": [str(e) for e in grounded_endpoints],
                    "rationale": rationale.strip(),
                },
                "l1a_connection": l1a_conn,
                "priority": priority,
            }
        )

    return results


async def run(
    step3_5: dict,
    step4: dict,
    step5: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    try:
        user_msg = _build_user_message(step3_5, step4, step5)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text if response.content else ""
        suggestions = _parse_response(text)
        # Renumber suggestion_ids to be sequential
        for i, s in enumerate(suggestions, 1):
            s["suggestion_id"] = f"FA-POS-{i:03d}"

        return {
            "suggestions": suggestions,
            "total_count": len(suggestions),
            "llm_model": response.model,
            "error": None,
        }
    except Exception as exc:
        return {
            "suggestions": [],
            "total_count": 0,
            "llm_model": None,
            "error": str(exc),
        }
