import asyncio
import json
import os
import re
from pathlib import Path

import anthropic

from pipeline.utils import _validate_path

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "venv", ".venv",
    "__pycache__", "coverage", ".cache", "out", "target", "vendor",
    ".claude", ".cursor", ".github", ".vscode", ".idea",
}

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

SPEC_DOC_EXTENSIONS = {".md", ".rst", ".txt"}
SPEC_DOC_KEYWORDS = {
    "requirement", "spec", "specification",
    "stories", "acceptance", "feature", "backlog",
    "use-case", "usecase", "epic", "functional",
}
README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())


MAX_DOCS = 30
MAX_CHARS_PER_DOC = 12000
MAX_README_DEPTH = 2

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Extract stated requirements as user-facing functions — each function describes a goal a user can directly perform in the UI.

---

EXTRACTION GATE

Before extracting any item, ask: "Does this text describe a goal a user can directly perform?"
YES → extract as a function.
NO → skip entirely.

Rejects: backend subjects (app.py, database, server), quality attributes (responsive, secure, accessible, performant), automatic behaviors the user cannot directly invoke, system reactions ("X happens when Y" or "system must X when Y"). If an item cannot be described without a conditional, skip it.

---

FUNCTION DESCRIPTION

Active voice, user as subject: "User can [action]"
Examples: "User can log in" | "User can add a task" | "User can view the dashboard"

---

PATH CONSTRUCTION

Each function includes a path: an ordered list of UI entities the user traverses to complete the goal.

Entity types:
  node    — a page or screen ("Login Page", "Dashboard", "Task Detail")
  element — a UI control, form, button, or input within a specific page
  edge    — a navigation action between two pages

Fields per entity:
  type     — "node" | "element" | "edge"
  label    — short human-readable name
  primary  — true if this entity is what the function is fundamentally asserting; false if it is context
  ui_node  — (elements only) the containing page name
  from/to  — (edges only) source and destination page names

PRIMARY ENTITY RULES:
- Multi-hop flows (log in, register, checkout): ALL entities are primary — every step is load-bearing.
- New page access (first function to assert a page exists): page node + entry edge are both primary.
- Feature functions (add, filter, edit, delete on an existing page): the element(s) and submit edge are primary; the containing page node is primary: false if the page is stated by another function.
- Navigation cross-links: the edge is primary; surrounding nodes are primary: false.
- State-variant destination nodes ("Task List Page (filtered)", "Task List Page (updated)"): OMIT them entirely — they are not scored. End the path at the last interaction (submit edge or element). Never append a result-state or updated-state node.

VAGUE REQUIREMENTS:
If the text is too broad to construct a specific path (e.g. "users can manage their tasks"), set vague: true and use a minimal path with one node only. Step 3 will decompose it.

SCREENSHOT PAGES:
A markdown section heading (`###`) immediately followed by a screenshot image (`![...](...)`), with no other requirement text, documents that a page exists. Extract it as a vague function: "User can access [Page Name]" with `vague: true` and `source_quote` set to the heading text (e.g. "Welcome Page"). Extract one function per page heading. Do NOT extract the image line itself as the quote.

---

PATH EXAMPLES

"Users should be able to log in" — multi-hop, all primary:
path: [
  {"type": "node",    "label": "Login Page",         "primary": true},
  {"type": "element", "label": "login form",         "primary": true, "ui_node": "Login Page"},
  {"type": "edge",    "label": "submit credentials", "primary": true, "from": "Login Page", "to": "Dashboard"},
  {"type": "node",    "label": "Dashboard",          "primary": true}
]

"The add-task button opens a form to create a new task" — element + edge primary; page context (no trailing state-variant node):
path: [
  {"type": "node",    "label": "Task List Page", "primary": false},
  {"type": "element", "label": "add task form",  "primary": true, "ui_node": "Task List Page"},
  {"type": "edge",    "label": "submit new task", "primary": true, "from": "Task List Page", "to": "Task List Page"}
]

"Users can manage their tasks" — vague, minimal path:
path: [{"type": "node", "label": "Task Management Page", "primary": true}]
vague: true

---

RULES

1. source_quote: one verbatim sentence from the source. Must appear verbatim in the source text (whitespace differences OK).
2. One function per user goal. "Register and log in" = two functions.
3. No inference: path must be derivable from source_quote alone. If path requires invention, set vague: true.
4. Decompose compound items: "register and log in" = Register function + Login function.
5. priority: critical = foundational (1–2 max); high = core; medium = supporting; low = minor
6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
7. source: exact filename or "user_input"
8. functional_area: short snake_case (e.g. "auth", "task_management")

project_summary: Write 2–3 sentences before the requirements: what the app is, who uses it, what problem it solves. Domain and purpose — not a feature list.

Return ONLY a valid JSON object (no markdown fences, no explanation):
{
  "project_summary": "2-3 sentence description.",
  "requirements": [{
    "req_id": "REQ-001",
    "description": "User can log in",
    "path": [
      {"type": "node",    "label": "Login Page",         "primary": true},
      {"type": "element", "label": "login form",         "primary": true, "ui_node": "Login Page"},
      {"type": "edge",    "label": "submit credentials", "primary": true, "from": "Login Page", "to": "Dashboard"},
      {"type": "node",    "label": "Dashboard",          "primary": true}
    ],
    "vague": false,
    "source": "README.md",
    "source_quote": "users should be able to log in",
    "tag": "stated",
    "priority": "high",
    "weight": 3.0,
    "testable": true,
    "functional_area": "auth"
  }]
}"""


def _find_project_root(extract_to: Path) -> Path:
    root = extract_to
    while True:
        contents = [p for p in root.iterdir()]
        if len(contents) == 1 and contents[0].is_dir():
            root = contents[0]
        else:
            break
    return root


def _find_spec_docs(root: Path) -> tuple[dict[str, str], list[str], int]:
    readme_bucket: dict[str, str] = {}
    spec_bucket: dict[str, str] = {}
    truncated: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        depth = len(Path(dirpath).relative_to(root).parts)
        for filename in filenames:
            name_lower = filename.lower()
            ext = Path(filename).suffix.lower()
            is_readme = name_lower in README_NAMES
            if is_readme and depth > MAX_README_DEPTH:
                continue
            is_spec = (
                ext in SPEC_DOC_EXTENSIONS
                and name_lower != "requirements.txt"
                and name_lower not in README_NAMES
                and any(kw in name_lower for kw in SPEC_DOC_KEYWORDS)
            )
            if not is_readme and not is_spec:
                continue

            key = (Path(dirpath).relative_to(root) / filename).as_posix()
            if key in readme_bucket or key in spec_bucket:
                continue

            try:
                raw = (Path(dirpath) / filename).read_text(encoding="utf-8", errors="ignore")
                if len(raw) > MAX_CHARS_PER_DOC:
                    truncated.append(key)
                content = raw[:MAX_CHARS_PER_DOC]
                if is_readme:
                    readme_bucket[key] = content
                else:
                    spec_bucket[key] = content
            except OSError:
                pass

    merged: dict[str, str] = {}
    for k, v in readme_bucket.items():
        if len(merged) >= MAX_DOCS:
            break
        merged[k] = v
    for k, v in spec_bucket.items():
        if len(merged) >= MAX_DOCS:
            break
        merged[k] = v

    excluded_count = sum(1 for k in spec_bucket if k not in merged)
    return merged, truncated, excluded_count


def _build_user_message(requirements_text: str, spec_docs: dict[str, str]) -> str:
    parts = [f"=== USER REQUIREMENTS ===\n{requirements_text}"]
    for label, content in spec_docs.items():
        parts.append(f"=== {label} ===\n{content}")
    parts.append("Extract all explicitly stated functional requirements as functions with paths.")
    return "\n\n".join(parts)


def _parse_llm_response(raw: str) -> tuple[list, str]:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed.get("requirements", []), str(parsed.get("project_summary", ""))
        if isinstance(parsed, list):
            return parsed, ""
    except json.JSONDecodeError as e:
        bracket_pos = text.find("[")
        if bracket_pos >= 0:
            array_text = text[bracket_pos:]
            adj_pos = max(0, e.pos - bracket_pos)
            try:
                return json.loads(array_text), ""
            except json.JSONDecodeError:
                last_close = array_text.rfind("},", 0, adj_pos)
                if last_close == -1:
                    last_close = array_text.rfind("},")
                if last_close != -1:
                    return json.loads(array_text[:last_close + 1] + "]"), ""

    raise ValueError("Could not parse LLM response as requirements")


def _validate_and_normalise(
    items: list,
    requirements_text: str,
    spec_docs: dict[str, str],
) -> tuple[list, int]:
    all_sources_norm = _norm(requirements_text + " " + " ".join(spec_docs.values()))
    valid = []
    dropped = 0

    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue

        quote = str(item.get("source_quote", "")).strip()
        if not quote:
            dropped += 1
            continue

        if _norm(quote) not in all_sources_norm:
            dropped += 1
            continue

        path = _validate_path(item.get("path"))
        if path is None:
            dropped += 1
            continue
        item["path"] = path

        item["vague"] = bool(item.get("vague", False))

        priority = item.get("priority", "medium")
        if priority not in WEIGHT_MAP:
            priority = "medium"
        item["priority"] = priority
        item["weight"] = WEIGHT_MAP[priority]

        item.setdefault("tag", "stated")
        item.setdefault("testable", True)
        item.setdefault("source", "user_input")
        item.setdefault("functional_area", "general")

        valid.append(item)

    for i, item in enumerate(valid, start=1):
        item["req_id"] = f"REQ-{i:03d}"

    return valid, dropped


async def run(
    requirements_text: str,
    extract_to: Path,
    client: anthropic.AsyncAnthropic,
) -> dict:
    model = "claude-haiku-4-5-20251001"
    spec_docs: dict[str, str] = {}
    truncated_docs: list[str] = []
    excluded_docs_count: int = 0

    try:
        root = _find_project_root(extract_to)
        spec_docs, truncated_docs, excluded_docs_count = _find_spec_docs(root)
    except Exception:
        pass

    last_exc = None
    project_summary = ""
    requirements = []
    dropped = 0
    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=8000,
                system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _build_user_message(requirements_text, spec_docs)}],
            )
            raw_items, project_summary = _parse_llm_response(response.content[0].text)
            requirements, dropped = _validate_and_normalise(raw_items, requirements_text, spec_docs)
            break
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code == 529 and attempt < 2:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            return {
                "requirements": [], "total_count": 0,
                "docs_used": list(spec_docs.keys()), "truncated_docs": truncated_docs,
                "excluded_docs_count": excluded_docs_count, "llm_model": model,
                "dropped_count": 0, "project_summary": "", "error": str(exc),
            }
        except Exception as exc:
            return {
                "requirements": [], "total_count": 0,
                "docs_used": list(spec_docs.keys()), "truncated_docs": truncated_docs,
                "excluded_docs_count": excluded_docs_count, "llm_model": model,
                "dropped_count": 0, "project_summary": "", "error": str(exc),
            }

    return {
        "requirements": requirements,
        "total_count": len(requirements),
        "docs_used": list(spec_docs.keys()),
        "truncated_docs": truncated_docs,
        "excluded_docs_count": excluded_docs_count,
        "llm_model": model,
        "dropped_count": dropped,
        "project_summary": project_summary,
    }
