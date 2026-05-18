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

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Extract functional requirements that are explicitly stated in the provided documentation.

WHAT TO EXTRACT: A requirement is a user-facing capability — something a user can navigate to, interact with, or observe in the interface. It must be grounded in a sentence that names a specific page, screen, form, button, or UI component.

WHAT TO SKIP: Technical and automatic behaviors — even when explicitly documented — are not requirements. They are correctness properties that will be captured as test assertions later.

---

EXTRACTION RULE

Extract a requirement when the sentence describes what a named page, screen, form, or UI component DOES for the user. The source_quote must contain a reference to that named entity.

Named entities include (not exhaustive):
- Any named page or screen: "the login screen", "the dashboard", "the settings page", "login.html", "the contacts view"
- Any named form: "the registration form", "the add-task form", "the checkout form"
- Any named button or link: "the logout button", "the save changes button", "the add category link"
- Any named UI component: "the navigation bar", "the sidebar", "the data table", "the task table"

NOTE: Named entities do NOT require .html filenames. "The contacts page shows..." is extractable even if no .html file is named.

SKIP sentences where the subject is:
- A backend file: app.py, server.py, index.js, routes.py
- A database or data store: "the database", "sqlite3", "Supabase"
- An automatic process or reaction: hashing, sorting, redirecting, validating, clearing
- A data field or passive noun: "passwords", "rows", "entries", "the input"

---

BEHAVIOURAL DECOMPOSITION RULE

If the source describes an automatic behaviour that only makes sense because the user can change a value, extract the user capability that enables that behaviour:

- "Rows with done status sink to the bottom of the table" → extract "System must allow users to change the status of an item"
- "Tasks are ordered by priority" → extract "System must allow users to set the priority of a task"
- "Entries are grouped by due date" → extract "System must allow users to set the due date of an entry"

The automatic behaviour sentence IS the source_quote (it exists verbatim in the source). Tag these as `stated`.

---

EXAMPLES

EXTRACT:
- "The login page requires username and password" → login capability
- "The dashboard displays the user's recent activity" → dashboard view
- "The contacts view shows name, phone, and email for each contact" → contacts list view
- "The 'add task' button opens a form to create a new task" → add task capability
- "The navigation bar shows all user categories" → nav bar view
- "Each category page has a back-to-home button and a task table" → back navigation + table view
- "The settings screen allows users to change their password" → change password capability
- "Rows with done status sink to the bottom of the table" → DECOMPOSE: user can change item status
- "Javascript allows deletion of categories from the navigation bar" → delete category

SKIP:
- "Passwords are hashed before storing" → automatic process, no UI element named
- "Duplicate entries are prevented on form submission" → validation rule, no UI element named
- "app.py validates the input and blocks duplicate names" → backend file as subject
- "The database stores user credentials" → data store as subject
- "Users are redirected to login when unauthenticated" → automatic reaction, no UI element named

---

DEDUPLICATION

If two sentences describe the same user action from different angles, extract ONE requirement.

---

RULES

1. source_quote must be ONE sentence copied verbatim from the source. It must name a specific UI element or describe an automatic behaviour that implies a user capability (per Behavioural Decomposition Rule).
2. No inference — description must be derivable from source_quote alone.
3. Decompose compound capabilities: "users can register and log in" = two requirements.
4. No artificial splits: two sides of the same behavior = one requirement.
5. Priority: critical = foundational root (max 1-2); high = core feature; medium = supporting; low = minor.
6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
7. source: exact filename (e.g. "README.md") or "user_input".
8. functional_area: short snake_case (e.g. "auth", "task_management").

Return ONLY a valid JSON array. No markdown fences, no explanation, no other text:
[{
  "req_id": "REQ-001",
  "description": "System must [verb] [object]",
  "source": "README.md",
  "source_quote": "verbatim sentence naming the UI element",
  "tag": "stated",
  "priority": "high",
  "weight": 3.0,
  "testable": true,
  "functional_area": "auth"
}]"""


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


def _parse_llm_response(raw: str) -> list:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # LLM output was truncated mid-item (hit max_tokens). Recover everything before
        # the last complete item so we return partial results instead of failing entirely.
        last_close = text.rfind("},")
        if last_close != -1:
            parsed = json.loads(text[:last_close + 1] + "]")
        else:
            raise
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-array JSON")
    return parsed


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

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_user_message(requirements_text, spec_docs)}],
        )
        raw_items = _parse_llm_response(response.content[0].text)
        requirements, dropped = _validate_and_normalise(raw_items, requirements_text, spec_docs)
    except Exception as exc:
        return {
            "requirements": [],
            "total_count": 0,
            "docs_used": list(spec_docs.keys()),
            "truncated_docs": truncated_docs,
            "excluded_docs_count": excluded_docs_count,
            "llm_model": model,
            "dropped_count": 0,
            "error": str(exc),
        }

    return {
        "requirements": requirements,
        "total_count": len(requirements),
        "docs_used": list(spec_docs.keys()),
        "truncated_docs": truncated_docs,
        "excluded_docs_count": excluded_docs_count,
        "llm_model": model,
        "dropped_count": dropped,
    }
