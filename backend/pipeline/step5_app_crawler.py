"""
Step 5: App Crawler — L2 element inventory.

Two-pass:
1. Dynamic (Playwright): boot the app, visit each route, record interactive elements,
   outbound links, and observed network requests.
2. Static fallback (Tree-sitter / regex): for routes Playwright could not visit
   (auth-gated, redirects, boot failure), parse source JSX/TSX files from route_to_files.

No LLM call.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

# ─────────────────────────────────────────────────────────────
# Bootstrap heuristics
# ─────────────────────────────────────────────────────────────

# Ports chosen to avoid collision with DSTA's own services (8000, 5173)
_PORT_FRONTEND_VITE = 5174
_PORT_FRONTEND_CRA = 3000
_PORT_BACKEND = 8001
_PORT_BACKEND_FLASK = 5001
_PORT_BACKEND_EXPRESS = 3001
_PORT_STATIC = 8082

# (cmd, port, cwd)
_BootSpec = tuple[list[str], int, Path]


def _bootstrap_commands(ctx: dict, root: Path) -> list[_BootSpec]:
    """Return list of (cmd, port, cwd) processes to start. Empty → static-only mode."""
    project_type = (ctx.get("project_type") or "").strip().lower()
    frontend_fw = (ctx.get("frontend_framework") or "").strip().lower()
    backend_fw = (ctx.get("backend_framework") or "").strip().lower()
    tooling = (ctx.get("frontend_tooling") or "").strip().lower()
    service_layout = (ctx.get("service_layout") or "").strip().lower()

    if project_type == "mobile_app":
        return []

    if project_type == "static_site":
        return [([sys.executable, "-m", "http.server", str(_PORT_STATIC)], _PORT_STATIC, root)]

    if project_type == "frontend_only":
        cmd, port = _npm_cmd(root, tooling, frontend_fw)
        return [(cmd, port, root)]

    if project_type == "backend_api_only":
        spec = _backend_spec(root, backend_fw)
        return [spec] if spec else []

    if project_type == "full_stack_web_app":
        if service_layout == "separate_frontend_backend":
            frontend_dir = _find_frontend_dir(root) or root
            cmd, port = _npm_cmd(frontend_dir, tooling, frontend_fw)
            return [(cmd, port, frontend_dir)]
        else:
            # SSR: crawl via the backend renderer
            spec = _backend_spec(root, backend_fw)
            return [spec] if spec else []

    return []


def _npm_cmd(cwd: Path, tooling: str, frontend_fw: str) -> tuple[list[str], int]:
    npm = shutil.which("npm") or "npm"
    if "vite" in tooling or "vite" in frontend_fw:
        return ([npm, "run", "dev", "--", "--port", str(_PORT_FRONTEND_VITE)], _PORT_FRONTEND_VITE)
    if "next" in frontend_fw:
        return ([npm, "run", "dev", "--", "-p", str(_PORT_FRONTEND_CRA)], _PORT_FRONTEND_CRA)
    if "sveltekit" in frontend_fw or "svelte" in frontend_fw:
        return ([npm, "run", "dev", "--", "--port", str(_PORT_FRONTEND_VITE)], _PORT_FRONTEND_VITE)
    # CRA / Webpack / generic
    return ([npm, "start"], _PORT_FRONTEND_CRA)


def _backend_spec(root: Path, backend_fw: str) -> _BootSpec | None:
    npm = shutil.which("npm") or "npm"
    if "fastapi" in backend_fw or "uvicorn" in backend_fw:
        return ([sys.executable, "-m", "uvicorn", "main:app", "--port", str(_PORT_BACKEND)], _PORT_BACKEND, root)
    if "flask" in backend_fw:
        return ([sys.executable, "-m", "flask", "run", "--port", str(_PORT_BACKEND_FLASK)], _PORT_BACKEND_FLASK, root)
    if "django" in backend_fw:
        return ([sys.executable, "manage.py", "runserver", str(_PORT_BACKEND)], _PORT_BACKEND, root)
    if "express" in backend_fw or "nestjs" in backend_fw:
        return ([npm, "start"], _PORT_BACKEND_EXPRESS, root)
    if "spring" in backend_fw:
        if (root / "mvnw.cmd").exists():
            return (
                ["cmd", "/c", "mvnw.cmd", "spring-boot:run",
                 f"-Dspring-boot.run.jvmArguments=-Dserver.port={_PORT_BACKEND}"],
                _PORT_BACKEND, root,
            )
        if (root / "mvnw").exists():
            return (
                [str(root / "mvnw"), "spring-boot:run",
                 f"-Dspring-boot.run.jvmArguments=-Dserver.port={_PORT_BACKEND}"],
                _PORT_BACKEND, root,
            )
    return None


def _find_frontend_dir(root: Path) -> Path | None:
    for name in ("frontend", "client", "web", "ui"):
        d = root / name
        if d.is_dir() and (d / "package.json").exists():
            return d
    return None


# ─────────────────────────────────────────────────────────────
# Port readiness poll
# ─────────────────────────────────────────────────────────────

async def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    try:
        import httpx
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(2.0)) as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    r = await client.get(f"http://localhost:{port}/")
                    if r.status_code < 500:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1.5)
    except Exception:
        pass
    return False


# ─────────────────────────────────────────────────────────────
# Playwright crawl
# ─────────────────────────────────────────────────────────────

_JS_EXTRACT_ELEMENTS = """
() => {
    const items = [];
    const seen = new Set();
    document.querySelectorAll('input, button, select, textarea, a[href]').forEach(el => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = rect.width > 0 && rect.height > 0 &&
                        style.display !== 'none' && style.visibility !== 'hidden';
        const tag = el.tagName.toLowerCase();
        const type = el.getAttribute('type') || null;
        const rawLabel = (
            el.getAttribute('aria-label') ||
            el.getAttribute('placeholder') ||
            (tag !== 'input' && tag !== 'select' ? (el.textContent || '').trim() : '') ||
            el.getAttribute('title') ||
            el.getAttribute('name') ||
            ''
        ).slice(0, 80).trim();
        if (!rawLabel && tag !== 'select') return;
        const key = tag + '|' + (type || '') + '|' + rawLabel;
        if (seen.has(key)) return;
        seen.add(key);
        let selector = tag;
        const id = el.id;
        if (id && /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(id)) {
            selector = '#' + id;
        } else if (el.getAttribute('data-testid')) {
            selector = '[data-testid="' + el.getAttribute('data-testid') + '"]';
        } else if (el.getAttribute('name')) {
            selector = tag + '[name="' + el.getAttribute('name') + '"]';
        } else if (type) {
            selector = tag + '[type="' + type + '"]';
        }
        items.push({
            type: tag === 'a' ? 'link' : tag,
            subtype: type,
            label: rawLabel || null,
            selector: selector,
            visible: visible
        });
    });
    return items;
}
"""

_JS_OUTBOUND_LINKS = """
() => {
    const origin = window.location.origin;
    const current = window.location.pathname;
    const seen = new Set();
    const links = [];
    document.querySelectorAll('a[href]').forEach(a => {
        try {
            const url = new URL(a.href, window.location.href);
            if (url.origin === origin) {
                const p = url.pathname;
                if (p !== current && !seen.has(p)) {
                    seen.add(p);
                    links.push(p);
                }
            }
        } catch {}
    });
    return links;
}
"""


async def _crawl_routes(routes: list[str], port: int) -> tuple[list[dict], list[dict]]:
    """Returns (pages, unvisitable_routes). Requires playwright to be installed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [], [{"route": r, "reason": "playwright_not_installed"} for r in routes]

    base_url = f"http://localhost:{port}"
    pages_out: list[dict] = []
    unvisitable: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        for route in routes:
            url = base_url + route
            api_calls: list[str] = []

            def _on_request(request, _calls=api_calls):
                if request.resource_type in ("xhr", "fetch"):
                    try:
                        _calls.append(f"{request.method} {urlparse(request.url).path}")
                    except Exception:
                        pass

            page.on("request", _on_request)
            response = None
            reason: str | None = None

            try:
                response = await page.goto(url, wait_until="load", timeout=10_000)
                await page.wait_for_timeout(400)
            except Exception as exc:
                reason = "timeout" if "timeout" in str(exc).lower() else "error"
            finally:
                page.remove_listener("request", _on_request)

            if reason:
                unvisitable.append({"route": route, "reason": reason})
                pages_out.append(_empty_playwright_page(route))
                continue

            final_path = urlparse(page.url).path.rstrip("/") or "/"
            norm_route = route.rstrip("/") or "/"
            accessible = (
                response is not None
                and response.status < 400
                and final_path == norm_route
            )
            if not accessible:
                unvisitable.append({
                    "route": route,
                    "reason": "not_found" if (response and response.status >= 400) else "auth_required",
                })

            try:
                elements = await page.evaluate(_JS_EXTRACT_ELEMENTS)
                outbound = await page.evaluate(_JS_OUTBOUND_LINKS)
                title = await page.title()
            except Exception:
                elements, outbound, title = [], [], ""

            pages_out.append({
                "route": route,
                "title": title or None,
                "discovered_by": "playwright",
                "accessible": accessible,
                "elements": elements,
                "outbound_links": outbound,
                "api_calls_observed": list(dict.fromkeys(api_calls)),
            })

        await context.close()
        await browser.close()

    return pages_out, unvisitable


def _empty_playwright_page(route: str) -> dict:
    return {
        "route": route,
        "title": None,
        "discovered_by": "playwright",
        "accessible": False,
        "elements": [],
        "outbound_links": [],
        "api_calls_observed": [],
    }


# ─────────────────────────────────────────────────────────────
# Static fallback — JSX/TSX/HTML regex element extraction
# ─────────────────────────────────────────────────────────────

_JSX_INPUT_RE = re.compile(
    r"""<(input|textarea|select)\b([^>]*?)(?:/>|>)""",
    re.IGNORECASE | re.DOTALL,
)
_JSX_BUTTON_RE = re.compile(
    r"""<[Bb]utton\b([^>]*?)>([^<]{1,80})</[Bb]utton>""",
    re.DOTALL,
)
_ATTR_ARIA = re.compile(r"""aria-label\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_PH = re.compile(r"""placeholder\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_NAME = re.compile(r"""\bname\s*=\s*["'`{]([^"'`}{]+)["'`}]""")
_ATTR_TYPE = re.compile(r"""\btype\s*=\s*["'`{]([^"'`}{]+)["'`}]""")

_STATIC_EXTS = {".tsx", ".jsx", ".ts", ".js", ".html", ".jinja2", ".j2", ".erb", ".ejs"}


def _label_from_attrs(attrs: str) -> str | None:
    for pat in (_ATTR_ARIA, _ATTR_PH, _ATTR_NAME):
        m = pat.search(attrs)
        if m:
            v = m.group(1).strip()
            if v:
                return v
    return None


def _static_elements_from_text(text: str) -> list[dict]:
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
        elements.append({"type": tag, "subtype": subtype, "label": label, "selector": None, "visible": None})

    for m in _JSX_BUTTON_RE.finditer(text):
        attrs = m.group(1)
        text_content = m.group(2).strip()
        type_m = _ATTR_TYPE.search(attrs)
        subtype = type_m.group(1) if type_m else None
        aria_m = _ATTR_ARIA.search(attrs)
        label = (aria_m.group(1) if aria_m else text_content)[:80]
        if not label:
            continue
        key = (label, subtype)
        if key in seen:
            continue
        seen.add(key)
        elements.append({"type": "button", "subtype": subtype, "label": label, "selector": None, "visible": None})

    return elements


def _static_page(route: str, files: list[str], root: Path) -> dict:
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
        for el in _static_elements_from_text(text):
            key = (el["label"] or "", el["subtype"])
            if key not in seen:
                seen.add(key)
                elements.append(el)

    return {
        "route": route,
        "title": None,
        "discovered_by": "static_fallback",
        "accessible": None,
        "elements": elements,
        "outbound_links": [],
        "api_calls_observed": [],
    }


def _full_static(
    routes: list[str],
    route_to_files: dict[str, list[str]],
    important_files: list[str],
    root: Path,
    reason: str = "no_bootstrap",
) -> dict:
    pages = [_static_page(r, route_to_files.get(r, important_files[:5]), root) for r in routes]
    unvisitable = [{"route": r, "reason": reason} for r in routes]
    return {"pages": pages, "unvisitable_routes": unvisitable, "total_pages": len(pages), "error": None}


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

async def run(step3_5_result: dict, step4_result: dict, extract_to: Path) -> dict:
    """Boot the app, crawl routes with Playwright, fall back to Tree-sitter for unvisitable routes."""
    ctx = step3_5_result.get("project_context", {})
    routes: list[str] = step4_result.get("frontend_routes", [])
    route_to_files: dict[str, list[str]] = step4_result.get("route_to_files", {})
    important_files: list[str] = step4_result.get("important_files", [])

    if not routes:
        return {"pages": [], "unvisitable_routes": [], "total_pages": 0,
                "error": "No frontend routes in Step 4 output"}

    bootstrap = _bootstrap_commands(ctx, extract_to)

    if not bootstrap:
        return _full_static(routes, route_to_files, important_files, extract_to)

    processes: list[asyncio.subprocess.Process] = []
    try:
        for cmd, _port, cwd in bootstrap:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(cwd),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                processes.append(proc)
            except Exception:
                continue

        crawl_port = bootstrap[-1][1]
        app_started = bool(processes) and await _wait_for_port(crawl_port)

        if not app_started:
            return _full_static(routes, route_to_files, important_files, extract_to, reason="boot_failed")

        playwright_pages, playwright_unvisitable = await _crawl_routes(routes, crawl_port)

        unvisitable_routes = {u["route"] for u in playwright_unvisitable}
        visited_routes = {p["route"] for p in playwright_pages}

        pages: list[dict] = []
        unvisitable: list[dict] = list(playwright_unvisitable)

        for p in playwright_pages:
            if p["route"] in unvisitable_routes:
                # Replace inaccessible playwright page with static fallback elements
                pages.append(_static_page(
                    p["route"],
                    route_to_files.get(p["route"], important_files[:5]),
                    extract_to,
                ))
            else:
                pages.append(p)

        for route in routes:
            if route not in visited_routes:
                pages.append(_static_page(route, route_to_files.get(route, important_files[:5]), extract_to))
                unvisitable.append({"route": route, "reason": "not_visited"})

        return {"pages": pages, "unvisitable_routes": unvisitable, "total_pages": len(pages), "error": None}

    except Exception as exc:
        return {"pages": [], "unvisitable_routes": [], "total_pages": 0, "error": str(exc)}

    finally:
        for proc in processes:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
