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

    # TSX/JSX: self-closing <Route path="..." />
    _Q_TSX_ROUTE_SC = Query(
        _LANG_TSX,
        "(jsx_self_closing_element"
        "  name: (identifier) @tag"
        "  (jsx_attribute"
        "    (property_identifier) @attr"
        "    (string (string_fragment) @path)))",
    )

    # TSX/JSX: <Route path="...">...</Route>
    _Q_TSX_ROUTE_OPEN = Query(
        _LANG_TSX,
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
        routes = _extract_frontend_routes(all_files, frontend_fw, extract_to)
        models = _extract_database_models(all_files, backend_fw)
        important = _identify_important_files(all_files, extract_to, endpoints)
        route_to_files = _build_route_to_files(all_files, frontend_fw, extract_to, routes, endpoints, important)
        impl_units = _build_implementation_units(endpoints, all_files, extract_to)

        return {
            "languages": languages,
            "frontend_routes": routes,
            "api_endpoints": endpoints,
            "route_to_files": route_to_files,
            "implementation_units": impl_units,
            "database_models": models,
            "important_files": important,
            "existing_tests": tests,
            "total_endpoints": len(endpoints),
            "total_routes": len(routes),
            "error": None,
        }
    except Exception as exc:
        return {
            "languages": [],
            "frontend_routes": [],
            "api_endpoints": [],
            "route_to_files": {},
            "implementation_units": [],
            "database_models": [],
            "important_files": [],
            "existing_tests": [],
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
_VUE_ROUTE_PATH = re.compile(r"""path\s*:\s*['"]([^'"]*)['"]""")


def _extract_frontend_routes(
    files: list[Path], frontend_fw: str, root: Path
) -> list[str]:
    routes: set[str] = set()

    # ── Next.js file-based (pages/) ─────────────
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
                        routes.add(r)
            if routes:
                return sorted(routes)

    # ── Next.js App Router (app/) ────────────────
    for base_name in ("app", "src/app"):
        app_dir = root / base_name
        if app_dir.is_dir():
            for f in app_dir.rglob("page.tsx"):
                if not any(part in IGNORE_DIRS for part in f.parts):
                    rel = f.parent.relative_to(app_dir)
                    route = "/" + "/".join(rel.parts) if rel.parts else "/"
                    routes.add(_norm_path(route))
            if routes:
                return sorted(routes)

    # ── SvelteKit (src/routes/) ──────────────────
    svelte_dir = root / "src" / "routes"
    if svelte_dir.is_dir():
        for f in svelte_dir.rglob("+page.svelte"):
            if not any(part in IGNORE_DIRS for part in f.parts):
                rel = f.parent.relative_to(svelte_dir)
                route = "/" + "/".join(rel.parts) if rel.parts else "/"
                routes.add(_norm_path(route))
        if routes:
            return sorted(routes)

    # ── React Router — JSX <Route path="..." /> ──
    jsx_files = [
        f for f in files
        if f.suffix in {".tsx", ".jsx"}
        and not any(p in IGNORE_DIRS for p in f.parts)
    ]
    for f in jsx_files:
        parsed = _ts_parse(f)
        if not parsed:
            continue
        _, tree = parsed
        # Self-closing
        for _, caps in _run_query(_Q_TSX_ROUTE_SC, tree.root_node):
            tag_nodes = caps.get("tag", [])
            attr_nodes = caps.get("attr", [])
            path_nodes = caps.get("path", [])
            if (
                tag_nodes and attr_nodes and path_nodes
                and _text(tag_nodes[0]) == "Route"
                and _text(attr_nodes[0]) == "path"
            ):
                routes.add(_norm_path(_text(path_nodes[0])))
        # Opening element
        for _, caps in _run_query(_Q_TSX_ROUTE_OPEN, tree.root_node):
            tag_nodes = caps.get("tag", [])
            attr_nodes = caps.get("attr", [])
            path_nodes = caps.get("path", [])
            if (
                tag_nodes and attr_nodes and path_nodes
                and _text(tag_nodes[0]) == "Route"
                and _text(attr_nodes[0]) == "path"
            ):
                routes.add(_norm_path(_text(path_nodes[0])))

    # ── React Router v6 object-based (createBrowserRouter) ──
    for f in files:
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
        for m in _ROUTE_OBJ_PATH.finditer(text):
            candidate = m.group(1)
            if candidate and (candidate.startswith("/") or candidate == "*"):
                routes.add(_norm_path(candidate))

    # ── Vue Router / Angular routing ─────────────
    for f in files:
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
        for m in _VUE_ROUTE_PATH.finditer(text):
            routes.add(_norm_path(m.group(1)))

    # ── Static HTML fallback ─────────────────────
    if not routes:
        for f in files:
            if f.suffix == ".html" and not any(p in IGNORE_DIRS for p in f.parts):
                stem = f.stem
                routes.add("/" if stem == "index" else f"/{stem}")

    # Filter out wildcard-only catch-all (* alone)
    return sorted(r for r in routes if r != "/*" or len(routes) == 1)


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


def _identify_important_files(
    files: list[Path], root: Path, endpoints: list[dict]
) -> list[str]:
    important: set[str] = set()

    # Files hosting endpoints
    for ep in endpoints:
        if ep.get("file"):
            important.add(ep["file"])

    for f in files:
        fname = f.name
        if fname in _ENTRY_NAMES or fname in _ROUTE_CFG_NAMES or fname in _MODEL_CFG_NAMES:
            important.add(_rel(f, root))
        if fname.endswith("-routing.module.ts"):
            important.add(_rel(f, root))
        if fname in {"index.ts", "index.js"} and f.parent.name in {"router", "routes", "api"}:
            important.add(_rel(f, root))

    return sorted(important)[:20]


# ─────────────────────────────────────────────────────────────
# route_to_files: maps each frontend route → source file(s)
# ─────────────────────────────────────────────────────────────


def _build_route_to_files(
    all_files: list[Path],
    frontend_fw: str,
    root: Path,
    routes: list[str],
    endpoints: list[dict],
    important_files: list[str],
) -> dict[str, list[str]]:
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
                _fill_fallback(routes, route_files, important_files)
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
                _fill_fallback(routes, route_files, important_files)
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
            _fill_fallback(routes, route_files, important_files)
            return route_files

    # ── React Router: JSX files containing <Route path="..."> ─
    for f in all_files:
        if f.suffix not in {".tsx", ".jsx"}:
            continue
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        parsed = _ts_parse(f)
        if not parsed:
            continue
        _, tree = parsed
        found: set[str] = set()
        for _, caps in _run_query(_Q_TSX_ROUTE_SC, tree.root_node):
            tag_n = caps.get("tag", [])
            attr_n = caps.get("attr", [])
            path_n = caps.get("path", [])
            if tag_n and attr_n and path_n and _text(tag_n[0]) == "Route" and _text(attr_n[0]) == "path":
                found.add(_norm_path(_text(path_n[0])))
        for _, caps in _run_query(_Q_TSX_ROUTE_OPEN, tree.root_node):
            tag_n = caps.get("tag", [])
            attr_n = caps.get("attr", [])
            path_n = caps.get("path", [])
            if tag_n and attr_n and path_n and _text(tag_n[0]) == "Route" and _text(attr_n[0]) == "path":
                found.add(_norm_path(_text(path_n[0])))
        rel_f = _rel(f, root)
        for r in found:
            lst = route_files.setdefault(r, [])
            if rel_f not in lst:
                lst.append(rel_f)

    if route_files:
        _fill_fallback(routes, route_files, important_files)
        return route_files

    # ── SSR (Flask/Django): endpoint file → route, then templates ──
    # Use sets to accumulate, convert to list at end to avoid duplicates
    route_file_sets: dict[str, set[str]] = {}

    for ep in endpoints:
        ep_path = ep.get("path", "")
        if ep_path in routes and ep.get("file"):
            route_file_sets.setdefault(ep_path, set()).add(ep["file"])

    # Template files: match stem to route (e.g. login.html → /login)
    for f in all_files:
        if f.suffix.lower() not in _TEMPLATE_EXTS:
            continue
        if any(p in IGNORE_DIRS for p in f.parts):
            continue
        if not any(part in _TEMPLATE_DIRS for part in f.parts):
            continue
        slug = "/" + f.stem if f.stem != "index" else "/"
        if slug in routes:
            route_file_sets.setdefault(slug, set()).add(_rel(f, root))

    # Static HTML fallback
    for f in all_files:
        if f.suffix != ".html" or any(p in IGNORE_DIRS for p in f.parts):
            continue
        slug = "/" if f.stem == "index" else f"/{f.stem}"
        if slug in routes:
            route_file_sets.setdefault(slug, set()).add(_rel(f, root))

    for route, file_set in route_file_sets.items():
        route_files[route] = sorted(file_set)

    _fill_fallback(routes, route_files, important_files)
    return route_files


def _fill_fallback(
    routes: list[str],
    route_files: dict[str, list[str]],
    important_files: list[str],
) -> None:
    fallback = important_files[:5]
    for route in routes:
        if route not in route_files:
            route_files[route] = fallback


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
            action = _norm_path(action_m.group(1)) if action_m else None
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
