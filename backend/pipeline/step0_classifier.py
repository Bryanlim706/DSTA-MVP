import asyncio
import configparser
import json
import os
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore

import anthropic

# --- Ignore dirs ---
IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "venv", ".venv",
    "__pycache__", "coverage", ".cache", ".turbo", "out", ".nuxt",
    ".output", "target", "vendor", "bin", "obj", ".svelte-kit",
}

CONFIG_FILES = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "composer.json", "angular.json",
    "next.config.js", "next.config.ts", "next.config.mjs",
    "vite.config.js", "vite.config.ts", "vite.config.mjs",
    "nuxt.config.js", "nuxt.config.ts",
    "svelte.config.js", "svelte.config.ts",
    "electron-builder.yml", "electron-builder.json",
    "electron.vite.config.js", "electron.vite.config.ts",
    "expo.json", "app.json", "pubspec.yaml",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "README.md", "readme.md",
}

# --- Framework registries ---
# Meta-frameworks listed before their base so _detect_frontend picks the more specific match first.
# e.g. Next.js projects have both "next" and "react" in deps — "next" must win.
FRONTEND_FRAMEWORKS: dict[str, str] = {
    "next": "Next.js",
    "@remix-run/react": "Remix",
    "gatsby": "Gatsby",
    "nuxt": "Nuxt",
    "@sveltejs/kit": "SvelteKit",
    "expo": "Expo",
    "react-native": "React Native",
    "react": "React",
    "vue": "Vue",
    "svelte": "Svelte",
    "@angular/core": "Angular",
    "astro": "Astro",
    "preact": "Preact",
    "solid-js": "SolidJS",
    "@builder.io/qwik": "Qwik",
    "htmx.org": "HTMX",
    "alpinejs": "Alpine.js",
    "ember-source": "Ember",
    "lit": "Lit",
}

BACKEND_FRAMEWORKS_JS: dict[str, str] = {
    "express": "Express",
    "@nestjs/core": "NestJS",
    "fastify": "Fastify",
    "koa": "Koa",
    "@hapi/hapi": "Hapi",
    "hapi": "Hapi",
}

BACKEND_FRAMEWORKS_PHP: dict[str, str] = {
    "laravel/framework": "Laravel",
    "symfony/symfony": "Symfony",
    "symfony/framework-bundle": "Symfony",
    "slim/slim": "Slim",
    "codeigniter4/framework": "CodeIgniter",
    "cakephp/cakephp": "CakePHP",
    "yiisoft/yii2": "Yii",
}

BACKEND_FRAMEWORKS_PY: dict[str, str] = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "litestar": "Litestar",
    "starlette": "Starlette",
    "aiohttp": "aiohttp",
    "tornado": "Tornado",
    "bottle": "Bottle",
    "sanic": "Sanic",
    "quart": "Quart",
}

# argparse is stdlib — it never appears in requirements files, so it cannot be detected here.
CLI_INDICATORS_PY: set[str] = {"click", "typer", "fire"}

TEST_STRATEGY_MAP: dict[str, dict] = {
    "full_stack_web_app": {"primary": "Playwright E2E", "secondary": "Pytest API tests"},
    "full_stack_js":      {"primary": "Playwright E2E", "secondary": "Jest/Supertest"},
    "frontend_only":      {"primary": "Playwright E2E", "secondary": None},
    "backend_api_only":   {"primary": "Pytest", "secondary": None},
    "cli_tool":           {"primary": "Pytest", "secondary": None},
    "library":            {"primary": "Pytest", "secondary": None},
    "electron_app":       {"primary": "Playwright E2E", "secondary": "Vitest"},
    "mobile_app":         {"primary": "Jest", "secondary": None},
    "static_site":        {"primary": "Playwright E2E", "secondary": None},
    "monorepo":           {"primary": "Playwright E2E", "secondary": None},
    "unknown":            {"primary": "none", "secondary": None},
}

# Secondary test tool keyed by backend framework — overrides the static map secondary
_BACKEND_TEST_SECONDARY: dict[str, str] = {
    "FastAPI": "Pytest API tests",
    "Flask": "Pytest API tests",
    "Django": "Pytest API tests",
    "Litestar": "Pytest API tests",
    "Starlette": "Pytest API tests",
    "aiohttp": "Pytest API tests",
    "Tornado": "Pytest API tests",
    "Bottle": "Pytest API tests",
    "Sanic": "Pytest API tests",
    "Quart": "Pytest API tests",
    "Express": "Jest/Supertest",
    "NestJS": "Jest/Supertest",
    "Fastify": "Jest/Supertest",
    "Koa": "Jest/Supertest",
    "Hapi": "Jest/Supertest",
    "Laravel": "PHPUnit",
    "Symfony": "PHPUnit",
    "Slim": "PHPUnit",
    "CodeIgniter": "PHPUnit",
    "CakePHP": "PHPUnit",
    "Yii": "PHPUnit",
    "Spring Boot": "JUnit",
    "Rails": "RSpec",
    "ASP.NET": "xUnit",
}

_BACKEND_TEST_PRIMARY: dict[str, str] = {
    "Express":      "Jest",
    "NestJS":       "Jest",
    "Fastify":      "Jest",
    "Koa":          "Jest",
    "Hapi":         "Jest",
    "Laravel":      "PHPUnit",
    "Symfony":      "PHPUnit",
    "Slim":         "PHPUnit",
    "CodeIgniter":  "PHPUnit",
    "CakePHP":      "PHPUnit",
    "Yii":          "PHPUnit",
    "Spring Boot":  "JUnit",
    "Rails":        "RSpec",
    "ASP.NET":      "xUnit",
}


def _get_test_strategy(project_type: str, backend_framework: str | None) -> dict:
    strategy = dict(TEST_STRATEGY_MAP.get(project_type, TEST_STRATEGY_MAP["unknown"]))
    if backend_framework:
        if backend_framework in _BACKEND_TEST_SECONDARY:
            strategy["secondary"] = _BACKEND_TEST_SECONDARY[backend_framework]
        if project_type == "backend_api_only" and backend_framework in _BACKEND_TEST_PRIMARY:
            strategy["primary"] = _BACKEND_TEST_PRIMARY[backend_framework]
    if strategy.get("secondary") == strategy.get("primary"):
        strategy["secondary"] = None
    return strategy

# --- LLM fallback prompt ---

LLM_SYSTEM_PROMPT = """You are a software project classifier. Given a project file tree and key config file contents, classify the project.

Return ONLY a valid JSON object — no markdown fences, no explanation, just raw JSON.

Use exactly this structure:
{
  "project_type": "<full_stack_web_app | full_stack_js | frontend_only | backend_api_only | cli_tool | library | static_site | monorepo | electron_app | mobile_app | unknown>",
  "frontend_framework": "<React | Vue | Angular | Svelte | Next.js | Nuxt | SvelteKit | Remix | Gatsby | Astro | Preact | SolidJS | Qwik | HTMX | Alpine.js | Ember | Lit | React Native | Expo | null>",
  "backend_framework": "<FastAPI | Flask | Django | Litestar | Starlette | aiohttp | Tornado | Express | NestJS | Fastify | Koa | Hapi | Spring Boot | Laravel | Rails | Phoenix | ASP.NET | Gin | Fiber | Echo | Actix | Electron | null>",
  "confidence": "<high | medium | low>",
  "reasoning": "<1-2 sentences: which specific signals led to this classification>"
}

Rules:
- electron_app: electron in dependencies or main/preload/renderer process structure. Set backend_framework to "Electron".
- mobile_app: React Native, Expo, or Flutter project.
- full_stack_web_app: frontend framework + Python/Go/Java/Ruby backend.
- full_stack_js: frontend framework + Node.js backend framework."""


# --- Helpers ---

def _parse_pkg_name(raw: str) -> str:
    return re.split(r'[<>=~!@\[\s;]', raw.strip())[0].lower().strip()


def _collect_python_packages(root: Path) -> set[str]:
    packages: set[str] = set()

    for req_file in root.rglob("requirements*.txt"):
        if any(part in IGNORE_DIRS for part in req_file.parts):
            continue
        try:
            for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                pkg = _parse_pkg_name(line)
                if pkg:
                    packages.add(pkg)
        except Exception:
            pass

    if tomllib:
        for pyproject in root.rglob("pyproject.toml"):
            if any(part in IGNORE_DIRS for part in pyproject.parts):
                continue
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="ignore"))
                for dep in data.get("project", {}).get("dependencies", []):
                    pkg = _parse_pkg_name(dep)
                    if pkg:
                        packages.add(pkg)
                for pkg_name in data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys():
                    if pkg_name.lower() != "python":
                        packages.add(pkg_name.lower())
            except Exception:
                pass

        for pipfile in root.rglob("Pipfile"):
            if any(part in IGNORE_DIRS for part in pipfile.parts):
                continue
            try:
                data = tomllib.loads(pipfile.read_text(encoding="utf-8", errors="ignore"))
                for pkg_name in {**data.get("packages", {}), **data.get("dev-packages", {})}.keys():
                    if pkg_name.lower() != "python":
                        packages.add(pkg_name.lower())
            except Exception:
                pass

    for setup_cfg in root.rglob("setup.cfg"):
        if any(part in IGNORE_DIRS for part in setup_cfg.parts):
            continue
        try:
            cfg = configparser.ConfigParser()
            cfg.read_string(setup_cfg.read_text(encoding="utf-8", errors="ignore"))
            raw = cfg.get("options", "install_requires", fallback="")
            for line in raw.splitlines():
                pkg = _parse_pkg_name(line)
                if pkg:
                    packages.add(pkg)
        except Exception:
            pass

    return packages


def _detect_frontend(deps: dict[str, str]) -> str | None:
    for key, name in FRONTEND_FRAMEWORKS.items():
        if key.lower() in deps:
            return name
    return None


def _detect_backend_js(deps: dict[str, str]) -> str | None:
    for key, name in BACKEND_FRAMEWORKS_JS.items():
        if key.lower() in deps:
            return name
    return None


def _detect_backend_py(packages: set[str]) -> str | None:
    for key, name in BACKEND_FRAMEWORKS_PY.items():
        if key in packages:
            return name
    return None


def _detect_language(ext_counts: dict[str, int], frontend_fw: str | None, backend_fw: str | None) -> str:
    if any(ext in ext_counts for ext in {".ts", ".tsx"}):
        return "TypeScript"
    if backend_fw in {"FastAPI", "Flask", "Django", "Litestar", "Starlette", "aiohttp", "Tornado", "Bottle", "Sanic", "Quart"}:
        return "Python"
    # Rank by file count so the dominant language wins (e.g. 147 PHP files beat 19 Java files)
    candidates = [
        (".py", "Python"), (".go", "Go"), (".rs", "Rust"), (".java", "Java"),
        (".cs", "C#"), (".rb", "Ruby"), (".php", "PHP"), (".dart", "Dart"),
    ]
    best = max(candidates, key=lambda x: ext_counts.get(x[0], 0))
    if ext_counts.get(best[0], 0) > 0:
        return best[1]
    return "JavaScript"


# --- File scanner ---

def _scan_project(root: Path) -> dict:
    file_tree: list[str] = []
    config_contents: dict[str, str] = {}
    extension_counts: dict[str, int] = {}
    js_deps_merged: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        rel_dir = Path(dirpath).relative_to(root)

        for filename in sorted(filenames):
            rel_path = (rel_dir / filename).as_posix()
            file_tree.append(rel_path)

            ext = Path(filename).suffix.lower()
            if ext:
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

            full_path = Path(dirpath) / filename

            if filename == "package.json":
                try:
                    data = json.loads(full_path.read_text(encoding="utf-8", errors="ignore"))
                    js_deps_merged.update(data.get("dependencies", {}))
                    js_deps_merged.update(data.get("devDependencies", {}))
                except Exception:
                    pass

            if filename in CONFIG_FILES:
                try:
                    with open(full_path, encoding="utf-8", errors="ignore") as f:
                        config_contents[rel_path] = f.read(5000)
                except OSError:
                    pass

    return {
        "file_tree": file_tree[:600],
        "config_files": config_contents,
        "extension_counts": dict(sorted(extension_counts.items(), key=lambda x: -x[1])[:20]),
        "total_files": len(file_tree),
        "js_deps": {k.lower(): v for k, v in js_deps_merged.items()},
    }


def _find_project_root(extract_to: Path) -> Path:
    """Unwrap single-directory zip wrappers at any depth (e.g. myproject/myproject/src)."""
    root = extract_to
    while True:
        contents = [p for p in root.iterdir()]
        if len(contents) == 1 and contents[0].is_dir():
            root = contents[0]
        else:
            break
    return root


def _apply_test_strategy_overrides(result: dict, js_deps: dict) -> None:
    """Override the static test_strategy secondary based on actual test deps in the project."""
    project_type = result.get("project_type", "unknown")
    if project_type not in ("frontend_only", "electron_app"):
        return
    if not isinstance(result.get("test_strategy"), dict):
        return

    has_vitest = "vitest" in js_deps
    has_jest = "jest" in js_deps or "react-scripts" in js_deps
    has_rtl = "@testing-library/react" in js_deps or "react-scripts" in js_deps

    if has_vitest:
        result["test_strategy"]["secondary"] = "Vitest"
    elif has_jest and has_rtl:
        result["test_strategy"]["secondary"] = "Jest + React Testing Library"
    elif has_jest:
        result["test_strategy"]["secondary"] = "Jest"
    elif project_type == "electron_app":
        result["test_strategy"]["secondary"] = None


# --- Rule-based classifier ---

def _classify_by_rules(root: Path, scan: dict) -> dict | None:
    """Returns a result dict if rules are confident, None to trigger LLM fallback."""
    ext_counts = scan["extension_counts"]
    js_deps = scan["js_deps"]

    has_package_json = bool(js_deps) or any(
        not any(part in IGNORE_DIRS for part in p.parts)
        for p in root.rglob("package.json")
    )

    is_electron = "electron" in js_deps
    frontend_fw = _detect_frontend(js_deps)
    backend_fw_js = _detect_backend_js(js_deps)

    py_config_files = [
        p for pattern in ("requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile")
        for p in root.rglob(pattern)
        if not any(part in IGNORE_DIRS for part in p.parts)
    ]
    has_python = bool(py_config_files)
    py_packages: set[str] = set()
    backend_fw_py: str | None = None
    is_cli = False

    if has_python:
        py_packages = _collect_python_packages(root)
        backend_fw_py = _detect_backend_py(py_packages)
        is_cli = any(cli in py_packages for cli in CLI_INDICATORS_PY)
        if backend_fw_py:
            is_cli = False

    # Trust Python backend only if a config file exists at root or immediate subdirectory
    # (depth 0 or 1, e.g. "requirements.txt" or "backend/requirements.txt").
    # If Python configs live only in sub-service dirs (depth 2+), they belong to separate
    # services — zero them out so the JS-only rules apply and LLM fallback fires.
    root_level_py = any(
        len(p.relative_to(root).parts) <= 1
        for p in py_config_files
    )
    if has_python and not root_level_py:
        has_python = False
        backend_fw_py = None
        is_cli = False

    # Use scan config index — catches these files anywhere in the tree, not just root
    config_paths = set(scan["config_files"].keys())
    has_go = any("go.mod" in p for p in config_paths)
    has_rust = any("Cargo.toml" in p for p in config_paths)
    has_java = any("pom.xml" in p or "build.gradle" in p for p in config_paths)

    # PHP: check composer.json for known framework deps
    php_fw: str | None = None
    has_php = bool(ext_counts.get(".php", 0))
    for p in config_paths:
        if "composer.json" in p:
            try:
                full = root / p
                data = json.loads(full.read_text(encoding="utf-8", errors="ignore"))
                all_php_deps = {**data.get("require", {}), **data.get("require-dev", {})}
                for pkg, name in BACKEND_FRAMEWORKS_PHP.items():
                    if pkg in all_php_deps:
                        php_fw = name
                        break
            except Exception:
                pass
    # If .php files exist but no framework found in composer.json, leave php_fw as None —
    # PHP is a language, not a framework.

    java_fw: str | None = None
    if has_java:
        for p, content in scan["config_files"].items():
            if "pom.xml" in p or "build.gradle" in p:
                cl = content.lower()
                if "spring-boot" in cl:
                    java_fw = "Spring Boot"
                elif "quarkus" in cl:
                    java_fw = "Quarkus"
                elif "micronaut" in cl:
                    java_fw = "Micronaut"
                if java_fw:
                    break

    # Unknown language project (Go/Rust/Java only, no JS/Python) — defer to LLM
    if not has_package_json and not has_python and (has_go or has_rust or has_java):
        return None

    # --- Classification ---
    if is_electron:
        project_type = "electron_app"
        backend_framework = "Electron"
        confidence = "high"
        reasoning = f"Found 'electron' in package.json dependencies with {'React' if frontend_fw else 'renderer'} process structure."

    elif php_fw and not has_java:
        # Laravel/Symfony etc. commonly use npm/Vite for frontend assets — not a monorepo
        project_type = "full_stack_web_app" if has_package_json else "backend_api_only"
        backend_framework = php_fw
        confidence = "high"
        reasoning = (
            f"Found {php_fw} in composer.json"
            + (" with package.json for frontend assets." if has_package_json else ".")
        )

    elif has_package_json and (has_java or has_php or has_go or has_rust):
        # JS coexisting with a non-JS backend language signals a monorepo (e.g. server + mobile app)
        project_type = "monorepo"
        backend_framework = php_fw or backend_fw_py or backend_fw_js or java_fw
        other_langs = ", ".join(l for l, flag in [("Java", has_java), ("PHP", has_php), ("Go", has_go), ("Rust", has_rust)] if flag)
        confidence = "medium"
        if backend_framework:
            reasoning = f"Found package.json alongside {other_langs} project files. Likely a monorepo. Frontend: {frontend_fw or 'unknown'}, Backend: {backend_framework}."
        else:
            reasoning = f"Found package.json alongside {other_langs} project files with no recognised backend framework. Likely a monorepo."

    elif has_package_json and has_python and (backend_fw_py or backend_fw_js):
        project_type = "full_stack_web_app"
        backend_framework = backend_fw_py or backend_fw_js
        confidence = "high"
        reasoning = f"Found package.json and Python config files. Frontend: {frontend_fw or 'unknown'}, Backend: {backend_framework}."

    elif has_package_json and frontend_fw and backend_fw_js:
        project_type = "full_stack_js"
        backend_framework = backend_fw_js
        confidence = "high"
        reasoning = f"Found {frontend_fw} and {backend_fw_js} in package.json dependencies."

    elif has_package_json and frontend_fw:
        project_type = "frontend_only"
        backend_framework = None
        confidence = "high"
        reasoning = f"Found {frontend_fw} in package.json with no backend framework detected."

    elif has_package_json and backend_fw_js:
        project_type = "backend_api_only"
        backend_framework = backend_fw_js
        confidence = "high"
        reasoning = f"Found {backend_fw_js} in package.json with no frontend framework."

    elif has_package_json:
        project_type = "library"
        backend_framework = None
        confidence = "medium"
        reasoning = "Found package.json but no known framework — assumed Node library."

    elif has_python and backend_fw_py:
        project_type = "backend_api_only"
        backend_framework = backend_fw_py
        confidence = "high"
        reasoning = f"Found {backend_fw_py} in Python dependencies."

    elif has_python and is_cli:
        project_type = "cli_tool"
        backend_framework = None
        confidence = "high"
        reasoning = "Found CLI framework (click/typer/fire) in Python dependencies."

    elif has_python:
        project_type = "library"
        backend_framework = None
        confidence = "medium"
        reasoning = "Found Python project with no known web framework — assumed library."

    else:
        return None  # No recognisable config — defer to LLM

    # Contradiction guard: if rules said frontend_only but the dominant file type is a backend
    # language, rules likely missed something — medium confidence triggers LLM review in run()
    if project_type == "frontend_only":
        language = _detect_language(ext_counts, frontend_fw, backend_framework)
        if language in {"Python", "Java", "Go", "Rust", "C#", "Ruby", "PHP"}:
            confidence = "medium"

    return {
        "project_type": project_type,
        "frontend_framework": frontend_fw,
        "backend_framework": backend_framework,
        "confidence": confidence,
        "reasoning": reasoning,
        "test_strategy": _get_test_strategy(project_type, backend_framework),
    }


# --- LLM fallback ---

def _build_llm_message(scan: dict) -> str:
    tree_str = "\n".join(scan["file_tree"])
    ext_str = json.dumps(scan["extension_counts"], indent=2)
    config_parts = [f"--- {path} ---\n{content}" for path, content in scan["config_files"].items()]
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


_LLM_FALLBACK = {
    "project_type": "unknown",
    "frontend_framework": None,
    "backend_framework": None,
    "confidence": "low",
    "reasoning": "Could not parse classifier response.",
    "test_strategy": {"primary": "none", "secondary": None},
}


async def _classify_by_llm(scan: dict, client: anthropic.AsyncAnthropic) -> dict:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _build_llm_message(scan)}],
    )
    try:
        parsed = _parse_llm_response(response.content[0].text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")
        parsed.setdefault("project_type", "unknown")
        parsed.setdefault("frontend_framework", None)
        parsed.setdefault("backend_framework", None)
        for field in ("frontend_framework", "backend_framework"):
            if parsed.get(field) == "null":
                parsed[field] = None
        parsed.setdefault("confidence", "low")
        parsed.setdefault("reasoning", "No reasoning provided.")
        parsed["test_strategy"] = _get_test_strategy(parsed["project_type"], parsed.get("backend_framework"))
        return parsed
    except Exception:
        return dict(_LLM_FALLBACK)


# --- Entry point ---

async def run(extract_to: Path, client: anthropic.AsyncAnthropic) -> dict:
    root = _find_project_root(extract_to)
    scan = await asyncio.to_thread(_scan_project, root)

    rules_result = await asyncio.to_thread(_classify_by_rules, root, scan)
    llm_called = False
    llm_model = None
    result = rules_result

    # Fall back to LLM if rules couldn't classify confidently
    if rules_result is None or rules_result["confidence"] == "medium":
        llm_called = True
        llm_model = "claude-haiku-4-5-20251001"
        llm_result = await _classify_by_llm(scan, client)
        if rules_result is None or llm_result["confidence"] != "low":
            result = llm_result

    # Apply test dep overrides regardless of whether rule-based or LLM produced the result
    _apply_test_strategy_overrides(result, scan["js_deps"])

    if result.get("project_type") == "monorepo":
        has_android = any("app/build.gradle" in p for p in scan["config_files"].keys())
        if has_android:
            existing = result["test_strategy"].get("secondary")
            result["test_strategy"]["secondary"] = (
                f"{existing} + Android JUnit/Espresso" if existing else "Android JUnit/Espresso"
            )

    result["config_files_found"] = list(scan["config_files"].keys())
    result["llm_used"] = llm_called
    result["llm_model"] = llm_model
    return result
