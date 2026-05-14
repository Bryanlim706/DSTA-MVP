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


_HTML_FILE_RE = re.compile(r"\b\w+\.html\b", re.IGNORECASE)
_QUOTED_BUTTON_RE = re.compile(r"""[\"’][^\"’]{1,40}[\"’]\s*button""", re.IGNORECASE)
_UI_COMPONENT_RE = re.compile(
    r"\b(navigation\s*bar|navbar|category\s+page|home\s+page|each\s+category\s+page)\b",
    re.IGNORECASE,
)


def _quote_has_ui_element(quote: str) -> bool:
    """Return True if quote references an HTML file, quoted button, or named UI component."""
    if _HTML_FILE_RE.search(quote):
        return True
    if _QUOTED_BUTTON_RE.search(quote):
        return True
    if _UI_COMPONENT_RE.search(quote):
        return True
    # "the table" only valid as subject (near start of sentence), not as object
    if re.match(r"the\s+table\b", quote.strip(), re.IGNORECASE):
        return True
    # Javascript as valid subject for user-initiated actions
    if re.match(r"^Javascript\b", quote.strip(), re.IGNORECASE):
        return True
    return False


MAX_DOCS = 30
MAX_CHARS_PER_DOC = 12000
MAX_README_DEPTH = 2

LLM_SYSTEM_PROMPT = """You are a requirements analyst. Extract functional requirements from software documentation.

EXTRACTION RULE: Extract ONLY from sentences whose grammatical subject is one of:
1. An HTML filename — e.g. "login.html", "register.html", "add_row.html"
2. A quoted button or link name — e.g. "the 'logout' button", "the 'change password' button"
3. A named UI component — e.g. "the navigation bar", "the table", "the category page", "the home page"
4. "Javascript" — only when the sentence describes a user-initiated action (clicking, deleting, editing)

All other subjects are skipped — no exceptions.

---

EXAMPLES

EXTRACT:
- "login.html renders a login page, requiring the user to enter their username and password" → subject: login.html (HTML file) → login capability
- "The 'change password' button allows the user to change their passwords" → subject: 'change password' button → change password
- "add_categories.html renders a page which allows the user to add a category" → subject: add_categories.html → add category
- "Each category page has a back to homepage button, as well as a table with columns..." → subject: category page (UI component) → back navigation + table view
- "Javascript also allows for deletion of the elements(category) from the navigation bar" → subject: Javascript (user-initiated action) → delete category

SKIP (subject is a backend process, not a UI element):
- "Passwords are hashed before storing, for security." → subject: passwords (automatic backend process) → SKIP
- "The input is validated by app.py, which prevents duplicate category name entries." → subject: app.py → SKIP
- "Rows with status marked as done sink to the bottom of the table." → subject: rows (automatic sorting behavior) → SKIP
- "Username and password is proofread against the sqlite3 database in app.py." → subject: database → SKIP
- "app.py passes this name data to layout.html, enabling the rendering" → subject: app.py → SKIP
- "If valid, username and password is stored in sqlite3 database through app.py." → subject: app.py process → SKIP

---

QUOTE RULE: source_quote must be ONE sentence only. Never combine multiple sentences.

---

DEDUPLICATION

If a button and the page it opens describe the same user action (e.g. "plus button opens add_row.html"), extract ONE requirement.

---

SELF-CHECK

Before outputting, for each item ask: "What is the FIRST noun phrase (grammatical subject) of source_quote?"
- If it is an HTML filename, button name, UI component, or Javascript → keep
- If it is app.py, a database, an algorithm, a passive process, or a data field → remove that item

---

RULES

1. Extract only from sentences matching subjects in the EXTRACTION RULE above.
2. source_quote = one verbatim sentence containing the named UI element.
3. One requirement per named UI entry point.
4. No inference — description must be derivable from the source_quote alone.
5. Priority: critical = foundational (max 1-2); high = core; medium = supporting; low = minor.
6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0
7. source: exact filename (e.g. "README.md") or "user_input".
8. functional_area: short snake_case.

Return ONLY a valid JSON array. No markdown fences, no explanation, no other text:
[{
  "req_id": "REQ-001",
  "description": "System must [allow users to / display]...",
  "source": "README.md",
  "source_quote": "single verbatim sentence containing the named UI element",
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

        if not _quote_has_ui_element(quote):
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
