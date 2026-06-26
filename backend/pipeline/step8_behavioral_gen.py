"""Step 8 — Behavioral Generation.

Extracts orphan autonomous behaviors from the requirements text: state changes or triggered
actions that happen WITHOUT any user-initiated UI action (auto-reset, scheduled notifications,
session/cache expiry, background sync). These correctly fail Step 1's actor+action gate and
live here as BEH-xxx requirements for correctness testing (Step 8.5).
"""
import json

import anthropic

_SYSTEM_PROMPT = """\
You are a software behavior analyst. Given requirements text and a codebase inventory, extract
**orphan autonomous behaviors** — state changes or triggered actions that occur WITHOUT any
user-initiated UI action (auto-reset, scheduled notifications, session/cache expiry, background
sync, etc.).

These behaviors correctly fail Step 1's user-actor gate ("User can [action]") because the real
subject is the system, scheduler, timer, or background process — not the user. They belong here
for behavioral correctness testing.

For each behavior:
- The actor is the system/scheduler/timer/background process (NOT the user)
- The behavior changes the state of a real database entity when a condition or time is met
- There is NO matching user-triggerable endpoint in the implementation units
- If a user can also trigger the same state change via an endpoint, skip it — it is already a
  functional requirement and will be covered by AC generation for that requirement

Return a JSON array only — no markdown fences, no prose outside the JSON.
If no autonomous behaviors exist, return an empty array []."""

_PRIORITY_WEIGHT = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}


def _build_user_message(requirements_text: str, step3_5: dict, step4: dict) -> str:
    project_summary = step3_5.get("project_summary") or "No project summary available."
    confirmed = step3_5.get("confirmed_requirements", [])
    advisory = step3_5.get("advisory_requirements", [])

    impl_units = step4.get("implementation_units", [])
    endpoints = [
        f"{u.get('method', '?')} {u.get('path', '?')}"
        for u in impl_units
        if u.get("kind") == "api_endpoint" and u.get("path")
    ][:40]
    models = step4.get("database_models", [])

    lines: list[str] = []
    lines.append("## Requirements Text (raw upload)")
    lines.append((requirements_text or "")[:8000])
    lines.append("")

    lines.append("## Project Summary")
    lines.append(project_summary)
    lines.append("")

    lines.append(
        "## Already-confirmed Functional Requirements (user-triggered — do NOT re-emit these)"
    )
    for r in confirmed:
        lines.append(f"- {r.get('req_id', '')} — {r.get('description', '')}")
    for r in advisory[:20]:
        lines.append(f"- {r.get('req_id', '')} — {r.get('description', '')}")
    lines.append("")

    lines.append(
        "## Database Models (stateful entities that can change autonomously)"
    )
    lines.append(", ".join(models) if models else "None detected")
    lines.append("")

    lines.append(
        "## Implementation Units (user-triggerable endpoints — "
        "any behavior matching one of these is functional, NOT behavioral)"
    )
    if endpoints:
        lines.extend(endpoints)
    else:
        lines.append("None detected")
    lines.append("")

    lines.append(
        "## Task\n"
        "Extract all autonomous/scheduled behaviors from the requirements text that satisfy ALL of:\n"
        "1. No matching user-triggered endpoint in Implementation Units above\n"
        "2. Actor is the system/scheduler/timer/background process (not the user)\n"
        "3. Changes the state of a Database Model entity\n\n"
        "Return a JSON array:\n"
        "[\n"
        "  {\n"
        '    "description": "System auto-resets task status to todo every midnight",\n'
        '    "source_quote": "verbatim quote from requirements text, or null",\n'
        '    "priority": "high|medium|low"\n'
        "  }\n"
        "]\n\n"
        "Return [] if no autonomous behaviors are present. Return the JSON array only."
    )

    return "\n".join(lines)


def _parse_response(text: str) -> list[dict]:
    bracket_pos = text.find("[")
    if bracket_pos == -1:
        return []
    raw = text[bracket_pos:]
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        last = raw.rfind("},")
        if last == -1:
            return []
        try:
            items = json.loads(raw[: last + 1] + "]")
        except json.JSONDecodeError:
            return []

    if not isinstance(items, list):
        return []

    results: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = item.get("description", "")
        if not isinstance(desc, str) or not desc.strip():
            continue

        priority = item.get("priority", "medium")
        if priority not in _PRIORITY_WEIGHT:
            priority = "medium"

        source_quote = item.get("source_quote")
        if not isinstance(source_quote, str) or not source_quote.strip():
            source_quote = None

        results.append({
            "req_id": f"BEH-{len(results) + 1:03d}",
            "description": desc.strip(),
            "path": [{"type": "node", "label": "System", "primary": True}],
            "priority": priority,
            "weight": _PRIORITY_WEIGHT[priority],
            "source_quote": source_quote,
        })

    return results


async def run(
    requirements_text: str,
    step3_5: dict,
    step4: dict,
    client: anthropic.AsyncAnthropic,
) -> dict:
    try:
        user_msg = _build_user_message(requirements_text, step3_5, step4)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text if response.content else ""
        requirements = _parse_response(text)

        return {
            "behavioral_requirements": requirements,
            "llm_model": response.model,
            "error": None,
        }
    except Exception as exc:
        return {
            "behavioral_requirements": [],
            "llm_model": None,
            "error": str(exc),
        }
