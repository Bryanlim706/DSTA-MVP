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

LLM_SYSTEM_PROMPT = """You are a requirements analyst extracting stated functional requirements for an ISO 25010 Functional Suitability evaluation. Each requirement you extract will be mapped to a specific UI screen or API endpoint in a later pipeline step, then tested automatically. Extract only what will survive that mapping.

## The core test
Before extracting any item, ask: "Can I point to a specific page, form, or API endpoint that implements this?" If yes, extract it. If no, skip it — it is a behavioral property of another function and will be captured as an acceptance criterion later.

## Exclusion criteria — do NOT extract these

| Pattern | Example | Why excluded |
|---|---|---|
| Error/validation behavior | "shows error if username taken", "renders apology page" | Behavioral property → AC on the registration/login function |
| Data persistence | "passwords stored in database" | Behavioral property → AC on the relevant data function |
| Navigation affordances described as implementation details | "back to homepage button on category page", "plus button opens form" | Implementation detail of existing navigation → AC on that function |
| Access/security constraints | "only authenticated users can access pages" | Constraint on existing functions → AC on those functions |

## Rules

1. **Quote fidelity.** The source_quote must directly evidence the requirement — not just be topically adjacent. A quote about storage is not evidence for a duplicate-prevention requirement.

2. **No artificial splits.** If a sentence describes two sides of the same behavior (e.g. "done tasks sink to bottom; active tasks rise to top"), extract it as ONE requirement — same function, one item.

3. **Decompose compound functions.** "Users can register and log in" = two distinct capabilities → two requirements. Split only when capabilities are independently testable with separate test cases.

4. **No inference, no invention.** Only extract what is explicitly stated. Obvious unstated requirements are handled in a separate step.

5. **Priority calibration:**
   - critical: App is completely non-functional without this, OR this requirement is a root that many other requirements depend on. Use sparingly — 1–2 per app maximum.
   - high: Core feature, explicitly stated or emphasized. Default for most functional requirements.
   - medium: Supporting feature, mentioned without emphasis.
   - low: Minor or optional feature.

6. weight = critical 4.0 | high 3.0 | medium 2.0 | low 1.0

7. **source:** use the exact section label from the input — "user_input" for the USER REQUIREMENTS section, or the exact filename label (e.g. "README.md"). If the same requirement appears in both, extract it once and prefer "user_input".

8. **functional_area:** snake_case label for the root feature (e.g. "auth", "task_management", "category_management"). Requirements sharing the same UI component or backend model share the same label. Use "general" only if the requirement spans the whole app.

9. **testable:** false only for vague quality statements that cannot be expressed as pass/fail. Functional requirements are almost always true.

Return ONLY a valid JSON array — no markdown fences, no explanation, just raw JSON:
[{
  "req_id": "REQ-001",
  "description": "System must [verb] [object] — short imperative sentence",
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
