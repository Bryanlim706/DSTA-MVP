import asyncio
import json
import os
import re
from pathlib import Path

import anthropic

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

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Extract stated requirements as graph entities — nodes, edges, or elements within nodes. Requirements are X-axis items (what exists in the UI). Behavioral properties (how well something works) are Y-axis items and must NOT be extracted.

---

TAXONOMY

node — A distinct page or screen a user can navigate to.
  description: "System must provide a [Page Name]"
  ui_node: the page name itself

element — A UI control, button, form, or feature that lives within a specific page.
  description: "System must provide [element] on the [Page Name]"
  ui_node: the containing page name

edge — An explicitly stated navigation path between two pages.
  description: "System must provide a way to navigate from [Source] to [Destination]"
  ui_node: the destination page name

---

WHAT TO EXTRACT

Extract when the source text names a specific page, screen, form, button, or UI component and describes what it IS or what it provides. Every item must classify as node, edge, or element.

Named entities include (not exhaustive): any named page or screen ("the login screen", "the dashboard"), any named form ("the add-task form"), any named button or link ("the logout button"), any named component ("the navigation bar", "the task table").

Named entities do NOT require .html filenames — "the contacts page shows..." is extractable even if no .html file is named.

---

EXTRACTION GATE — before adding any item, ask: does the source text name a specific UI entity (page, screen, form, button, component) and describe what it IS or provides? If not, skip it.

This gate rejects: automatic behaviors (hashing, redirecting, validating, sorting), backend subjects (app.py, server.py, database), reactions ("System must X when/if Y"), behavioral properties of existing entities (how something works, not what it is), and quality attributes (responsive, accessible, performant, secure) — none of these name a UI entity.

---

BEHAVIOURAL DECOMPOSITION RULE

If the source describes an automatic behaviour that only makes sense because the user can change a value, extract the element that enables it:

- "Rows with done status sink to the bottom" → element: status-change control on [task list page]
- "Tasks are ordered by priority" → element: priority-setting control on [task page]
- "Entries are grouped by due date" → element: due-date control on [entries page]

The automatic behaviour sentence IS the source_quote.

---

EXAMPLES

EXTRACT:
- "The login page requires username and password" → node: Login Page
- "The dashboard displays the user's recent activity" → node: Dashboard
- "The contacts view shows name, phone, and email for each contact" → node: Contacts View
- "The 'add task' button opens a form to create a new task" → element: add-task button/form on [task list page]
- "The navigation bar shows all user categories" → element: navigation bar on [home page]
- "Each category page has a back-to-home button" → edge: navigate from Category Page to Home
- "The settings screen allows users to change their password" → element: change-password control on Settings Page
- "Rows with done status sink to the bottom" → DECOMPOSE → element: status-change control on [task list page]
- "Javascript allows deletion of categories from the navigation bar" → element: delete-category control on [nav bar / home page]

SKIP:
- "Passwords are hashed before storing" → automatic process
- "Duplicate entries are prevented on form submission" → validation rule
- "app.py validates the input" → backend subject
- "The database stores user credentials" → data store
- "Users are redirected to login when unauthenticated" → reaction
- "Responsive design" → non-functional quality attribute (not a graph entity)
- "The app must be accessible on mobile and desktop" → non-functional quality attribute

---

DEDUPLICATION

If two sentences describe the same entity, extract ONE requirement.

---

PROJECT SUMMARY

Before extracting requirements, write a project_summary: 2–3 sentences covering what the app is, who uses it, and what problem it solves. Capture domain and purpose — not a feature list. Draw from the documentation only, no inference.

---

RULES

1. source_quote: ONE verbatim sentence from the source naming the UI entity or describing the automatic behaviour (Decomposition Rule).
2. No inference — description must be derivable from source_quote alone.
3. Decompose compound items: "register and log in" = two requirements (Registration Page node + Login Page node).
4. No artificial splits: two sides of the same entity = one requirement.
5. Priority: critical = foundational node with many dependents (max 1–2); high = core; medium = supporting; low = minor.
6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
7. source: exact filename (e.g. "README.md") or "user_input".
8. functional_area: short snake_case (e.g. "auth", "task_management").
9. type: "node" | "edge" | "element"
10. ui_node: for node — the page name itself; for element — the containing page; for edge — the destination page.

Return ONLY a valid JSON object. No markdown fences, no explanation, no other text:
{
  "project_summary": "2-3 sentence description of what the app is, who uses it, and what problem it solves.",
  "requirements": [{
    "req_id": "REQ-001",
    "description": "System must provide a Login Page",
    "type": "node",
    "ui_node": "Login Page",
    "source": "README.md",
    "source_quote": "verbatim sentence naming the UI entity",
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
    """
    Returns (docs, truncated_docs, excluded_count).
    docs: {relative_posix_path: content} — README always first, then spec docs.
    truncated_docs: relative paths of files that exceeded MAX_CHARS_PER_DOC.
    excluded_count: spec docs found but dropped because MAX_DOCS was hit.
    README files deeper than MAX_README_DEPTH are skipped to avoid sub-module READMEs
    consuming all README slots.
    Uses relative paths as keys so same-named files in different dirs never collide.
    """
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

    # README always first; spec docs fill remaining slots up to MAX_DOCS
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
    parts.append("Extract all explicitly stated functional requirements.")
    return "\n\n".join(parts)


def _parse_llm_response(raw: str) -> tuple[list, str]:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Full parse — expect {"project_summary": "...", "requirements": [...]}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed.get("requirements", []), str(parsed.get("project_summary", ""))
        if isinstance(parsed, list):
            return parsed, ""
    except json.JSONDecodeError:
        pass

    # Truncation recovery: find the requirements array and recover partial results.
    # project_summary is lost in this path but requirements are preserved.
    bracket_pos = text.find("[")
    if bracket_pos >= 0:
        array_text = text[bracket_pos:]
        try:
            return json.loads(array_text), ""
        except json.JSONDecodeError:
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

        priority = item.get("priority", "medium")
        if priority not in WEIGHT_MAP:
            priority = "medium"
        item["priority"] = priority
        item["weight"] = WEIGHT_MAP[priority]

        item.setdefault("tag", "stated")
        item.setdefault("testable", True)
        item.setdefault("source", "user_input")
        item.setdefault("functional_area", "general")

        if item.get("type") not in {"node", "edge", "element"}:
            item["type"] = "node"
        item.setdefault("ui_node", "")

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
