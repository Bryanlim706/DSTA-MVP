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

# Vite — passes API URL as build arg (read by Vite dev server at runtime via
# import.meta.env.VITE_API_URL).
_FRONTEND_DOCKERFILE_VITE = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ARG VITE_API_URL=http://localhost:{BACKEND_HOST_PORT}
ENV VITE_API_URL=$VITE_API_URL
EXPOSE 5174
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5174"]
"""

# Create React App — PORT env var controls the CRA dev server port.
_FRONTEND_DOCKERFILE_CRA = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ENV PORT=5174
ENV HOST=0.0.0.0
ENV REACT_APP_API_URL=http://localhost:{BACKEND_HOST_PORT}
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
# client-accessible env vars.
_FRONTEND_DOCKERFILE_NEXTJS = f"""\
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline --strict-ssl=false
COPY . .
ENV PORT=5174
ENV HOSTNAME=0.0.0.0
ENV NEXT_PUBLIC_API_URL=http://localhost:{BACKEND_HOST_PORT}
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


# ---------------------------------------------------------------------------
# Vite proxy patching
# ---------------------------------------------------------------------------

# Matches backend-like localhost URLs in vite.config (ports 8xxx / 9xxx).
# Rewrites them to the Docker service hostname so proxy calls work inside
# the frontend container.
_PROXY_URL_RE = re.compile(r"http://localhost:([89]\d{3})")


def _patch_vite_config(sb_frontend: Path) -> None:
    """Replace localhost backend URLs in vite.config proxy with Docker service name."""
    for name in ("vite.config.js", "vite.config.ts", "vite.config.mjs", "vite.config.cjs"):
        cfg = sb_frontend / name
        if not cfg.exists():
            continue
        text = cfg.read_text(errors="ignore")
        patched = _PROXY_URL_RE.sub("http://backend:8080", text)
        if patched != text:
            cfg.write_text(patched, encoding="utf-8")
        break  # only one vite config file expected


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
) -> str:
    db_block      = _db_service_block(db_type) if db_type else ""
    env_block     = _backend_env_block(profile, has_h2, db_type, extra_env)
    depends_block = (
        "    depends_on:\n"
        "      db:\n"
        "        condition: service_healthy\n"
    ) if db_type else ""

    return (
        f"services:\n"
        f"{db_block}"
        f"  backend:\n"
        f"    build:\n"
        f"      context: ./backend\n"
        f"    ports:\n"
        f"      - \"{BACKEND_HOST_PORT}:8080\"\n"
        f"{depends_block}"
        f"    environment:\n"
        f"{env_block}\n"
        f"  frontend:\n"
        f"    build:\n"
        f"      context: ./frontend\n"
        f"      args:\n"
        f"        - VITE_API_URL=http://localhost:{BACKEND_HOST_PORT}\n"
        f"        - REACT_APP_API_URL=http://localhost:{BACKEND_HOST_PORT}\n"
        f"        - NEXT_PUBLIC_API_URL=http://localhost:{BACKEND_HOST_PORT}\n"
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
    # Pre-checks
    docker_err = _check_docker_available()
    if docker_err:
        return {"boot_status": "boot_failed", "error": docker_err}

    busy_ports = [p for p in (BACKEND_HOST_PORT, FRONTEND_HOST_PORT) if _port_in_use(p)]
    if busy_ports:
        return {
            "boot_status": "boot_failed",
            "error": f"Port(s) already in use: {busy_ports}. Stop any other running sandbox first.",
        }

    # Absolute path anchored to this file's parent (backend/)
    sandbox_dir = (Path(__file__).parent.parent / "jobs" / job_id / "sandbox").resolve()
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    root = _unwrap_root(extract_to.resolve())
    backend_src, frontend_src, frontend_type = _find_dirs(root)

    if not backend_src:
        return {"boot_status": "boot_failed", "error": "Could not locate Spring Boot backend directory (no pom.xml or build.gradle found)"}
    if not frontend_src:
        return {"boot_status": "boot_failed", "error": "Could not locate frontend directory (no package.json with dev/start script found)"}

    profile    = _detect_spring_profile(backend_src)
    has_h2     = _has_h2_dep(backend_src)
    db_type    = _detect_db_type(backend_src)
    build_tool = _detect_build_tool(backend_src)
    extra_env  = _detect_spring_extra_env(backend_src)

    # Copy source into sandbox (strips build artefacts and node_modules)
    sb_backend  = sandbox_dir / "backend"
    sb_frontend = sandbox_dir / "frontend"
    for p in (sb_backend, sb_frontend):
        if p.exists():
            shutil.rmtree(p)
    shutil.copytree(backend_src,  sb_backend,  ignore=_COPY_IGNORE)
    shutil.copytree(frontend_src, sb_frontend, ignore=_COPY_IGNORE)

    # Patch vite proxy targets so they resolve inside Docker
    _patch_vite_config(sb_frontend)

    (sb_backend  / "Dockerfile").write_text(
        _BACKEND_DOCKERFILE_MAVEN if build_tool == "maven" else _BACKEND_DOCKERFILE_GRADLE
    )
    (sb_frontend / "Dockerfile").write_text(_frontend_dockerfile(frontend_type))

    compose_file = sandbox_dir / "docker-compose.yml"
    compose_file.write_text(_compose_yaml(profile, has_h2, db_type, extra_env))

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
                "build_time_s":        build_time_s,
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
                "boot_status":   "boot_failed",
                "error":         f"docker compose up failed:\n{up.stderr[-2000:]}",
                "build_tool":    build_tool,
                "frontend_type": frontend_type,
                "build_time_s":  build_time_s,
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
            "build_time_s":        build_time_s,
            "boot_time_s":         boot_time_s,
            "test_results":        [],
            "error":               None,
        }

    except subprocess.TimeoutExpired:
        _teardown(compose_base, compose_file, sandbox_dir)
        return {
            "boot_status":   "boot_failed",
            "error":         f"Docker build timed out after {BUILD_TIMEOUT_S}s — Maven dependency download may need a longer timeout",
            "build_tool":    build_tool,
            "frontend_type": frontend_type,
        }
    except Exception as exc:
        _teardown(compose_base, compose_file, sandbox_dir)
        return {"boot_status": "boot_failed", "error": str(exc)}


async def run(job_id: str, extract_to: Path, project_context: dict) -> dict:
    return await asyncio.to_thread(_run_sandbox_sync, job_id, extract_to, project_context)
