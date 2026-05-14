"""
Fixture-based tests for step0_classifier._classify_by_rules.
Tests call the synchronous helper directly — no Anthropic client needed.
Run with: pytest backend/tests/test_step0_classifier.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.step0_classifier import _classify_by_rules, _scan_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write files into tmp_path and return it as the project root."""
    for rel, content in files.items():
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return tmp_path


def classify(root: Path) -> dict:
    scan = _scan_project(root)
    result = _classify_by_rules(root, scan)
    assert result is not None, "Expected rule-based result but got None (LLM fallback triggered)"
    return result


# ---------------------------------------------------------------------------
# 1. Spring Boot + React + Vite — separate frontend/backend directories
# ---------------------------------------------------------------------------

def test_springboot_react_vite_split(tmp_path):
    root = make_project(tmp_path, {
        "frontend/package.json": json.dumps({
            "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
            "devDependencies": {"vite": "^5.0.0", "@vitejs/plugin-react": "^4.0.0"},
        }),
        "frontend/vite.config.ts": "import { defineConfig } from 'vite'",
        "frontend/src/App.tsx": "export default function App() { return <div/> }",
        "backend/pom.xml": (
            "<project><dependencies><dependency>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-web</artifactId>"
            "</dependency></dependencies></project>"
        ),
    })
    r = classify(root)
    assert r["project_type"] == "full_stack_web_app"
    assert r["frontend_framework"] == "React"
    assert r["frontend_tooling"] == "Vite"
    assert r["backend_framework"] == "Spring Boot"
    assert r["template_engine"] is None
    assert r["service_layout"] == "separate_frontend_backend"
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 2. Spring Boot + React + Vite — single root directory
# ---------------------------------------------------------------------------

def test_springboot_react_vite_root(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
            "devDependencies": {"vite": "^5.0.0"},
        }),
        "vite.config.ts": "import { defineConfig } from 'vite'",
        "src/main/java/App.java": "public class App {}",
        "src/App.tsx": "export default function App() { return <div/> }",
        "pom.xml": (
            "<project><dependencies><dependency>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-web</artifactId>"
            "</dependency></dependencies></project>"
        ),
    })
    r = classify(root)
    assert r["project_type"] == "full_stack_web_app"
    assert r["frontend_framework"] == "React"
    assert r["frontend_tooling"] == "Vite"
    assert r["backend_framework"] == "Spring Boot"
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 3. Spring Boot + Gradle KTS + React — must detect from build.gradle.kts
# ---------------------------------------------------------------------------

def test_springboot_gradle_kts_react(tmp_path):
    root = make_project(tmp_path, {
        "frontend/package.json": json.dumps({
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"vite": "^5.0.0"},
        }),
        "frontend/src/App.tsx": "export default function App() {}",
        "backend/build.gradle.kts": (
            "plugins { id(\"org.springframework.boot\") version \"3.2.0\" }\n"
            "dependencies { implementation(\"org.springframework.boot:spring-boot-starter-web\") }"
        ),
    })
    r = classify(root)
    assert r["project_type"] == "full_stack_web_app"
    assert r["backend_framework"] == "Spring Boot"
    assert r["frontend_framework"] == "React"
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 4. Spring Boot + Thymeleaf SSR — no package.json, must be deterministic
# ---------------------------------------------------------------------------

def test_springboot_thymeleaf_ssr(tmp_path):
    root = make_project(tmp_path, {
        "pom.xml": (
            "<project><dependencies><dependency>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-thymeleaf</artifactId>"
            "</dependency></dependencies></project>"
        ),
        "src/main/resources/templates/index.html": "<html><body>Hello</body></html>",
        "src/main/java/App.java": "public class App {}",
    })
    r = classify(root)
    assert r["project_type"] == "full_stack_web_app"
    assert r["backend_framework"] == "Spring Boot"
    assert r["frontend_framework"] is None
    assert r["template_engine"] == "Thymeleaf"
    assert r["service_layout"] == "single_project_ssr"
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 5. React + Vite only (no backend)
# ---------------------------------------------------------------------------

def test_react_vite_only(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
            "devDependencies": {"vite": "^5.0.0"},
        }),
        "vite.config.ts": "import { defineConfig } from 'vite'",
        "src/App.tsx": "export default function App() { return <div/> }",
    })
    r = classify(root)
    assert r["project_type"] == "frontend_only"
    assert r["frontend_framework"] == "React"
    assert r["frontend_tooling"] == "Vite"
    assert r["backend_framework"] is None
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 6. React dep only, no .jsx/.tsx source — confidence should be medium
# ---------------------------------------------------------------------------

def test_react_dep_only_no_source(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {"react": "^18.0.0"},
        }),
        "src/main.js": "// plain JS",
    })
    r = classify(root)
    assert r["project_type"] == "frontend_only"
    assert r["frontend_framework"] == "React"
    assert r["confidence"] == "medium"


# ---------------------------------------------------------------------------
# 7. Static HTML/CSS/JS site — no config files
# ---------------------------------------------------------------------------

def test_static_html_site(tmp_path):
    root = make_project(tmp_path, {
        "index.html": "<html><body>Hello</body></html>",
        "style.css": "body { margin: 0; }",
        "script.js": "console.log('hello')",
    })
    r = classify(root)
    assert r["project_type"] == "static_site"
    assert r["frontend_framework"] is None
    assert r["backend_framework"] is None
    assert r["confidence"] == "medium"


# ---------------------------------------------------------------------------
# 8. Electron + React + Vite
# ---------------------------------------------------------------------------

def test_electron_react(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "main": "main.js",
            "dependencies": {"electron": "^28.0.0", "react": "^18.0.0"},
            "devDependencies": {"vite": "^5.0.0"},
        }),
        "src/App.tsx": "export default function App() { return <div/> }",
    })
    r = classify(root)
    assert r["project_type"] == "electron_app"
    assert r["frontend_framework"] == "React"
    assert r["frontend_tooling"] == "Vite"
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 9. React Native / Expo — must be mobile_app, not frontend_only
# ---------------------------------------------------------------------------

def test_expo_mobile_app(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {
                "expo": "~50.0.0",
                "react": "18.2.0",
                "react-native": "0.73.0",
            },
        }),
        "App.tsx": "export default function App() { return null }",
    })
    r = classify(root)
    assert r["project_type"] == "mobile_app"
    assert r["frontend_framework"] == "Expo"
    assert r["backend_framework"] is None
    assert r["confidence"] == "high"


# ---------------------------------------------------------------------------
# 10. Express in devDependencies only — must NOT classify as backend_api_only
# ---------------------------------------------------------------------------

def test_express_devdep_only(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
            "devDependencies": {"express": "^4.18.0", "vite": "^5.0.0"},
        }),
        "src/App.tsx": "export default function App() { return <div/> }",
    })
    r = classify(root)
    # Express is devDep only — should be treated as a React frontend, not full_stack_js
    assert r["project_type"] == "frontend_only"
    assert r["frontend_framework"] == "React"
    assert r["backend_framework"] is None


# ---------------------------------------------------------------------------
# 11. Next.js with API routes — server_routes_detected = True
# ---------------------------------------------------------------------------

def test_nextjs_with_api_routes(tmp_path):
    root = make_project(tmp_path, {
        "package.json": json.dumps({
            "dependencies": {"next": "^14.0.0", "react": "^18.0.0"},
        }),
        "app/api/hello/route.ts": "export async function GET() {}",
        "app/page.tsx": "export default function Home() { return <div/> }",
    })
    r = classify(root)
    assert r["frontend_framework"] == "Next.js"
    assert r["server_routes_detected"] is True


# ---------------------------------------------------------------------------
# 12. Flask SSR with Jinja2 templates — full_stack_web_app
# ---------------------------------------------------------------------------

def test_flask_jinja2_ssr(tmp_path):
    root = make_project(tmp_path, {
        "requirements.txt": "flask==3.0.0\n",
        "templates/index.html": "<html><body>{{ name }}</body></html>",
        "app.py": "from flask import Flask; app = Flask(__name__)",
    })
    r = classify(root)
    assert r["project_type"] == "full_stack_web_app"
    assert r["backend_framework"] == "Flask"
    assert r["template_engine"] == "Jinja2"
    assert r["service_layout"] == "single_project_ssr"
    assert r["confidence"] == "high"
