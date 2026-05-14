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

Each requirement you extract represents something a user can do or experience in the application's interface. It will later be located in the codebase and automatically tested. Only extract items a user can directly interact with or navigate to.

---

CORE DISTINCTION: capabilities vs reactions

A CAPABILITY is something a user can directly navigate to, interact with, or observe. It has a dedicated place in the interface — its own page, form, button, or view.

A REACTION is what the system does when or if something else happens. Reactions are not requirements — they describe how existing capabilities behave under specific conditions, and will be captured as test assertions later.

THE SIGNAL: If you find yourself writing "System must [do X] when [condition]" or "System must [do X] if [condition]" — that is a reaction. Skip it.

---

PRIMARY TEST

Before deciding whether to extract an item, ask: Does this have a dedicated place in the interface — its own page, form, button, or view that a user navigates to?

If yes — it may be a capability. Continue to the signal check.
If no — skip it. This applies even when the behavior is explicitly documented. Technical behaviors stated in a README (password hashing, duplicate prevention, automatic sorting) are Y-axis correctness properties — they fail the UI gate regardless of how clearly they appear in the source.

Things that always fail this test:
- Automatic behaviors: rows sort by status automatically, users are redirected on auth failure
- Background processes: passwords are hashed before storing, sessions are cleared on logout
- Validation rules: duplicate entries are blocked, uniqueness is enforced on submission
- UI trigger details: "the plus button opens the add-row form" — the button is part of the add-row capability, not a capability on its own

---

EXAMPLES

Extract these (capabilities — each is a dedicated, user-facing feature):
- "User can log in" — the login page is a dedicated screen the user navigates to
- "User can log out" — the logout button is a dedicated action the user takes
- "User can register an account" — the registration form is its own page
- "User can view their task list" — the task list is its own dedicated view
- "User can add a task" — the add task form is its own dedicated screen
- "User can navigate back to home from the category page" — the back button is a dedicated UI element

Skip these (reactions — they describe what happens when something else occurs):
- "System redirects to login when session expires" — reaction to a condition
- "Session is cleared when user logs out" — side effect of the logout action
- "Error is shown when username is already taken" — reaction to a validation failure
- "Page is inaccessible when user is not authenticated" — reaction to auth state
- "Task list shows a message when no tasks exist" — reaction to an empty state
- "Passwords are hashed before storing" — background process, no dedicated UI entry point
- "Duplicate entries are prevented on form submission" — validation rule, no dedicated UI
- "Tasks with done status sink to the bottom of the table" — automatic reordering, no UI
- "The plus button opens the add-row form" — sub-affordance of the add-row capability, subsumed

---

RULES

1. Quote fidelity. source_quote must directly support the requirement. A quote about storing passwords does not evidence a uniqueness rule. A quote about database storage does not evidence a duplicate-prevention rule.

2. No artificial splits. If one sentence describes two sides of the same capability ("done tasks sink to the bottom; active tasks rise to the top"), extract ONE requirement. Only split when each part requires a completely separate test.

3. Decompose compound capabilities. "Users can register and log in" = two separate capabilities → two requirements, each with the same source quote.

4. No inference. Extract only what is explicitly stated AS A USER-FACING CAPABILITY — something with a dedicated page, form, button, or view. Not every sentence in the documentation is a requirement. Explicitly documented technical behaviors (password hashing, duplicate prevention, automatic sorting) are Y-axis properties — do not extract them.

5. Priority:
   - critical: A foundational capability that many other features depend on. Without it the app does not work for any user. Use for at most 1-2 requirements per app.
   - high: Core stated feature. Use for most requirements.
   - medium: Supporting feature mentioned without emphasis.
   - low: Minor or optional feature.

6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0

7. source: The exact section label from the input — "user_input" for the USER REQUIREMENTS section, or the exact filename (e.g. "README.md"). If the same capability appears in both, extract it once and use "user_input".

8. functional_area: A short snake_case label for the feature group this requirement belongs to (e.g. "auth", "task_management", "category_management"). Requirements that share the same page or backend model should share the same label. Use "general" only if the requirement spans the whole application.

9. testable: Set false only if the item is so vague it cannot be expressed as pass/fail. Capabilities are almost always testable.

---

Return ONLY a valid JSON array. No markdown fences, no explanation, no other text:
[{
  "req_id": "REQ-001",
  "description": "System must [verb] [object]",
  "source": "user_input",
  "source_quote": "verbatim excerpt copied exactly from the source text",
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
