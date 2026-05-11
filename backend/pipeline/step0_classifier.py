import asyncio
import json
import os
from pathlib import Path

import anthropic

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "venv", ".venv",
    "__pycache__", "coverage", ".cache", ".turbo", "out", ".nuxt",
    ".output", "target", "vendor", "bin", "obj", ".svelte-kit",
}

CONFIG_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "angular.json",
    "next.config.js", "next.config.ts", "next.config.mjs",
    "vite.config.js", "vite.config.ts", "vite.config.mjs",
    "nuxt.config.js", "nuxt.config.ts",
    "svelte.config.js", "svelte.config.ts",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "README.md", "readme.md",
}

SYSTEM_PROMPT = """You are a software project classifier. Given a project file tree and key config file contents, classify the project.

Return ONLY a valid JSON object — no markdown fences, no explanation, just raw JSON.

Use exactly this structure:
{
  "project_type": "<full_stack_web_app | frontend_only | backend_api_only | cli_tool | library | static_site | monorepo | unknown>",
  "frontend_framework": "<React | Vue | Angular | Svelte | Next.js | Nuxt | SvelteKit | null>",
  "backend_framework": "<FastAPI | Flask | Django | Express | Fastify | Spring | Rails | null>",
  "primary_language": "<TypeScript | JavaScript | Python | Go | Rust | Java | Ruby | other>",
  "confidence": "<high | medium | low>",
  "reasoning": "<1-2 sentences: which specific signals led to this classification>",
  "test_strategy": {
    "primary": "<Playwright E2E | Pytest | Jest | Supertest | subprocess | none>",
    "secondary": "<same options or null>"
  }
}"""


def _scan_project(root: Path) -> dict:
    file_tree: list[str] = []
    config_contents: dict[str, str] = {}
    extension_counts: dict[str, int] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        rel_dir = Path(dirpath).relative_to(root)

        for filename in sorted(filenames):
            rel_path = str(rel_dir / filename)
            file_tree.append(rel_path)

            ext = Path(filename).suffix.lower()
            if ext:
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

            if filename in CONFIG_FILES:
                full_path = Path(dirpath) / filename
                try:
                    with open(full_path, encoding="utf-8", errors="ignore") as f:
                        config_contents[rel_path] = f.read(5000)
                except OSError:
                    pass

    return {
        "file_tree": file_tree[:600],
        "config_files": config_contents,
        "extension_counts": dict(
            sorted(extension_counts.items(), key=lambda x: -x[1])[:20]
        ),
        "total_files": len(file_tree),
    }


def _find_project_root(extract_to: Path) -> Path:
    """If zip extracts to a single top-level folder, use that as root."""
    contents = [p for p in extract_to.iterdir()]
    if len(contents) == 1 and contents[0].is_dir():
        return contents[0]
    return extract_to


def _build_user_message(scan: dict) -> str:
    tree_str = "\n".join(scan["file_tree"])
    ext_str = json.dumps(scan["extension_counts"], indent=2)

    config_parts = []
    for path, content in scan["config_files"].items():
        config_parts.append(f"--- {path} ---\n{content}")
    config_str = "\n\n".join(config_parts) if config_parts else "None found"

    return (
        f"File tree ({scan['total_files']} total files, showing up to 600):\n{tree_str}\n\n"
        f"Extension distribution:\n{ext_str}\n\n"
        f"Config file contents:\n{config_str}\n\n"
        "Classify this project."
    )


def _parse_llm_response(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(text)


async def run(extract_to: Path, client: anthropic.AsyncAnthropic) -> dict:
    root = _find_project_root(extract_to)
    scan = await asyncio.to_thread(_scan_project, root)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _build_user_message(scan)}],
    )

    try:
        result = _parse_llm_response(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        result = {
            "project_type": "unknown",
            "frontend_framework": None,
            "backend_framework": None,
            "primary_language": "unknown",
            "confidence": "low",
            "reasoning": "Could not parse classifier response.",
            "test_strategy": {"primary": "none", "secondary": None},
        }

    result["scan_summary"] = {
        "total_files": scan["total_files"],
        "extension_counts": scan["extension_counts"],
        "config_files_found": list(scan["config_files"].keys()),
    }
    return result
