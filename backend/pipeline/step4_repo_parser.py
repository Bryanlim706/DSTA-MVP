"""
Step 4: Repo Parser — builds L3 inventory from the uploaded codebase.

Extracts without any LLM call:
  - languages spoken
  - API endpoints (backend)
  - frontend routes
  - database models
  - important files
  - test files

Tree-sitter 0.25 API: Query() + QueryCursor().matches(node)
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
import tree_sitter_typescript as tsts

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from tree_sitter import Language, Parser, Query, QueryCursor

# ─────────────────────────────────────────────────────────────
# Language objects (created once at import time)
# ─────────────────────────────────────────────────────────────

_LANG_PY = Language(tspython.language())
_LANG_JS = Language(tsjs.language())
_LANG_TS = Language(tsts.language_typescript())
_LANG_TSX = Language(tsts.language_tsx())
_LANG_JAVA = Language(tsjava.language())

_EXT_TO_LANG: dict[str, Language] = {
    ".py": _LANG_PY,
    ".js": _LANG_JS,
    ".jsx": _LANG_JS,
    ".ts": _LANG_TS,
    ".tsx": _LANG_TSX,
    ".java": _LANG_JAVA,
}

# ─────────────────────────────────────────────────────────────
# Tree-sitter queries (compiled once at import time)
# ─────────────────────────────────────────────────────────────

with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    # Python: decorated function definitions
    _Q_PY_DECORATED = Query(
        _LANG_PY,
        "(decorated_definition (decorator) @dec"
        " (function_definition name: (identifier) @handler))",
    )

    # Java: class-level annotation with a path argument
    _Q_JAVA_CLASS_ANN = Query(
        _LANG_JAVA,
        "(class_declaration"
        "  (modifiers"
        "    (annotation"
        "      name: (identifier) @ann"
        "      (annotation_argument_list (string_literal) @path)))"
        "  name: (identifier) @class_name)",
    )

    # Java: method-level annotation with a path argument
    _Q_JAVA_METHOD_ANN = Query(
        _LANG_JAVA,
        "(method_declaration"
        "  (modifiers"
        "    (annotation"
        "      name: (identifier) @ann"
        "      (annotation_argument_list (string_literal) @path)))"
        "  name: (identifier) @method_name)",
    )

    # Java: method-level annotation WITHOUT path (e.g. bare @GetMapping)
    _Q_JAVA_METHOD_ANN_NOPATH = Query(
        _LANG_JAVA,
        "(method_declaration"
        "  (modifiers"
        "    (marker_annotation name: (identifier) @ann))"
        "  name: (identifier) @method_name)",
    )

    # TSX: self-closing <Route path="..." />  (.tsx files)
    _Q_TSX_ROUTE_SC = Query(
        _LANG_TSX,
        "(jsx_self_closing_element"
        "  name: (identifier) @tag"
        "  (jsx_attribute"
        "    (property_identifier) @attr"
        "    (string (string_fragment) @path)))",
    )

    # TSX: <Route path="...">...</Route>  (.tsx files)
    _Q_TSX_ROUTE_OPEN = Query(
        _LANG_TSX,
        "(jsx_element"
        "  open_tag: (jsx_opening_element"
        "    name: (identifier) @tag"
        "    (jsx_attribute"
        "      (property_identifier) @attr"
        "      (string (string_fragment) @path))))",
    )

    # JS: self-closing <Route path="..." />  (.jsx/.js files — same pattern, different language)
    _Q_JS_ROUTE_SC = Query(
        _LANG_JS,
        "(jsx_self_closing_element"
        "  name: (identifier) @tag"
        "  (jsx_attribute"
        "    (property_identifier) @attr"
        "    (string (string_fragment) @path)))",
    )

    # JS: <Route path="...">...</Route>  (.jsx/.js files)
    _Q_JS_ROUTE_OPEN = Query(
        _LANG_JS,
        "(jsx_element"
        "  open_tag: (jsx_opening_element"
        "    name: (identifier) @tag"
        "    (jsx_attribute"
        "      (property_identifier) @attr"
        "      (string (string_fragment) @path))))",
    )

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "venv", "__pycache__",
    "coverage", ".tox", ".mypy_cache", "target", ".gradle", "out", ".idea",
    ".vscode", ".cache", "vendor", "bower_components", "eggs", ".eggs",
    "htmlcov", ".pytest_cache", "examples", "demo", "demos", "sample", "samples",
    "assets",  # static asset dirs (e.g. public/assets/js/) contain no app source
}

_LANG_NAMES: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".php": "PHP",
    ".rb": "Ruby",
    ".go": "Go",
    ".cs": "C#",
    ".swift": "Swift",
    ".rs": "Rust",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB cap for tree-sitter parsing

_ANN_TO_METHOD: dict[bytes, str] = {
    b"GetMapping": "GET",
    b"PostMapping": "POST",
    b"PutMapping": "PUT",
    b"DeleteMapping": "DELETE",
    b"PatchMapping": "PATCH",
    b"RequestMapping": "GET",
}

# Template file extensions for form_handler and route_to_files detection
_TEMPLATE_EXTS = {
    ".html", ".htm", ".jinja2", ".jinja", ".j2",
    ".ejs", ".erb", ".cshtml", ".twig",
}
_TEMPLATE_DIRS = {"templates", "views", "partials", "layouts"}

# HTML form tag parsing
_FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_FORM_METHOD_RE = re.compile(r'\bmethod\s*=\s*["\']?(\w+)', re.IGNORECASE)
_FORM_ACTION_RE = re.compile(r'\baction\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)

# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────


async def run(step3_5_result: dict, extract_to: Path) -> dict:
    """Parse the codebase and return L3 inventory. No LLM call."""
    try:
        ctx = step3_5_result.get("project_context", {})
        backend_fw = (ctx.get("backend_framework") or "").strip().lower()
        frontend_fw = (ctx.get("frontend_framework") or "").strip().lower()

        all_files = _walk_files(extract_to)
        languages = _detect_languages(all_files)
        tests = _find_test_files(all_files, extract_to)
        endpoints = _extract_api_endpoints(all_files, backend_fw, extract_to)
        models = _extract_database_models(all_files, backend_fw)
        important = _identify_important_files(all_files, extract_to, endpoints)
        route_to_files = _build_route_to_files(all_files, frontend_fw, extract_to, endpoints, important)
        routes = sorted(route_to_files.keys())
        impl_units = _build_implementation_units(endpoints, all_files, extract_to)
        route_elements = _extract_route_elements(route_to_files, extract_to)
        navigation_graph = _extract_navigation_graph(route_to_files, extract_to)

        return {
            # L3 scoring inputs — consumed by Step 6 E() formula
            "frontend_routes": [_route_entry(r) for r in routes],
            "implementation_units": impl_units,
            "route_elements": route_elements,
            "navigation_graph": navigation_graph,
            # Infrastructure — route→file mapping used internally for route_elements/navigation_graph
            "route_to_files": route_to_files,
            "important_files": important,
            # Context / reporting — Step 15/16 evidence pack, Step 7.5 advisor
            "database_models": models,
            "existing_tests": tests,
            "languages": languages,
            "total_endpoints": len(endpoints),
            "total_routes": len(routes),
            "error": None,
        }
    except Exception as exc:
        return {
            "frontend_routes": [],
            "implementation_units": [],
            "route_elements": {},
            "navigation_graph": {},
            "route_to_files": {},
            "important_files": [],
            "database_models": [],
            "existing_tests": [],
            "languages": [],
            "total_endpoints": 0,
            "total_routes": 0,
            "error": str(exc),
        }


# ─────────────────────────────────────────────────────────────
# File walking
# ─────────────────────────────────────────────────────────────


def _walk_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts):
            result.append(p)
    return result


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


# ─────────────────────────────────────────────────────────────
# Language detection
# ─────────────────────────────────────────────────────────────


def _detect_languages(files: list[Path]) -> list[str]:
    counts: dict[str, int] = {}
    for f in files:
        name = _LANG_NAMES.get(f.suffix.lower())
        if name:
            counts[name] = counts.get(name, 0) + 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda x: -x[1])]


# ─────────────────────────────────────────────────────────────
# Tree-sitter helpers
# ─────────────────────────────────────────────────────────────


def _ts_parse(path: Path) -> tuple[Language, object] | None:
    lang = _EXT_TO_LANG.get(path.suffix.lower())
    if lang is None:
        return None
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        src = path.read_bytes()
        parser = Parser(lang)
        return lang, parser.parse(src)
    except Exception:
        return None


def _run_query(query: Query, node) -> list[tuple[int, dict]]:
    """Execute a query via QueryCursor, return list of (idx, caps) matches."""
    try:
        cursor = QueryCursor(query)
        return list(cursor.matches(node))
    except Exception:
        return []


def _text(node) -> str:
    """Decode node.text bytes to str."""
    return node.text.decode("utf-8", errors="replace") if node.text else ""


# ─────────────────────────────────────────────────────────────
# Path normalisation
# ─────────────────────────────────────────────────────────────


def _norm_path(raw: str) -> str:
    """Ensure path starts with / and has no trailing / (except root)."""
    p = raw.strip()
    if not p:
        return "/"
    if not p.startswith("/"):
        p = "/" + p
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p


def _join(base: str, sub: str) -> str:
    base = base.rstrip("/")
    sub = sub if sub.startswith("/") else ("/" + sub if sub else "")
    return _norm_path(base + sub) if (base + sub) else "/"


# ─────────────────────────────────────────────────────────────
# API Endpoint extraction
# ─────────────────────────────────────────────────────────────


def _extract_api_endpoints(
    files: list[Path], backend_fw: str, root: Path
) -> list[dict]:
    endpoints: list[dict] = []

    if "flask" in backend_fw or "fastapi" in backend_fw:
        endpoints = _endpoints_python(files, root)
    elif "django" in backend_fw:
        endpoints = _endpoints_django(files, root)
    elif "express" in backend_fw or "nestjs" in backend_fw or "nest" in backend_fw:
        endpoints = _endpoints_express(files, root, backend_fw)
    elif "spring" in backend_fw:
        endpoints = _endpoints_spring(files, root)

    # Deduplicate by (method, path)
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for ep in endpoints:
        key = (ep["method"], ep["path"])
        if key not in seen:
            seen.add(key)
            unique.append(ep)
    return unique


# ── Python Flask / FastAPI ──────────────────────

# Regex to extract path and method from decorator text
_PY_DEC_PATH = re.compile(
    r'\.(route|get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_PY_METHODS = re.compile(r'methods\s*=\s*\[([^\]]+)\]', re.IGNORECASE)


def _endpoints_python(files: list[Path], root: Path) -> list[dict]:
    endpoints: list[dict] = []
    for f in files:
        if f.suffix != ".py":
            continue
        parsed = _ts_parse(f)
        if not parsed:
            continue
        _, tree = parsed
        src = f.read_bytes()

        for _, caps in _run_query(_Q_PY_DECORATED, tree.root_node):
            dec_nodes = caps.get("dec", [])
            handler_nodes = caps.get("handler", [])
            if not dec_nodes:
                continue
            dec_text = _text(dec_nodes[0])
            handler = _text(handler_nodes[0]) if handler_nodes else ""

            m = _PY_DEC_PATH.search(dec_text)
            if not m:
                continue
            verb = m.group(1).lower()
            path_str = _norm_path(m.group(2))
            methods_m = _PY_METHODS.search(dec_text)
            if methods_m:
                for meth in re.findall(r"[A-Z]+", methods_m.group(1)):
                    endpoints.append(
                        {"method": meth, "path": path_str, "file": _rel(f, root), "handler": handler}
                    )
            else:
                method = "GET" if verb == "route" else verb.upper()
                endpoints.append(
                    {"method": method, "path": path_str, "file": _rel(f, root), "handler": handler}
                )
    return endpoints


# ── Django urls.py ──────────────────────────────

_DJANGO_PATH = re.compile(
    r'\bpath\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_DJANGO_INCLUDE = re.compile(r'\binclude\s*\(')


def _endpoints_django(files: list[Path], root: Path) -> list[dict]:
    endpoints: list[dict] = []
    for f in files:
        if f.name != "urls.py" or f.suffix != ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in _DJANGO_PATH.finditer(text):
            raw = m.group(1).lstrip("^").rstrip("$")
            # Skip include() redirects and empty paths from re_path
            ctx = text[m.end():m.end() + 60]
            if _DJANGO_INCLUDE.search(ctx):
                continue
            endpoints.append(
                {"method": "GET", "path": _norm_path(raw), "file": _rel(f, root), "handler": ""}
            )
    return endpoints


# ── Express / NestJS ────────────────────────────

_EXPRESS_ROUTE = re.compile(
    r'\b(?:app|router|server)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_NESTJS_DEC = re.compile(
    r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\']',
)
_NESTJS_CTRL = re.compile(
    r'@Controller\s*\(\s*["\']([^"\']*)["\']',
)


def _endpoints_express(
    files: list[Path], root: Path, backend_fw: str
) -> list[dict]:
    endpoints: list[dict] = []
    is_nest = "nest" in backend_fw
    for f in files:
        if f.suffix not in {".js", ".ts", ".jsx", ".tsx"}:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if is_nest:
            base = ""
            ctrl_m = _NESTJS_CTRL.search(text)
            if ctrl_m:
                base = _norm_path(ctrl_m.group(1))
            for m in _NESTJS_DEC.finditer(text):
                verb = m.group(1).upper()
                path_str = _join(base, m.group(2))
                endpoints.append(
                    {"method": verb, "path": path_str, "file": _rel(f, root), "handler": ""}
                )
        else:
            for m in _EXPRESS_ROUTE.finditer(text):
                verb = m.group(1).upper()
                endpoints.append(
                    {"method": verb, "path": _norm_path(m.group(2)), "file": _rel(f, root), "handler": ""}
                )
    return endpoints


# ── Spring Boot (Java + Kotlin) ─────────────────

_KT_SPRING = re.compile(
    r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\(\s*["\']([^"\']+)["\']',
)
_KT_CLASS_MAPPING = re.compile(
    r'@RequestMapping\s*\(\s*["\']([^"\']+)["\']',
)


def _endpoints_spring(files: list[Path], root: Path) -> list[dict]:
    endpoints: list[dict] = []
    for f in files:
        if f.suffix not in {".java", ".kt"}:
            continue

        if f.suffix == ".kt":
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            base = ""
            cm = _KT_CLASS_MAPPING.search(text)
            if cm:
                base = _norm_path(cm.group(1))
            for m in _KT_SPRING.finditer(text):
                verb = _ANN_TO_METHOD.get(m.group(1).encode(), "GET")
                endpoints.append(
                    {"method": verb, "path": _join(base, m.group(2)), "file": _rel(f, root), "handler": ""}
                )
            continue

        # Java via tree-sitter
        parsed = _ts_parse(f)
        if not parsed:
            continue
        _, tree = parsed

        # Class-level base path
        base = ""
        for _, caps in _run_query(_Q_JAVA_CLASS_ANN, tree.root_node):
            ann_nodes = caps.get("ann", [])
            path_nodes = caps.get("path", [])
            if ann_nodes and b"RequestMapping" in ann_nodes[0].text and path_nodes:
                raw = _text(path_nodes[0]).strip('"').strip("'")
                base = _norm_path(raw)
                break

        # Method-level mappings — with explicit path arg (e.g. @GetMapping("/users"))
        for _, caps in _run_query(_Q_JAVA_METHOD_ANN, tree.root_node):
            ann_nodes = caps.get("ann", [])
            path_nodes = caps.get("path", [])
            handler_nodes = caps.get("method_name", [])
            if not ann_nodes or not path_nodes:
                continue
            ann_bytes = ann_nodes[0].text
            verb = _ANN_TO_METHOD.get(ann_bytes)
            if not verb:
                continue
            raw = _text(path_nodes[0]).strip('"').strip("'")
            handler = _text(handler_nodes[0]) if handler_nodes else ""
            endpoints.append(
                {"method": verb, "path": _join(base, raw), "file": _rel(f, root), "handler": handler}
            )

        # Method-level mappings — bare annotation without path (e.g. @GetMapping alone)
        for _, caps in _run_query(_Q_JAVA_METHOD_ANN_NOPATH, tree.root_node):
            ann_nodes = caps.get("ann", [])
            handler_nodes = caps.get("method_name", [])
            if not ann_nodes:
                continue
            ann_bytes = ann_nodes[0].text
            verb = _ANN_TO_METHOD.get(ann_bytes)
            if not verb:
                continue
            handler = _text(handler_nodes[0]) if handler_nodes else ""
            # Path is just the base path (no sub-path)
            endpoints.append(
                {"method": verb, "path": base or "/", "file": _rel(f, root), "handler": handler}
            )

    return endpoints


# ─────────────────────────────────────────────────────────────
# Frontend route extraction
# ─────────────────────────────────────────────────────────────

_ROUTE_OBJ_PATH = re.compile(r"""(?:path|to)\s*:\s*['"]([^'"]+)['"]""")

# React Router: extract route→component from <Route path="..." element={<ComponentName
_ROUTE_COMPONENT_RE = re.compile(
    r"""path\s*=\s*["']([^"']+)["'](?:[^>]*?\n?)*?element\s*=\s*\{[^<]*<(\w+)""",
    re.DOTALL,
)
# Import statement: import Name from "path"
_IMPORT_NAME_RE = re.compile(r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]""")
_VUE_ROUTE_PATH = re.compile(r"""path\s*:\s*['"]([^'"]*)['"]""")
_DYNAMIC_SEGMENT = re.compile(r'(:\w+|\{\w+\}|\[[^\]]+\]|<\w+>)')


def _route_entry(path: str) -> dict:
    """Return {path, dynamic, params} metadata for a route path string."""
    params = _DYNAMIC_SEGMENT.findall(path)
    param_names = [re.sub(r'[:{}\[\]<>]', '', p) for p in params]
    return {"path": path, "dynamic": bool(params), "params": param_names}


def _extract_frontend_routes(
    files: list[Path], frontend_fw: str, root: Path, *, endpoints: list[dict] | None = None
) -> list[str]:
    """Thin wrapper retained for direct test calls. Returns sorted route paths."""
    route_to_files = _build_route_to_files(files, frontend_fw, root, endpoints or [], [])
    return sorted(route_to_files.keys())


def _nextjs_path(rel: Path) -> str | None:
    parts = list(rel.parts)
    if not parts:
        return "/"
    last = Path(parts[-1]).stem
    if last.startswith("_"):
        return None
    parts[-1] = last
    if last == "index":
        parts.pop()
    route = "/" + "/".join(parts)
    return route if route else "/"


# ─────────────────────────────────────────────────────────────
# Database model extraction
# ─────────────────────────────────────────────────────────────

_SA_CLASS = re.compile(
    r'class\s+(\w+)\s*\(([^)]*(?:Base|Model|db\.Model|models\.Model|DeclarativeBase)[^)]*)\)'
)
_SA_ABSTRACT = re.compile(r'__abstract__\s*=\s*True')
_JPA_ENTITY_RE = re.compile(r'@(?:Entity|javax\.persistence\.Entity)\b')
_JAVA_CLASS_NAME = re.compile(r'class\s+(\w+)')
_PRISMA_MODEL = re.compile(r'^model\s+(\w+)\s*\{', re.MULTILINE)
_MONGOOSE_SCHEMA = re.compile(
    r'(?:const|let|var)\s+(\w+)\s*=\s*new\s+(?:mongoose\.)?Schema\s*\('
)
_TYPEORM_ENTITY_DEC = re.compile(r'@Entity\s*\(')
_TS_CLASS_NAME = re.compile(r'class\s+(\w+)')


def _extract_database_models(files: list[Path], backend_fw: str) -> list[str]:
    models: set[str] = set()

    for f in files:
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        try:
            # ── Prisma schema ───────────────────
            if f.suffix == ".prisma":
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in _PRISMA_MODEL.finditer(text):
                    models.add(m.group(1))
                continue

            # ── Python ORM ──────────────────────
            if f.suffix == ".py":
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in _SA_CLASS.finditer(text):
                    # Exclude abstract base classes
                    class_start = m.end()
                    body = text[class_start: class_start + 500]
                    if not _SA_ABSTRACT.search(body):
                        models.add(m.group(1))
                continue

            # ── Java JPA ────────────────────────
            if f.suffix == ".java":
                text = f.read_text(encoding="utf-8", errors="replace")
                if _JPA_ENTITY_RE.search(text):
                    cm = _JAVA_CLASS_NAME.search(text)
                    if cm:
                        models.add(cm.group(1))
                continue

            # ── TypeScript (TypeORM / Mongoose) ─
            if f.suffix in {".ts", ".tsx"}:
                text = f.read_text(encoding="utf-8", errors="replace")
                if "@Entity" in text:
                    for m in _TYPEORM_ENTITY_DEC.finditer(text):
                        cm = _TS_CLASS_NAME.search(text, m.end())
                        if cm:
                            models.add(cm.group(1))
                for m in _MONGOOSE_SCHEMA.finditer(text):
                    name = m.group(1).replace("Schema", "").replace("schema", "")
                    if name:
                        models.add(name)
                continue

            # ── JavaScript (Mongoose) ────────────
            if f.suffix in {".js", ".jsx"}:
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in _MONGOOSE_SCHEMA.finditer(text):
                    name = m.group(1).replace("Schema", "").replace("schema", "")
                    if name:
                        models.add(name)

        except Exception:
            continue

    return sorted(models)


# ─────────────────────────────────────────────────────────────
# Test file detection
# ─────────────────────────────────────────────────────────────

_TEST_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".java"}
_TEST_FILENAME_RE = re.compile(
    r"^(?:test_.+|.+_test)\.py$"
    r"|^.+\.(?:test|spec)\.(?:ts|tsx|js|jsx)$"
    r"|^.+(?:Test|Tests|IT)\.java$"
)
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}


def _find_test_files(files: list[Path], root: Path) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []

    for f in files:
        if f.suffix not in _TEST_SUFFIXES:
            continue
        is_test = _TEST_FILENAME_RE.match(f.name) or any(
            part in _TEST_DIRS for part in f.parts
        )
        if is_test:
            rel = _rel(f, root)
            if rel not in seen:
                seen.add(rel)
                results.append(rel)

    return sorted(results)[:100]


# ─────────────────────────────────────────────────────────────
# Important file detection
# ─────────────────────────────────────────────────────────────

_ENTRY_NAMES = {
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    "index.ts", "index.js", "main.ts", "main.js",
    "App.tsx", "App.jsx", "App.ts", "App.js",
    "main.java", "Application.java",
    "index.html",
}
_ROUTE_CFG_NAMES = {"urls.py", "router.js", "router.ts"}
_MODEL_CFG_NAMES = {
    "models.py", "schema.prisma", "database.py", "db.py",
    "entities.py", "schemas.py",
}
_PAGE_DIRS = {"pages", "screens", "views"}
_COMPONENT_DIRS = {"components"}
_SERVICE_DIRS = {"services", "api", "hooks", "store"}
_CONFIG_FILE_NAMES = {
    "application.properties", "application.yml", "application.yaml",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "package.json", "settings.py",
}
_JAVA_LAYER_DIRS = {"service", "services", "security", "config", "repository", "repositories"}


def _identify_important_files(
    files: list[Path], root: Path, endpoints: list[dict]
) -> list[str]:
    important: set[str] = set()

    # Files hosting endpoints
    for ep in endpoints:
        if ep.get("file"):
            important.add(ep["file"])

    for f in files:
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        fname = f.name

        # Entry points, route configs, model configs
        if fname in _ENTRY_NAMES or fname in _ROUTE_CFG_NAMES or fname in _MODEL_CFG_NAMES:
            important.add(_rel(f, root))
        if fname.endswith("-routing.module.ts"):
            important.add(_rel(f, root))
        if fname in {"index.ts", "index.js"} and f.parent.name in {"router", "routes", "api"}:
            important.add(_rel(f, root))

        # Frontend page components (pages/, screens/, views/)
        if f.suffix in {".tsx", ".jsx", ".vue", ".svelte"} and f.parent.name in _PAGE_DIRS:
            important.add(_rel(f, root))

        # Frontend UI components
        if f.suffix in {".tsx", ".jsx", ".vue"} and f.parent.name in _COMPONENT_DIRS:
            important.add(_rel(f, root))

        # Service / API client files
        if f.suffix in {".ts", ".js"} and f.parent.name in _SERVICE_DIRS:
            important.add(_rel(f, root))

        # Config and properties files
        if fname in _CONFIG_FILE_NAMES:
            important.add(_rel(f, root))

        # Java service / security / repository layer
        if f.suffix == ".java" and f.parent.name in _JAVA_LAYER_DIRS:
            important.add(_rel(f, root))

    return sorted(important)[:100]


# ─────────────────────────────────────────────────────────────
# route_to_files: maps each frontend route → source file(s)
# ─────────────────────────────────────────────────────────────


def _route_component_files(router_file: Path, root: Path) -> dict[str, str]:
    """Given a React Router file, return {route: component_file_rel_path} by parsing
    element={<ComponentName />} attributes and resolving imports."""
    try:
        text = router_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    # Build import map: ComponentName → resolved relative path
    imports: dict[str, str] = {}
    for m in _IMPORT_NAME_RE.finditer(text):
        name = m.group(1)
        import_path = m.group(2)
        if not import_path.startswith("."):
            continue
        base = router_file.parent / import_path
        for ext in ("", ".jsx", ".tsx", ".js", ".ts", "/index.jsx", "/index.tsx", "/index.js"):
            candidate = Path(str(base) + ext) if ext and not ext.startswith("/") else base / ext.lstrip("/")
            if candidate.is_file():
                imports[name] = _rel(candidate, root)
                break

    # Map route → component file
    result: dict[str, str] = {}
    for m in _ROUTE_COMPONENT_RE.finditer(text):
        route = _norm_path(m.group(1))
        component_name = m.group(2)
        comp_file = imports.get(component_name)
        if comp_file:
            result[route] = comp_file
    return result


def _shallow_component_imports(component_rel: str, root: Path) -> list[str]:
    """Return relative paths of all directly imported local files from a component (1 level deep).
    Gives Step 5 static fallback visibility into child component files where form elements live."""
    abs_path = root / component_rel
    root_resolved = root.resolve()
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    results: list[str] = []
    seen: set[str] = set()
    for m in _IMPORT_NAME_RE.finditer(text):
        import_path = m.group(2)
        if not import_path.startswith("."):
            continue
        base = abs_path.parent / import_path
        for ext in ("", ".jsx", ".tsx", ".js", ".ts", "/index.jsx", "/index.tsx", "/index.js"):
            candidate = (
                Path(str(base) + ext) if ext and not ext.startswith("/")
                else base / ext.lstrip("/")
            )
            if candidate.is_file():
                # resolve() normalises '..' segments (e.g. src/pages/../components/X → src/components/X)
                rel = _rel(candidate.resolve(), root_resolved)
                if rel not in seen:
                    seen.add(rel)
                    results.append(rel)
                break
    return results


def _expand_with_shallow_imports(route_files: dict[str, list[str]], root: Path) -> None:
    """Expand each route's file list with 1-level-deep local imports.
    Ensures Step 5 static fallback sees child components (forms, modals, layout) not just the page root."""
    for files in route_files.values():
        existing = set(files)
        additions: list[str] = []
        for rel in list(files):
            for child in _shallow_component_imports(rel, root):
                if child not in existing:
                    existing.add(child)
                    additions.append(child)
        files.extend(additions)


def _build_route_to_files(
    all_files: list[Path],
    frontend_fw: str,
    root: Path,
    endpoints: list[dict],
    important_files: list[str],
) -> dict[str, list[str]]:
    """Discover every frontend route and map it to its source file(s) in one pass.
    Route discovery and file mapping are unified — no external routes list needed."""
    route_files: dict[str, list[str]] = {}

    # ── Next.js pages/ (file-based routing) ──────────────────
    for base_name in ("pages", "src/pages"):
        pages_dir = root / base_name
        if pages_dir.is_dir():
            for f in pages_dir.rglob("*"):
                if (
                    f.is_file()
                    and f.suffix in {".tsx", ".ts", ".jsx", ".js"}
                    and not f.name.startswith("_")
                    and not any(part in IGNORE_DIRS for part in f.parts)
                ):
                    r = _nextjs_path(f.relative_to(pages_dir))
                    if r:
                        route_files.setdefault(r, []).append(_rel(f, root))
            if route_files:
                _expand_with_shallow_imports(route_files, root)
                return route_files

    # ── Next.js App Router (app/) ─────────────────────────────
    for base_name in ("app", "src/app"):
        app_dir = root / base_name
        if app_dir.is_dir():
            for f in app_dir.rglob("page.tsx"):
                if not any(part in IGNORE_DIRS for part in f.parts):
                    rel = f.parent.relative_to(app_dir)
                    route = _norm_path("/" + "/".join(rel.parts) if rel.parts else "/")
                    route_files.setdefault(route, []).append(_rel(f, root))
            if route_files:
                _expand_with_shallow_imports(route_files, root)
                return route_files

    # ── SvelteKit (src/routes/) ───────────────────────────────
    svelte_dir = root / "src" / "routes"
    if svelte_dir.is_dir():
        for f in svelte_dir.rglob("+page.svelte"):
            if not any(part in IGNORE_DIRS for part in f.parts):
                rel = f.parent.relative_to(svelte_dir)
                route = _norm_path("/" + "/".join(rel.parts) if rel.parts else "/")
                route_files.setdefault(route, []).append(_rel(f, root))
        if route_files:
            _expand_with_shallow_imports(route_files, root)
            return route_files

    # ── React Router: JSX <Route> + createBrowserRouter/useRoutes ─
    # Step 1: tree-sitter JSX <Route path="...">
    for f in all_files:
        if f.suffix not in {".tsx", ".jsx"}:
            continue
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        parsed = _ts_parse(f)
        if not parsed:
            continue
        _, tree = parsed
        q_sc = _Q_JS_ROUTE_SC if f.suffix in {".jsx", ".js"} else _Q_TSX_ROUTE_SC
        q_open = _Q_JS_ROUTE_OPEN if f.suffix in {".jsx", ".js"} else _Q_TSX_ROUTE_OPEN
        found: set[str] = set()
        for _, caps in _run_query(q_sc, tree.root_node):
            tag_n = caps.get("tag", [])
            attr_n = caps.get("attr", [])
            path_n = caps.get("path", [])
            if tag_n and attr_n and path_n and _text(tag_n[0]) == "Route" and _text(attr_n[0]) == "path":
                found.add(_norm_path(_text(path_n[0])))
        for _, caps in _run_query(q_open, tree.root_node):
            tag_n = caps.get("tag", [])
            attr_n = caps.get("attr", [])
            path_n = caps.get("path", [])
            if tag_n and attr_n and path_n and _text(tag_n[0]) == "Route" and _text(attr_n[0]) == "path":
                found.add(_norm_path(_text(path_n[0])))
        if not found:
            continue
        rel_f = _rel(f, root)
        for r in found:
            lst = route_files.setdefault(r, [])
            if rel_f not in lst:
                lst.append(rel_f)
        comp_map = _route_component_files(f, root)
        for r, comp_file in comp_map.items():
            if r in found and comp_file:
                lst = route_files.setdefault(r, [])
                if comp_file not in lst:
                    lst.append(comp_file)

    # Step 2: createBrowserRouter / useRoutes object-based paths
    for f in all_files:
        if f.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if "react-router" not in text and "createBrowserRouter" not in text and "useRoutes" not in text:
            continue
        rel_f = _rel(f, root)
        for m in _ROUTE_OBJ_PATH.finditer(text):
            candidate = m.group(1)
            if candidate and (candidate.startswith("/") or candidate == "*"):
                r = _norm_path(candidate)
                lst = route_files.setdefault(r, [])
                if rel_f not in lst:
                    lst.append(rel_f)

    if route_files:
        _expand_with_shallow_imports(route_files, root)
        if "/*" in route_files and len(route_files) > 1:
            del route_files["/*"]
        return route_files

    # ── Vue Router / Angular routing ──────────────────────────
    for f in all_files:
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        fname = f.name
        is_vue_router = fname in {"router.js", "router.ts"} or (
            f.parent.name in {"router", "routes"}
            and fname in {"index.ts", "index.js"}
        )
        is_angular = fname.endswith("-routing.module.ts")
        if not is_vue_router and not is_angular:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel_f = _rel(f, root)
        for m in _VUE_ROUTE_PATH.finditer(text):
            route = _norm_path(m.group(1))
            lst = route_files.setdefault(route, [])
            if rel_f not in lst:
                lst.append(rel_f)

    if route_files:
        return route_files

    # ── SSR endpoint fallback (Flask/Django — no JS frontend) ──
    if not frontend_fw and endpoints:
        for ep in endpoints:
            if ep.get("method") == "GET" and ep.get("path") and ep.get("file"):
                route = _norm_path(ep["path"])
                lst = route_files.setdefault(route, [])
                if ep["file"] not in lst:
                    lst.append(ep["file"])
        # Also add matching template files
        for f in all_files:
            if f.suffix.lower() not in _TEMPLATE_EXTS:
                continue
            if any(p in IGNORE_DIRS for p in f.parts):
                continue
            if not any(part in _TEMPLATE_DIRS for part in f.parts):
                continue
            slug = _norm_path("/" + f.stem if f.stem != "index" else "/")
            if slug in route_files:
                rel = _rel(f, root)
                if rel not in route_files[slug]:
                    route_files[slug].append(rel)
        if route_files:
            return route_files

    # ── Static HTML fallback ──────────────────────────────────
    route_file_sets: dict[str, set[str]] = {}
    for f in all_files:
        if f.suffix != ".html" or any(p in IGNORE_DIRS for p in f.parts):
            continue
        stem = f.stem
        slug = "/" if stem == "index" else f"/{stem}"
        route_file_sets.setdefault(slug, set()).add(_rel(f, root))

    # SPA/Electron: route maps only to HTML shell — also add App component
    _APP_NAMES = {"App.tsx", "App.jsx", "App.ts", "App.js"}
    for slug, file_set in route_file_sets.items():
        if all(p.endswith(".html") for p in file_set):
            app_file = next(
                (imp for imp in important_files if Path(imp).name in _APP_NAMES),
                None,
            )
            if app_file is None:
                app_file = next(
                    (_rel(f, root) for f in all_files if f.name in _APP_NAMES
                     and not any(p in IGNORE_DIRS for p in f.parts)),
                    None,
                )
            if app_file:
                file_set.add(app_file)

    for route, file_set in route_file_sets.items():
        route_files[route] = sorted(file_set)

    return route_files


# ─────────────────────────────────────────────────────────────
# implementation_units: generalised api_endpoints + form_handlers
# ─────────────────────────────────────────────────────────────


def _build_implementation_units(
    endpoints: list[dict],
    all_files: list[Path],
    root: Path,
) -> list[dict]:
    units: list[dict] = []

    # Wrap all existing api_endpoints
    for ep in endpoints:
        units.append({
            "kind": "api_endpoint",
            "method": ep.get("method"),
            "path": ep.get("path"),
            "file": ep.get("file"),
            "handler": ep.get("handler"),
        })

    # HTML template form handlers
    seen: set[tuple[str | None, str | None]] = set()
    for f in all_files:
        suffix = f.suffix.lower()
        is_template = suffix in _TEMPLATE_EXTS or f.name.endswith(".blade.php")
        if not is_template:
            continue
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in _FORM_TAG_RE.finditer(text):
            attrs = m.group(1)
            method_m = _FORM_METHOD_RE.search(attrs)
            action_m = _FORM_ACTION_RE.search(attrs)
            method = method_m.group(1).upper() if method_m else "POST"
            if method not in {"POST", "PUT", "DELETE", "PATCH"}:
                continue
            raw_action = action_m.group(1) if action_m else None
            # Blade/Jinja/Twig template expressions can't be resolved statically
            if raw_action and ("{{" in raw_action or "{%" in raw_action or raw_action.startswith("{")):
                raw_action = None
            action = _norm_path(raw_action) if raw_action else None
            key = (method, action)
            if key in seen:
                continue
            seen.add(key)
            units.append({
                "kind": "form_handler",
                "method": method,
                "path": action,
                "file": _rel(f, root),
                "handler": None,
            })

    return units


# ─────────────────────────────────────────────────────────────
# L3 element inventory: parse source files per route
# ─────────────────────────────────────────────────────────────

_STATIC_EXTS = {".tsx", ".jsx", ".ts", ".js", ".html", ".jinja2", ".j2", ".erb", ".ejs"}

_JSX_INPUT_RE = re.compile(
    r"""<(input|textarea|select)\b([^>]*?)(?:/>|>)""",
    re.IGNORECASE | re.DOTALL,
)
_JSX_BUTTON_RE = re.compile(
    r"""<[Bb]utton\b([^>]*?)>(.*?)</[Bb]utton>""",
    re.DOTALL,
)
_ATTR_ARIA = re.compile(r"""aria-label\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_PH = re.compile(r"""placeholder\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_NAME = re.compile(r"""\bname\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_TYPE = re.compile(r"""\btype\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_JSX_BLOCK_COMMENT_RE = re.compile(r'\{/\*.*?\*/\}', re.DOTALL)
_LINE_COMMENT_ONLY_RE = re.compile(r'^\s*//.*$', re.MULTILINE)


def _strip_comments(text: str) -> str:
    text = _JSX_BLOCK_COMMENT_RE.sub('', text)
    text = _LINE_COMMENT_ONLY_RE.sub('', text)
    return text


def _label_from_attrs(attrs: str) -> str | None:
    for pat in (_ATTR_ARIA, _ATTR_PH, _ATTR_NAME):
        m = pat.search(attrs)
        if m:
            v = m.group(1).strip()
            if v:
                return v
    return None


def _elements_from_text(text: str) -> list[dict]:
    """Extract interactive elements from source. Returns {type, subtype, label} — no runtime fields."""
    text = _strip_comments(text)
    elements: list[dict] = []
    seen: set[tuple[str, str | None]] = set()

    for m in _JSX_INPUT_RE.finditer(text):
        tag = m.group(1).lower()
        attrs = m.group(2)
        type_m = _ATTR_TYPE.search(attrs)
        subtype = type_m.group(1) if type_m else None
        label = _label_from_attrs(attrs)
        if not label:
            continue
        key = (label, subtype)
        if key in seen:
            continue
        seen.add(key)
        elements.append({"type": tag, "subtype": subtype, "label": label})

    for m in _JSX_BUTTON_RE.finditer(text):
        attrs = m.group(1)
        raw_text = m.group(2).strip()
        if '>' in raw_text:
            raw_text = raw_text.rsplit('>', 1)[1].strip()
        if raw_text.startswith('{') and not raw_text.strip('{}').strip():
            raw_text = ''
        elif raw_text.startswith('{'):
            qm = re.search(r'"([^"]{1,80})"', raw_text)
            raw_text = qm.group(1) if qm else re.sub(r'\{[^{}]*\}', '', raw_text).strip()
        type_m = _ATTR_TYPE.search(attrs)
        subtype = type_m.group(1) if type_m else None
        aria_m = _ATTR_ARIA.search(attrs)
        label = (aria_m.group(1) if aria_m else raw_text)[:80]
        if not label:
            continue
        key = (label, subtype)
        if key in seen:
            continue
        seen.add(key)
        elements.append({"type": "button", "subtype": subtype, "label": label})

    return elements


def _extract_route_elements(
    route_to_files: dict[str, list[str]], root: Path
) -> dict[str, list[dict]]:
    """L3 element inventory: {route: [{type, subtype, label}, ...]} parsed from source files."""
    result: dict[str, list[dict]] = {}
    for route, files in route_to_files.items():
        elements: list[dict] = []
        seen: set[tuple[str, str | None]] = set()
        for rel in files:
            p = root / rel
            if p.suffix.lower() not in _STATIC_EXTS:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for el in _elements_from_text(text):
                key = (el["label"], el["subtype"])
                if key not in seen:
                    seen.add(key)
                    elements.append(el)
        if elements:
            result[route] = elements
    return result


# ─────────────────────────────────────────────────────────────
# L3 navigation graph: parse source files per route
# ─────────────────────────────────────────────────────────────

# Matches static string paths in navigation directives — skips template literals and variables.
# Covers: <Link to="/p">, <a href="/p">, navigate("/p"), router.push("/p"), history.push("/p"),
#         <RouterLink to="/p">, <a routerLink="/p">
_NAV_TARGET_RE = re.compile(
    r'(?:(?:to|href|routerLink)\s*=\s*["\']'
    r'|(?:navigate|router\.push|history\.push)\s*\(\s*["\'])'
    r'([/][^"\'?#\s]*)["\']',
    re.IGNORECASE,
)


def _extract_navigation_graph(
    route_to_files: dict[str, list[str]], root: Path
) -> dict[str, list[str]]:
    """L3 navigation graph: {route: [target_routes...]} from navigation triggers in source."""
    graph: dict[str, list[str]] = {}
    for route, files in route_to_files.items():
        targets: set[str] = set()
        for rel in files:
            p = root / rel
            if p.suffix.lower() not in _STATIC_EXTS:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in _NAV_TARGET_RE.finditer(text):
                target = _norm_path(m.group(1))
                if target != route:
                    targets.add(target)
        if targets:
            graph[route] = sorted(targets)
    return graph
