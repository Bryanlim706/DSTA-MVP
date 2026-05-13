import json
import os
from pathlib import Path

import anthropic

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "venv", ".venv",
    "__pycache__", "coverage", ".cache", "out", "target", "vendor",
}

WEIGHT_MAP = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}

SPEC_DOC_EXTENSIONS = {".md", ".rst", ".txt"}
SPEC_DOC_KEYWORDS = {
    "requirement", "spec", "specification",
    "stories", "acceptance", "feature", "backlog",
    "use-case", "usecase", "epic", "functional",
}
README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}
MAX_DOCS = 10
MAX_CHARS_PER_DOC = 12000

LLM_SYSTEM_PROMPT = """You are a requirement extraction assistant. Extract ONLY functional requirements that are explicitly stated in the provided text.

Rules:
1. No inference, no invention — every item must trace back to an exact verbatim quote from the source text.
2. Decompose compound statements (e.g. "users can register and log in") into separate atomic items — each independently testable.
3. Each item must describe a single functional behaviour the system must support.
4. Assign priority based on urgency/importance signals in the text: critical / high / medium / low. Default to "medium" if no signal exists.
5. weight derives from priority: critical=4.0  high=3.0  medium=2.0  low=1.0
6. testable: set false only if the item cannot be expressed as a pass/fail behaviour (e.g. vague quality statements). Functional behaviours are almost always true.
7. source: use the exact section label from the input — "user_input" for the USER REQUIREMENTS section, or the exact label shown (e.g. "README.md", "docs/REQUIREMENTS.md") for any other section.
8. If the same requirement appears in multiple sections (same meaning, even if worded differently), extract it once only — prefer "user_input" as the source.
9. functional_area: assign a short snake_case label for the root feature this requirement belongs to (e.g. "auth", "cart", "product_listing", "checkout", "notifications"). Requirements that share a root component should share the same label. Use "general" if it spans the whole app.

Return ONLY a valid JSON array — no markdown fences, no explanation, just raw JSON:
[{
  "req_id": "REQ-001",
  "description": "Short imperative sentence: what the system must do",
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


def _find_spec_docs(root: Path) -> tuple[dict[str, str], list[str]]:
    """
    Returns (docs, truncated_docs).
    docs: {relative_posix_path: content} — README always first, then spec docs.
    truncated_docs: relative paths of files that exceeded MAX_CHARS_PER_DOC.
    README is guaranteed to be included before any spec doc when the MAX_DOCS cap is hit.
    Uses relative paths as keys so same-named files in different dirs never collide.
    """
    readme_bucket: dict[str, str] = {}
    spec_bucket: dict[str, str] = {}
    truncated: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            name_lower = filename.lower()
            ext = Path(filename).suffix.lower()
            is_readme = name_lower in README_NAMES
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

    return merged, truncated


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
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-array JSON")
    return parsed


def _validate_and_normalise(
    items: list,
    requirements_text: str,
    spec_docs: dict[str, str],
) -> tuple[list, int]:
    all_sources_lower = requirements_text.lower() + " " + " ".join(spec_docs.values()).lower()
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

        if quote.lower() not in all_sources_lower:
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

    try:
        root = _find_project_root(extract_to)
        spec_docs, truncated_docs = _find_spec_docs(root)
    except Exception:
        pass

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=8192,
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
            "llm_model": model,
            "dropped_count": 0,
            "error": str(exc),
        }

    return {
        "requirements": requirements,
        "total_count": len(requirements),
        "docs_used": list(spec_docs.keys()),
        "truncated_docs": truncated_docs,
        "llm_model": model,
        "dropped_count": dropped,
    }
