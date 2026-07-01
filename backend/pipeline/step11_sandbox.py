"""
Step 11 — Test Execution Sandbox

Boots the evaluated app in Docker containers and executes test scripts.
Primary target: Spring Boot (Maven/Gradle) + React/Vite frontend.

Boot sequence:
  1.  Pre-checks: Docker available, ports free
  2.  Detect backend dir (pom.xml / build.gradle) and frontend dir + type
  3.  Detect DB type (MySQL / PostgreSQL / MariaDB / H2 fallback)
  4.  Detect Spring profile (application-test.properties etc.)
  5.  Detect extra env vars needed (JWT_SECRET, mail, etc.)
  6.  Copy source into jobs/{job_id}/sandbox/{backend,frontend}/
  7.  Patch vite.config proxy targets to use Docker service hostname
  8.  Write Dockerfiles (backend: fat-JAR detection; frontend: type-specific)
  9.  Write docker-compose.yml (DB service + healthcheck + depends_on)
  10. docker compose build (Maven/Gradle download deps)
  11. docker compose up -d
  12. Poll host ports until healthy or timeout
  13. Execute test scripts (Step 9 output) — empty until Steps 8-10 are built
  14. docker compose down in finally block
"""

import asyncio
import json
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx

# Host ports — never collide with DSTA (8000, 5173) or Step 5 (8001, 5174)
BACKEND_HOST_PORT       = 8081
FRONTEND_HOST_PORT      = 5181

BUILD_TIMEOUT_S         = 420   # Maven dep download + compile
BOOT_TIMEOUT_S          = 240   # DB init (MySQL ~90 s) + backend start
FRONTEND_BOOT_TIMEOUT_S = 60    # npm run dev is fast once image is built
POLL_INTERVAL_S         = 5
TEARDOWN_TIMEOUT_S      = 30

SPRING_PROFILE_CANDIDATES: list[tuple[str, str]] = [
    ("test",  "src/main/resources/application-test.properties"),
    ("test",  "src/main/resources/application-test.yml"),
    ("dev",   "src/main/resources/application-dev.properties"),
    ("dev",   "src/main/resources/application-dev.yml"),
    ("local", "src/main/resources/application-local.properties"),
    ("local", "src/main/resources/application-local.yml"),
]

_COPY_IGNORE = shutil.ignore_patterns(
    "node_modules", "target", ".git", "build", "dist",
    ".next", "__pycache__", ".gradle", "out", ".idea", ".vscode",
)

# ---------------------------------------------------------------------------
# Backend Dockerfile templates
# ---------------------------------------------------------------------------

# Fat-JAR detection: unpack MANIFEST.MF from every candidate JAR, look for
# the Spring-Boot-Version entry which is only present in repackaged fat JARs.
# `jar` is from the JDK already present in the build stage — no extra install.
_JAR_FIND_MAVEN = r"""
    BOOT_JAR=$(for j in $(find /app -name "*.jar" -path "*/target/*" \
        ! -name "*-sources.jar" ! -name "*-javadoc.jar" \
        ! -name "*-plain.jar"   ! -name "original-*.jar"); do \
      jar tf "$j" 2>/dev/null | grep -q "^BOOT-INF/" && echo "$j" && break; done) && \
    [ -n "$BOOT_JAR" ] || { echo "ERROR: Spring Boot fat JAR not found in target/"; exit 1; } && \
    cp "$BOOT_JAR" /app.jar
""".strip()

_JAR_FIND_GRADLE = r"""
    BOOT_JAR=$(for j in $(find /app -name "*.jar" -path "*/build/libs/*" \
        ! -name "*-plain.jar"); do \
      jar tf "$j" 2>/dev/null | grep -q "^BOOT-INF/" && echo "$j" && break; done) && \
    [ -n "$BOOT_JAR" ] || { echo "ERROR: Spring Boot fat JAR not found in build/libs/"; exit 1; } && \
    cp "$BOOT_JAR" /app.jar
""".strip()

_BACKEND_DOCKERFILE_MAVEN = f"""\
FROM maven:3.9-eclipse-temurin-21-alpine AS build
WORKDIR /app
COPY . .
RUN mvn package -DskipTests -B -q && \\
    {_JAR_FIND_MAVEN}
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
"""

_BACKEND_DOCKERFILE_GRADLE = f"""\
FROM gradle:8-jdk21-alpine AS build
WORKDIR /app
COPY . .
RUN if [ -f ./gradlew ]; then chmod +x ./gradlew && ./gradlew bootJar --no-daemon -q; \\
    else gradle bootJar --no-daemon -q; fi && \\
    {_JAR_FIND_GRADLE}
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
"""

# ---------------------------------------------------------------------------
# Frontend Dockerfile templates — all standardise on internal port 5174
# ---------------------------------------------------------------------------

# Vite — production build + vite preview (avoids SWC native binary
# incompatibility between Windows node_modules and Alpine Linux; preview
# respects preview.proxy config from the vite.sandbox.config.js sidecar
# written by _write_vite_sandbox_config).
_FRONTEND_DOCKERFILE_VITE = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ARG VITE_API_URL=http://localhost:{BACKEND_HOST_PORT}
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build
EXPOSE 5174
CMD ["./node_modules/.bin/vite", "preview", "--config", "vite.sandbox.config.js", "--host", "0.0.0.0", "--port", "5174"]
"""

# Create React App — PORT env var controls the CRA dev server port.
# REACT_APP_API_URL is baked at build time via webpack DefinePlugin, so it must be
# an ARG (not ENV) so compose build args can override the default.
_FRONTEND_DOCKERFILE_CRA = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ENV PORT=5174
ENV HOST=0.0.0.0
ARG REACT_APP_API_URL=http://localhost:{FRONTEND_HOST_PORT}
ENV REACT_APP_API_URL=$REACT_APP_API_URL
ENV CHOKIDAR_USEPOLLING=true
ENV BROWSER=none
EXPOSE 5174
CMD ["npm", "start"]
"""

# Angular — ng serve with explicit host/port; disable host-check so the
# container is reachable from the Docker host.
_FRONTEND_DOCKERFILE_ANGULAR = """\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
EXPOSE 5174
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "5174", "--disable-host-check"]
"""

# Next.js — PORT env var; HOSTNAME for the dev server; NEXT_PUBLIC_ prefix for
# client-accessible env vars. ARG so compose build args can override.
_FRONTEND_DOCKERFILE_NEXTJS = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ENV PORT=5174
ENV HOSTNAME=0.0.0.0
ARG NEXT_PUBLIC_API_URL=http://localhost:{FRONTEND_HOST_PORT}
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
EXPOSE 5174
CMD ["npm", "run", "dev"]
"""

# Generic Node frontend — tries npm run dev first, falls back to npm start.
_FRONTEND_DOCKERFILE_GENERIC = """\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ENV PORT=5174
ENV HOST=0.0.0.0
EXPOSE 5174
CMD ["sh", "-c", "npm run dev 2>/dev/null || npm start"]
"""


def _frontend_dockerfile(frontend_type: str) -> str:
    return {
        "vite":    _FRONTEND_DOCKERFILE_VITE,
        "cra":     _FRONTEND_DOCKERFILE_CRA,
        "angular": _FRONTEND_DOCKERFILE_ANGULAR,
        "nextjs":  _FRONTEND_DOCKERFILE_NEXTJS,
    }.get(frontend_type, _FRONTEND_DOCKERFILE_GENERIC)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _check_docker_available() -> str | None:
    """Return None if Docker daemon is reachable, or an error string."""
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        return None if r.returncode == 0 else "Docker daemon not responding (is Docker Desktop running?)"
    except FileNotFoundError:
        return "Docker not found — install Docker Desktop and ensure it is in PATH"
    except subprocess.TimeoutExpired:
        return "docker info timed out — Docker daemon may still be starting"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect(("localhost", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


# ---------------------------------------------------------------------------
# Project layout detection
# ---------------------------------------------------------------------------

def _unwrap_root(root: Path) -> Path:
    """Unwrap single-dir zip wrapper (same pattern as Steps 0, 4, 5)."""
    while True:
        contents = [p for p in root.iterdir() if not p.name.startswith(".")]
        if len(contents) == 1 and contents[0].is_dir():
            root = contents[0]
        else:
            break
    return root


def _detect_frontend_type(d: Path) -> str | None:
    """Classify a directory as a known frontend project type."""
    if list(d.glob("vite.config*")):
        return "vite"
    if (d / "angular.json").exists():
        return "angular"
    if list(d.glob("next.config*")):
        return "nextjs"
    pkg = d / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
        except Exception:
            return "generic"
        all_deps = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
        }
        if "react-scripts" in all_deps:
            return "cra"
        scripts = data.get("scripts", {})
        if "dev" in scripts or "start" in scripts:
            return "generic"
    return None


def _find_dirs(root: Path) -> tuple[Path | None, Path | None, str]:
    """
    Return (backend_dir, frontend_dir, frontend_type).

    Searches root + one level deeper (handles single-wrapper zips where all
    real dirs are one level inside the wrapper).
    """
    backend_dir:   Path | None = None
    frontend_dir:  Path | None = None
    frontend_type: str         = "generic"

    def _is_backend(d: Path) -> bool:
        return (
            (d / "pom.xml").exists()
            or (d / "build.gradle").exists()
            or (d / "build.gradle.kts").exists()
        )

    def _is_frontend(d: Path) -> str | None:
        return _detect_frontend_type(d)

    candidates = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]

    for d in candidates:
        if backend_dir is None and _is_backend(d):
            backend_dir = d
        if frontend_dir is None:
            ft = _is_frontend(d)
            if ft:
                frontend_dir  = d
                frontend_type = ft

    # Root itself may be the backend (single-repo with a frontend subdir)
    if backend_dir is None and _is_backend(root):
        backend_dir = root

    # Root itself may be the frontend (SPA at root with a backend/ subdir)
    if frontend_dir is None and backend_dir is not root:
        ft = _is_frontend(root)
        if ft:
            frontend_dir  = root
            frontend_type = ft

    # One level deeper — handles partial zip-wrapper unwrap
    if backend_dir is None or frontend_dir is None:
        for wrapper in candidates:
            if not wrapper.is_dir():
                continue
            try:
                sub_dirs = [p for p in wrapper.iterdir() if p.is_dir() and not p.name.startswith(".")]
            except PermissionError:
                continue
            for d in sub_dirs:
                if backend_dir is None and _is_backend(d):
                    backend_dir = d
                if frontend_dir is None:
                    ft = _is_frontend(d)
                    if ft:
                        frontend_dir  = d
                        frontend_type = ft

    return backend_dir, frontend_dir, frontend_type


# ---------------------------------------------------------------------------
# Spring Boot configuration detection
# ---------------------------------------------------------------------------

def _detect_spring_profile(backend_dir: Path) -> str | None:
    for profile, rel in SPRING_PROFILE_CANDIDATES:
        if (backend_dir / rel).exists():
            return profile
    return None


def _has_h2_dep(backend_dir: Path) -> bool:
    pom = backend_dir / "pom.xml"
    if pom.exists():
        return "com.h2database" in pom.read_text(errors="ignore")
    for name in ("build.gradle", "build.gradle.kts"):
        g = backend_dir / name
        if g.exists():
            return "h2" in g.read_text(errors="ignore").lower()
    return False


def _detect_db_type(backend_dir: Path) -> str | None:
    """Return 'mysql' | 'postgresql' | 'mariadb' | None from Maven/Gradle artifact IDs."""
    text = ""
    pom = backend_dir / "pom.xml"
    if pom.exists():
        text += pom.read_text(errors="ignore").lower()
    for name in ("build.gradle", "build.gradle.kts"):
        g = backend_dir / name
        if g.exists():
            text += g.read_text(errors="ignore").lower()

    # Check most specific artifact IDs first to avoid false positives.
    # MariaDB before MySQL — mariadb-java-client is unambiguous.
    if "mariadb-java-client" in text:
        return "mariadb"
    # mysql-connector-j (new) or mysql-connector-java (legacy)
    if "mysql-connector-j" in text or "mysql-connector-java" in text:
        return "mysql"
    # org.postgresql:postgresql
    if "org.postgresql" in text or ":postgresql" in text:
        return "postgresql"
    return None


def _detect_build_tool(backend_dir: Path) -> str:
    return "maven" if (backend_dir / "pom.xml").exists() else "gradle"


def _detect_spring_extra_env(backend_dir: Path) -> dict[str, str]:
    """
    Inject dummy environment variables for common Spring Boot deps that fail
    to initialize without configuration (JWT secrets, mail servers, etc.).
    """
    text = ""
    for path in (
        backend_dir / "pom.xml",
        backend_dir / "build.gradle",
        backend_dir / "build.gradle.kts",
    ):
        if path.exists():
            text += path.read_text(errors="ignore").lower()

    env: dict[str, str] = {}

    # Only inject JWT vars for libraries that explicitly handle JWT secrets.
    # spring-security alone does NOT require a JWT_SECRET env var.
    if any(k in text for k in ("jjwt", "java-jwt", "nimbus-jose-jwt")):
        env["JWT_SECRET"]     = "sandbox_secret_key_min_32_chars_long"
        env["JWT_EXPIRATION"] = "86400000"

    if "spring-boot-starter-mail" in text or "jakarta.mail" in text or "javax.mail" in text:
        env["SPRING_MAIL_HOST"] = "localhost"
        env["SPRING_MAIL_PORT"] = "25"

    return env


_PROP_PLACEHOLDER_RE = re.compile(r"\$\{([^}:]+)\}")


def _detect_property_placeholders(backend_dir: Path) -> dict[str, str]:
    """
    Scan application.properties for ${varname} placeholders that have no
    :default fallback. These cause 'Could not resolve placeholder' errors at
    Spring Boot startup when no corresponding env var is set.
    Returns {ENV_VAR_NAME: 'sandbox_dummy'} for each unresolved placeholder.
    """
    props = backend_dir / "src/main/resources/application.properties"
    if not props.exists():
        return {}
    try:
        text = props.read_text(errors="ignore")
    except Exception:
        return {}
    result: dict[str, str] = {}
    for m in _PROP_PLACEHOLDER_RE.finditer(text):
        name = m.group(1).strip()
        env_name = name.upper().replace("-", "_").replace(".", "_")
        result[env_name] = "sandbox_dummy"
    return result


# ---------------------------------------------------------------------------
# Port and API call style detection
# ---------------------------------------------------------------------------

def _detect_spring_port(backend_dir: Path) -> int:
    """Read server.port from application.properties or application.yml; default 8080."""
    props = backend_dir / "src/main/resources/application.properties"
    if props.exists():
        for line in props.read_text(errors="ignore").splitlines():
            m = re.match(r"\s*server\.port\s*=\s*(\d+)", line)
            if m:
                return int(m.group(1))
    yml = backend_dir / "src/main/resources/application.yml"
    if yml.exists():
        in_server = False
        for line in yml.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if re.match(r"server\s*:", stripped):
                in_server = True
                continue
            if in_server:
                if stripped and not line[0].isspace():
                    in_server = False
                m = re.match(r"\s+port\s*:\s*(\d+)", line)
                if m:
                    return int(m.group(1))
    return 8080


def _detect_frontend_port(frontend_dir: Path, frontend_type: str) -> int:
    """Detect the port the frontend dev server will listen on; used for compose port mapping."""
    for name in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.cjs"):
        cfg = frontend_dir / name
        if cfg.exists():
            text = cfg.read_text(errors="ignore")
            m = re.search(r"server\s*:\s*\{[^}]*?port\s*:\s*(\d+)", text, re.DOTALL)
            if m:
                return int(m.group(1))
            break
    pkg = frontend_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore"))
            for script in data.get("scripts", {}).values():
                m = re.search(r"--port[=\s]+(\d+)", str(script))
                if m:
                    return int(m.group(1))
        except Exception:
            pass
    return {"vite": 5173, "cra": 3000, "angular": 4200, "nextjs": 3000}.get(frontend_type, 3000)


_SCAN_EXTS       = {".js", ".ts", ".tsx", ".jsx"}
_SCAN_IGNORE     = {"node_modules", "dist", "build", ".next", "__pycache__"}
_ENV_BASED_RE    = re.compile(r"import\.meta\.env\.VITE_|process\.env\.REACT_APP_|process\.env\.NEXT_PUBLIC_")
_RELATIVE_API_RE  = re.compile(r"""(?:fetch|axios\.(?:get|post|put|delete|patch))\s*\(\s*["']/(?!/)""")
_HARDCODED_RE     = re.compile(r"https?://localhost:(\d+)")
_SAME_ORIGIN_RE   = re.compile(r"window\.location\.(?:host|origin|protocol)")


def _scan_env_var_names(frontend_dir: Path) -> list[str]:
    """
    Scan frontend source for actual environment variable names used
    (VITE_*, REACT_APP_*, NEXT_PUBLIC_*). Returns unique names found,
    so we can inject the right build args rather than guessing fixed names.
    """
    env_name_re = re.compile(
        r"(?:import\.meta\.env\.|process\.env\.)((VITE_|REACT_APP_|NEXT_PUBLIC_)\w+)"
    )
    names: set[str] = set()
    for path in frontend_dir.rglob("*"):
        if path.suffix not in _SCAN_EXTS:
            continue
        if _SCAN_IGNORE.intersection(path.parts):
            continue
        try:
            for m in env_name_re.finditer(path.read_text(errors="ignore")):
                names.add(m.group(1))
        except Exception:
            continue
    return sorted(names)


def _strip_hardcoded_origin(sb_frontend: Path, hardcoded_port: int) -> str | None:
    """
    Replace `http://localhost:{hardcoded_port}` with an empty string in all
    frontend source files so absolute API URLs become relative paths.
    e.g. `http://localhost:8080/api/login` → `/api/login`
    This eliminates the cross-origin request entirely — the Vite preview
    proxy then forwards the relative call to the backend container, so Spring
    Boot's CORS config is never involved.
    Returns a warning string if any files were patched, else None.
    """
    origin = f"http://localhost:{hardcoded_port}"
    patched_files = []
    for path in (sb_frontend / "src").rglob("*"):
        if path.suffix not in _SCAN_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if origin in text:
                path.write_text(text.replace(origin, ""), encoding="utf-8")
                patched_files.append(path.name)
        except Exception:
            continue
    if patched_files:
        return (
            f"Hardcoded API origin '{origin}' stripped from "
            f"{len(patched_files)} file(s) ({', '.join(patched_files[:5])}"
            f"{'…' if len(patched_files) > 5 else ''}). "
            f"The submission would fail CORS in any environment other than the "
            f"developer's own machine on port {hardcoded_port}."
        )
    return None


def _detect_api_call_style(frontend_dir: Path) -> tuple[str, int | None]:
    """
    Scan frontend source files to determine how the app calls the backend API.
    Returns one of:
      ("env_based", None)    — uses VITE_API_URL / REACT_APP_API_URL / NEXT_PUBLIC_API_URL
      ("relative", None)     — fetch('/api/...') or axios.get('/...')
      ("same_origin", None)  — window.location.host/origin used to build API URLs
      ("hardcoded", port)    — http://localhost:PORT hardcoded in source
      ("unknown", None)      — no API calls detected
    Priority: env_based > relative > same_origin > hardcoded.
    """
    found_env         = False
    found_rel         = False
    found_same_origin = False
    hardcoded_port: int | None = None

    for path in frontend_dir.rglob("*"):
        if path.suffix not in _SCAN_EXTS:
            continue
        if _SCAN_IGNORE.intersection(path.parts):
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        if _ENV_BASED_RE.search(text):
            found_env = True
        if _RELATIVE_API_RE.search(text):
            found_rel = True
        if _SAME_ORIGIN_RE.search(text):
            found_same_origin = True
        if hardcoded_port is None:
            m = _HARDCODED_RE.search(text)
            if m:
                port = int(m.group(1))
                if port not in {8000, 5173}:  # ignore DSTA's own service ports
                    hardcoded_port = port

    if found_env:
        return ("env_based", None)
    # hardcoded takes priority over relative: when both exist (e.g. axios instance with
    # hardcoded baseURL + relative path calls), the hardcoded origin must be stripped.
    if hardcoded_port is not None:
        return ("hardcoded", hardcoded_port)
    if found_rel:
        return ("relative", None)
    if found_same_origin:
        return ("same_origin", None)
    return ("unknown", None)


# ---------------------------------------------------------------------------
# Tailwind v4 CSS patching
# ---------------------------------------------------------------------------

_TW_V3_DIRECTIVES_RE = re.compile(
    r"^[ \t]*@tailwind\s+(?:base|components|utilities)\s*;[ \t]*$",
    re.MULTILINE,
)


def _patch_tailwind_css(sb_frontend: Path) -> str | None:
    """
    Detect Tailwind v4 (@tailwindcss/postcss in package.json) used with v3-style
    CSS directives (@tailwind base/components/utilities). In v4 these directives
    produce an empty CSS file. Replace the entire block with @import "tailwindcss"
    so the v4 engine generates real output.
    Returns a warning string if a patch was applied, else None.
    """
    pkg = sb_frontend / "package.json"
    if not pkg.exists():
        return None
    try:
        data = json.loads(pkg.read_text(errors="ignore"))
    except Exception:
        return None
    all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    if "@tailwindcss/postcss" not in all_deps and "@tailwindcss/vite" not in all_deps:
        return None  # not Tailwind v4

    patched_files = []
    for css_file in (sb_frontend / "src").rglob("*.css"):
        text = css_file.read_text(errors="ignore")
        if not _TW_V3_DIRECTIVES_RE.search(text):
            continue
        stripped = _TW_V3_DIRECTIVES_RE.sub("", text).lstrip("\n")
        css_file.write_text('@import "tailwindcss";\n' + stripped, encoding="utf-8")
        patched_files.append(css_file.name)

    if patched_files:
        return (
            f"Tailwind v4 + v3 directives detected — patched {', '.join(patched_files)} "
            f"to use '@import \"tailwindcss\"'. The submission's CSS would produce an empty "
            f"stylesheet in any clean build environment."
        )
    return None


# ---------------------------------------------------------------------------
# Vite proxy — sidecar config written next to the submission's vite.config
# ---------------------------------------------------------------------------

# Written into the sandbox frontend dir; Vite is told to use it via --config.
# Imports the submission's vite.config (any format: object or function form,
# .ts/.js/.mjs) and merges in a catch-all preview proxy pointing at the backend
# container.  No regex parsing of the original config needed.
_VITE_SANDBOX_CONFIG = """\
// Written by DSTA sandbox — merges submission's vite config with a preview proxy
// so API calls from the browser are forwarded to the backend container.
import {{ mergeConfig }} from 'vite';
import baseConfig from './vite.config';

// defineConfig(fn) returns the fn; defineConfig(obj) returns the obj.
// Handle both so the typeof check works correctly.
const base = typeof baseConfig === 'function'
  ? baseConfig({{ mode: 'production', command: 'preview', ssrBuild: false }})
  : (baseConfig || {{}});

export default mergeConfig(base, {{
  preview: {{
    proxy: {{
      '/': {{
        target: '{target}',
        changeOrigin: true,
        configure: function(proxy, _options) {{
          proxy.on('proxyReq', function(proxyReq) {{
            // Strip browser origin/referer so Spring Boot's DefaultCorsProcessor
            // never sees a cross-origin request — the proxy is the requester here,
            // not the browser, so CORS enforcement is irrelevant on the server side.
            proxyReq.removeHeader('origin');
            proxyReq.removeHeader('referer');
          }});
        }},
        bypass: function(req) {{
          var url = req.url.split('?')[0];
          // Let Vite serve its own assets and source files directly.
          if (url.startsWith('/@') || url.startsWith('/src/') ||
              url.startsWith('/node_modules/') || /\\.\\w+$/.test(url)) {{
            return url;
          }}
          // HTML-accepting requests (browser navigation) → SPA shell.
          if (req.headers.accept && req.headers.accept.includes('text/html')) {{
            return '/index.html';
          }}
          // Everything else (fetch/axios API calls) → proxy to backend.
        }}
      }}
    }}
  }}
}});
"""


def _inject_cra_proxy(sb_frontend: Path, spring_port: int) -> str | None:
    """
    Inject or rewrite the CRA proxy field in package.json so the webpack dev server
    forwards all non-asset requests to the backend Docker service.
    The simple string form proxies everything CRA dev server doesn't serve as a
    static file — HTML navigation requests are still served as index.html by CRA.
    Returns a warning string if the proxy was injected (not already present), else None.
    """
    pkg = sb_frontend / "package.json"
    if not pkg.exists():
        return None
    try:
        data = json.loads(pkg.read_text(errors="ignore"))
    except Exception:
        return None
    target = f"http://backend:{spring_port}"
    if "proxy" in data:
        if data["proxy"] != target:
            data["proxy"] = target
            pkg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return None
    data["proxy"] = target
    pkg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return (
        "CRA proxy injected in package.json — all non-asset requests are forwarded "
        f"to the backend container ({target}). "
        "The submission lacked a proxy configuration for the development build."
    )


def _write_vite_sandbox_config(sb_frontend: Path, spring_port: int) -> str | None:
    """
    Write vite.sandbox.config.js into the sandbox frontend directory.
    Vite is invoked with --config vite.sandbox.config.js (see _FRONTEND_DOCKERFILE_VITE).
    The sidecar imports the submission's own vite.config (any format — object literal
    or function form, .ts/.js/.mjs) and merges in a catch-all preview proxy.
    Using a sidecar + mergeConfig avoids any regex rewriting of the original config,
    which silently fails for the common defineConfig(({ mode }) => ({...})) pattern.
    Returns a warning string when written, else None (no vite.config found).
    """
    if not any(
        (sb_frontend / n).exists()
        for n in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.cjs")
    ):
        return None
    target = f"http://backend:{spring_port}"
    (sb_frontend / "vite.sandbox.config.js").write_text(
        _VITE_SANDBOX_CONFIG.format(target=target), encoding="utf-8"
    )
    return (
        "Sandbox accommodation (not a submission defect): vite.sandbox.config.js written — "
        "the submission's vite.config is wrapped with a preview proxy so the browser's API "
        "calls reach the backend container while we crawl the production build via `vite preview`. "
        "Real deployments serve the built SPA behind a reverse proxy, same-origin from the "
        "backend, or via absolute API URLs — none of which use Vite's preview proxy — so its "
        "absence is normal and does not indicate a defect."
    )


# ---------------------------------------------------------------------------
# Docker Compose generation
# ---------------------------------------------------------------------------

def _db_service_block(db_type: str) -> str:
    if db_type == "mysql":
        return (
            "  db:\n"
            "    image: mysql:8\n"
            "    environment:\n"
            "      MYSQL_ROOT_PASSWORD: sandbox\n"
            "      MYSQL_DATABASE: appdb\n"
            "      MYSQL_USER: app\n"
            "      MYSQL_PASSWORD: sandbox\n"
            "    healthcheck:\n"
            "      test: [\"CMD\", \"mysqladmin\", \"ping\", \"-h\", \"localhost\", \"-uroot\", \"-psandbox\"]\n"
            "      interval: 5s\n"
            "      timeout: 5s\n"
            "      retries: 20\n"
            "      start_period: 30s\n"
        )
    if db_type == "mariadb":
        return (
            "  db:\n"
            "    image: mariadb:lts\n"
            "    environment:\n"
            "      MARIADB_ROOT_PASSWORD: sandbox\n"
            "      MARIADB_DATABASE: appdb\n"
            "      MARIADB_USER: app\n"
            "      MARIADB_PASSWORD: sandbox\n"
            "    healthcheck:\n"
            "      test: [\"CMD\", \"healthcheck.sh\", \"--connect\", \"--innodb_initialized\"]\n"
            "      interval: 5s\n"
            "      timeout: 5s\n"
            "      retries: 20\n"
            "      start_period: 30s\n"
        )
    if db_type == "postgresql":
        return (
            "  db:\n"
            "    image: postgres:16-alpine\n"
            "    environment:\n"
            "      POSTGRES_DB: appdb\n"
            "      POSTGRES_USER: app\n"
            "      POSTGRES_PASSWORD: sandbox\n"
            "    healthcheck:\n"
            "      test: [\"CMD-SHELL\", \"pg_isready -U app -d appdb\"]\n"
            "      interval: 5s\n"
            "      timeout: 5s\n"
            "      retries: 10\n"
            "      start_period: 10s\n"
        )
    return ""


def _backend_env_block(
    profile: str | None,
    has_h2: bool,
    db_type: str | None,
    extra_env: dict[str, str],
) -> str:
    lines: list[str] = []

    if profile:
        lines.append(f"      SPRING_PROFILES_ACTIVE: {profile}")

    if db_type == "mysql":
        lines += [
            "      SPRING_DATASOURCE_URL: 'jdbc:mysql://db:3306/appdb?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC'",
            "      SPRING_DATASOURCE_USERNAME: app",
            "      SPRING_DATASOURCE_PASSWORD: sandbox",
            "      SPRING_DATASOURCE_DRIVER_CLASS_NAME: com.mysql.cj.jdbc.Driver",
            "      SPRING_JPA_DATABASE_PLATFORM: org.hibernate.dialect.MySQLDialect",
            "      SPRING_JPA_HIBERNATE_DDL_AUTO: create-drop",
        ]
    elif db_type == "mariadb":
        lines += [
            "      SPRING_DATASOURCE_URL: 'jdbc:mariadb://db:3306/appdb'",
            "      SPRING_DATASOURCE_USERNAME: app",
            "      SPRING_DATASOURCE_PASSWORD: sandbox",
            "      SPRING_DATASOURCE_DRIVER_CLASS_NAME: org.mariadb.jdbc.Driver",
            "      SPRING_JPA_DATABASE_PLATFORM: org.hibernate.dialect.MariaDBDialect",
            "      SPRING_JPA_HIBERNATE_DDL_AUTO: create-drop",
        ]
    elif db_type == "postgresql":
        lines += [
            "      SPRING_DATASOURCE_URL: 'jdbc:postgresql://db:5432/appdb'",
            "      SPRING_DATASOURCE_USERNAME: app",
            "      SPRING_DATASOURCE_PASSWORD: sandbox",
            "      SPRING_DATASOURCE_DRIVER_CLASS_NAME: org.postgresql.Driver",
            "      SPRING_JPA_DATABASE_PLATFORM: org.hibernate.dialect.PostgreSQLDialect",
            "      SPRING_JPA_HIBERNATE_DDL_AUTO: create-drop",
        ]
    elif has_h2:
        lines += [
            "      SPRING_DATASOURCE_URL: 'jdbc:h2:mem:testdb;DB_CLOSE_DELAY=-1'",
            "      SPRING_DATASOURCE_DRIVER_CLASS_NAME: org.h2.Driver",
            "      SPRING_JPA_DATABASE_PLATFORM: org.hibernate.dialect.H2Dialect",
            "      SPRING_JPA_HIBERNATE_DDL_AUTO: create-drop",
        ]
    else:
        lines.append("      SPRING_JPA_HIBERNATE_DDL_AUTO: create-drop")

    for k, v in extra_env.items():
        lines.append(f"      {k}: '{v}'")

    return "\n".join(lines)


def _compose_yaml(
    profile: str | None,
    has_h2: bool,
    db_type: str | None,
    extra_env: dict[str, str],
    spring_port: int = 8080,
    api_style: str = "unknown",
    hardcoded_api_port: int | None = None,
    env_var_names: list[str] | None = None,
) -> str:
    db_block      = _db_service_block(db_type) if db_type else ""
    env_block     = _backend_env_block(profile, has_h2, db_type, extra_env)
    depends_block = (
        "    depends_on:\n"
        "      db:\n"
        "        condition: service_healthy\n"
    ) if db_type else ""

    # Always expose BACKEND_HOST_PORT for health polling.
    # For hardcoded-URL style, also expose the port the browser actually calls.
    port_lines = [f'      - "{BACKEND_HOST_PORT}:{spring_port}"']
    if api_style == "hardcoded" and hardcoded_api_port and hardcoded_api_port != BACKEND_HOST_PORT:
        port_lines.append(f'      - "{hardcoded_api_port}:{spring_port}"')
    backend_ports = "\n".join(port_lines)

    # env_based: point at the frontend's own host port so browser API calls are same-origin.
    # The Vite/CRA proxy then forwards them to the backend container — Spring Boot CORS config
    # is never involved. Using "" breaks apps that do `VITE_API_URL || fallback_url` (empty
    # string is falsy → falls back to the hardcoded URL → cross-origin CORS fails again).
    api_url = (
        f"http://localhost:{FRONTEND_HOST_PORT}"
        if api_style == "env_based"
        else f"http://localhost:{BACKEND_HOST_PORT}"
    )

    # Build args: inject every env var name the app actually uses, plus safe fallbacks.
    # Hardcoded-style apps have had their origins stripped so they no longer need a URL
    # env var, but we inject anyway in case any conditional code references them.
    default_names = ["VITE_API_URL", "REACT_APP_API_URL", "NEXT_PUBLIC_API_URL"]
    all_names = sorted(set(default_names) | set(env_var_names or []))
    build_args = "\n".join(f"        - {n}={api_url}" for n in all_names)

    return (
        f"services:\n"
        f"{db_block}"
        f"  backend:\n"
        f"    build:\n"
        f"      context: ./backend\n"
        f"    ports:\n"
        f"{backend_ports}\n"
        f"{depends_block}"
        f"    environment:\n"
        f"{env_block}\n"
        f"  frontend:\n"
        f"    build:\n"
        f"      context: ./frontend\n"
        f"      args:\n"
        f"{build_args}\n"
        f"    ports:\n"
        f"      - \"{FRONTEND_HOST_PORT}:5174\"\n"
    )


# ---------------------------------------------------------------------------
# Health polling
# ---------------------------------------------------------------------------

def _poll_url(url: str, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with httpx.Client(verify=False, timeout=4) as client:
                r = client.get(url)
                if r.status_code < 500:
                    return True
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# Main sync entry point (wrapped in asyncio.to_thread by run())
# ---------------------------------------------------------------------------

def _teardown(compose_base: list, compose_file: Path, sandbox_dir: Path) -> None:
    if compose_file.exists():
        subprocess.run(
            compose_base + ["down", "--remove-orphans", "-v"],
            capture_output=True, timeout=TEARDOWN_TIMEOUT_S,
            cwd=str(sandbox_dir),
        )


def teardown(job_id: str) -> None:
    """Stop and remove containers for a given job. Called by the /sandbox/stop endpoint."""
    sandbox_dir  = (Path(__file__).parent.parent / "jobs" / job_id / "sandbox").resolve()
    compose_file = sandbox_dir / "docker-compose.yml"
    project_name = f"dsta-{job_id.replace('-', '')[:12]}"
    compose_base = ["docker", "compose", "-f", str(compose_file), "--project-name", project_name]
    _teardown(compose_base, compose_file, sandbox_dir)


def _run_sandbox_sync(job_id: str, extract_to: Path, project_context: dict) -> dict:
    # Pre-check Docker before doing anything else
    docker_err = _check_docker_available()
    if docker_err:
        return {"boot_status": "boot_failed", "error": docker_err}

    root = _unwrap_root(extract_to.resolve())
    backend_src, frontend_src, frontend_type = _find_dirs(root)

    if not backend_src:
        return {"boot_status": "boot_failed", "error": "Could not locate Spring Boot backend directory (no pom.xml or build.gradle found)"}
    if not frontend_src:
        return {"boot_status": "boot_failed", "error": "Could not locate frontend directory (no package.json with dev/start script found)"}

    # Detect ports, API call style, and env var names from the original source (before copy)
    spring_port            = _detect_spring_port(backend_src)
    detected_frontend_port = _detect_frontend_port(frontend_src, frontend_type)  # informational
    api_style, hardcoded_api_port = _detect_api_call_style(frontend_src)
    env_var_names          = _scan_env_var_names(frontend_src)

    # Port pre-checks with detected values
    ports_to_check = [BACKEND_HOST_PORT, FRONTEND_HOST_PORT]
    if api_style == "hardcoded" and hardcoded_api_port and hardcoded_api_port != BACKEND_HOST_PORT:
        ports_to_check.append(hardcoded_api_port)
    busy_ports = [p for p in ports_to_check if _port_in_use(p)]
    if busy_ports:
        return {
            "boot_status": "boot_failed",
            "error": f"Port(s) already in use: {busy_ports}. Stop any other running sandbox first.",
        }

    # Absolute path anchored to this file's parent (backend/)
    sandbox_dir = (Path(__file__).parent.parent / "jobs" / job_id / "sandbox").resolve()
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    profile    = _detect_spring_profile(backend_src)
    has_h2     = _has_h2_dep(backend_src)
    db_type    = _detect_db_type(backend_src)
    build_tool = _detect_build_tool(backend_src)
    extra_env  = _detect_spring_extra_env(backend_src)

    # Merge placeholder dummies first, then let extra_env overwrite its known keys
    placeholder_env = _detect_property_placeholders(backend_src)
    extra_env = {**placeholder_env, **extra_env}

    # Copy source into sandbox (strips build artefacts and node_modules)
    sb_backend  = sandbox_dir / "backend"
    sb_frontend = sandbox_dir / "frontend"
    for p in (sb_backend, sb_frontend):
        if p.exists():
            shutil.rmtree(p)
    shutil.copytree(backend_src,  sb_backend,  ignore=_COPY_IGNORE)
    shutil.copytree(frontend_src, sb_frontend, ignore=_COPY_IGNORE)

    # Apply source patches and collect warnings for each one that fires
    sandbox_warnings: list[str] = []
    if placeholder_env:
        names = sorted(placeholder_env)
        sandbox_warnings.append(
            f"application.properties has {len(names)} unresolved placeholder(s) "
            f"({', '.join(names[:6])}{'…' if len(names) > 6 else ''}): "
            f"injected sandbox dummy values so the app can start. "
            f"Features using these credentials (OAuth2, external APIs, mail) will not function."
        )

    if api_style == "env_based":
        sandbox_warnings.append(
            f"Frontend uses environment-based API URLs (VITE_* / REACT_APP_* / NEXT_PUBLIC_*). "
            f"Build args set to http://localhost:{FRONTEND_HOST_PORT} (sandbox frontend port) "
            f"so API calls are same-origin from the browser — the proxy routes them to the "
            f"backend container without CORS involvement. "
            f"The submission's API URL is not portable without build-time environment configuration."
        )

    if api_style == "hardcoded" and hardcoded_api_port:
        w = _strip_hardcoded_origin(sb_frontend, hardcoded_api_port)
        if w: sandbox_warnings.append(w)

    # For Vite: write a sidecar config that uses mergeConfig() to add the preview
    # proxy regardless of the original vite.config format (object or function form).
    # A sidecar avoids regex rewriting of the original config, which silently fails
    # for the common defineConfig(({ mode }) => ({...})) pattern.
    w = _write_vite_sandbox_config(sb_frontend, spring_port)
    if w: sandbox_warnings.append(w)

    if frontend_type == "cra":
        w = _inject_cra_proxy(sb_frontend, spring_port)
        if w: sandbox_warnings.append(w)

    w = _patch_tailwind_css(sb_frontend)
    if w: sandbox_warnings.append(w)

    (sb_backend  / "Dockerfile").write_text(
        _BACKEND_DOCKERFILE_MAVEN if build_tool == "maven" else _BACKEND_DOCKERFILE_GRADLE
    )
    (sb_frontend / "Dockerfile").write_text(_frontend_dockerfile(frontend_type))

    compose_file = sandbox_dir / "docker-compose.yml"
    compose_file.write_text(_compose_yaml(
        profile, has_h2, db_type, extra_env,
        spring_port=spring_port,
        api_style=api_style,
        hardcoded_api_port=hardcoded_api_port,
        env_var_names=env_var_names,
    ))

    # Unique project name per job — prevents cross-job container collisions
    project_name = f"dsta-{job_id.replace('-', '')[:12]}"
    compose_base = ["docker", "compose", "-f", str(compose_file), "--project-name", project_name]

    try:
        # Pre-run cleanup — evicts leftover containers from a previous crashed run
        subprocess.run(
            compose_base + ["down", "--remove-orphans", "-v"],
            capture_output=True, timeout=TEARDOWN_TIMEOUT_S,
            cwd=str(sandbox_dir),
        )

        # Build images
        t0 = time.time()
        build = subprocess.run(
            compose_base + ["build"],
            capture_output=True, text=True,
            timeout=BUILD_TIMEOUT_S,
            cwd=str(sandbox_dir),
        )
        build_time_s = round(time.time() - t0, 1)

        if build.returncode != 0:
            return {
                "boot_status":         "boot_failed",
                "error":               f"Docker build failed:\n{build.stderr[-3000:]}",
                "spring_profile_used": profile,
                "h2_dep_found":        has_h2,
                "db_type":             db_type,
                "build_tool":          build_tool,
                "frontend_type":       frontend_type,
                "spring_port":         spring_port,
                "api_style":           api_style,
                "build_time_s":        build_time_s,
                "sandbox_warnings":    sandbox_warnings,
            }

        # Start containers
        t_boot = time.time()
        up = subprocess.run(
            compose_base + ["up", "-d"],
            capture_output=True, text=True,
            timeout=60,
            cwd=str(sandbox_dir),
        )
        if up.returncode != 0:
            return {
                "boot_status":      "boot_failed",
                "error":            f"docker compose up failed:\n{up.stderr[-2000:]}",
                "build_tool":       build_tool,
                "frontend_type":    frontend_type,
                "spring_port":      spring_port,
                "api_style":        api_style,
                "build_time_s":     build_time_s,
                "sandbox_warnings": sandbox_warnings,
            }

        backend_url  = f"http://localhost:{BACKEND_HOST_PORT}"
        frontend_url = f"http://localhost:{FRONTEND_HOST_PORT}"

        backend_ok  = _poll_url(backend_url,  BOOT_TIMEOUT_S)
        frontend_ok = _poll_url(frontend_url, FRONTEND_BOOT_TIMEOUT_S)
        boot_time_s = round(time.time() - t_boot, 1)

        if backend_ok and frontend_ok:
            boot_status = "success"
        elif backend_ok or frontend_ok:
            boot_status = "partial"
        else:
            boot_status = "boot_failed"

        return {
            "boot_status":         boot_status,
            "backend_url":         backend_url  if backend_ok  else None,
            "frontend_url":        frontend_url if frontend_ok else None,
            "backend_accessible":  backend_ok,
            "frontend_accessible": frontend_ok,
            "spring_profile_used": profile,
            "h2_dep_found":        has_h2,
            "db_type":             db_type,
            "build_tool":          build_tool,
            "frontend_type":       frontend_type,
            "spring_port":         spring_port,
            "api_style":           api_style,
            "build_time_s":        build_time_s,
            "boot_time_s":         boot_time_s,
            "test_results":        [],
            "sandbox_warnings":    sandbox_warnings,
            "error":               None,
        }

    except subprocess.TimeoutExpired:
        _teardown(compose_base, compose_file, sandbox_dir)
        return {
            "boot_status":      "boot_failed",
            "error":            f"Docker build timed out after {BUILD_TIMEOUT_S}s — Maven dependency download may need a longer timeout",
            "build_tool":       build_tool,
            "frontend_type":    frontend_type,
            "spring_port":      spring_port,
            "api_style":        api_style,
            "test_results":     [],
            "sandbox_warnings": sandbox_warnings,
        }
    except Exception as exc:
        _teardown(compose_base, compose_file, sandbox_dir)
        return {"boot_status": "boot_failed", "error": str(exc), "test_results": [], "sandbox_warnings": sandbox_warnings}


async def run(job_id: str, extract_to: Path, project_context: dict) -> dict:
    return await asyncio.to_thread(_run_sandbox_sync, job_id, extract_to, project_context)
