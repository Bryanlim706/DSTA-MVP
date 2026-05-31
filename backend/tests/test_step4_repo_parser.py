"""
Fixture-based tests for step4_repo_parser.
Tests call module helpers directly — no LLM, no async needed.
Run with: pytest backend/tests/test_step4_repo_parser.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.step4_repo_parser import (
    _norm_path,
    _join,
    _detect_languages,
    _walk_files,
    _endpoints_python,
    _endpoints_django,
    _endpoints_express,
    _endpoints_spring,
    _extract_api_endpoints,
    _extract_frontend_routes,
    _extract_database_models,
    _find_test_files,
    _identify_important_files,
    _build_route_to_files,
    _build_implementation_units,
    _shallow_component_imports,
    _expand_with_shallow_imports,
)


def make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Path utilities
# ---------------------------------------------------------------------------

def test_norm_path_no_change():
    assert _norm_path("/foo") == "/foo"

def test_norm_path_adds_leading_slash():
    assert _norm_path("foo") == "/foo"

def test_norm_path_removes_trailing():
    assert _norm_path("/foo/") == "/foo"

def test_norm_path_root_preserved():
    assert _norm_path("/") == "/"

def test_norm_path_empty():
    assert _norm_path("") == "/"

def test_join_sub_with_slash():
    assert _join("/api", "/users") == "/api/users"

def test_join_sub_no_slash():
    assert _join("/api", "users") == "/api/users"

def test_join_empty_sub():
    assert _join("/api", "") == "/api"

def test_join_empty_base():
    assert _join("", "/users") == "/users"


# ---------------------------------------------------------------------------
# 2. Language detection
# ---------------------------------------------------------------------------

def test_detect_languages_python(tmp_path):
    files = [tmp_path / f"f{i}.py" for i in range(3)]
    assert _detect_languages(files) == ["Python"]

def test_detect_languages_mixed_sorted_by_count(tmp_path):
    files = (
        [tmp_path / f"f{i}.ts" for i in range(3)]
        + [tmp_path / "f.py", tmp_path / "f.java"]
    )
    result = _detect_languages(files)
    assert result[0] == "TypeScript"
    assert "Python" in result
    assert "Java" in result

def test_detect_languages_ignores_unknown_exts(tmp_path):
    files = [tmp_path / "README.md", tmp_path / "config.json", tmp_path / "ci.yml"]
    assert _detect_languages(files) == []

def test_detect_languages_empty():
    assert _detect_languages([]) == []


# ---------------------------------------------------------------------------
# 3. _walk_files + IGNORE_DIRS
# ---------------------------------------------------------------------------

def test_walk_files_basic(tmp_path):
    root = make_project(tmp_path, {
        "src/app.py": "# app",
        "src/utils.py": "# utils",
        "index.ts": "// ts",
    })
    files = _walk_files(root)
    names = {f.name for f in files}
    assert "app.py" in names
    assert "utils.py" in names
    assert "index.ts" in names

def test_walk_files_ignores_node_modules(tmp_path):
    root = make_project(tmp_path, {
        "src/app.js": "// app",
        "node_modules/lodash/index.js": "// lodash",
    })
    files = _walk_files(root)
    rel_strs = {str(f.relative_to(root)) for f in files}
    assert any("app.js" in s for s in rel_strs)
    assert not any("node_modules" in s for s in rel_strs)

def test_walk_files_ignores_build_dir(tmp_path):
    root = make_project(tmp_path, {
        "src/app.js": "// source",
        "build/output.js": "// compiled",
    })
    files = _walk_files(root)
    names = {f.name for f in files}
    assert "app.js" in names
    assert "output.js" not in names

def test_walk_files_ignores_nested_ignore(tmp_path):
    root = make_project(tmp_path, {
        "src/module.py": "# real",
        "src/__pycache__/module.pyc": "bytecode",
    })
    files = _walk_files(root)
    assert all("__pycache__" not in str(f) for f in files)


# ---------------------------------------------------------------------------
# 4. Python (Flask / FastAPI) endpoint extraction
# ---------------------------------------------------------------------------

def test_flask_get_decorator(tmp_path):
    root = make_project(tmp_path, {
        "app.py": (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "\n"
            "@app.get(\"/users\")\n"
            "def get_users():\n"
            "    pass\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_python(files, root)
    assert len(endpoints) == 1
    assert endpoints[0]["method"] == "GET"
    assert endpoints[0]["path"] == "/users"
    assert endpoints[0]["handler"] == "get_users"

def test_flask_route_with_methods(tmp_path):
    root = make_project(tmp_path, {
        "app.py": (
            "@app.route(\"/users\", methods=[\"GET\", \"POST\"])\n"
            "def users():\n"
            "    pass\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_python(files, root)
    pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/users") in pairs
    assert ("POST", "/users") in pairs

def test_fastapi_post(tmp_path):
    root = make_project(tmp_path, {
        "main.py": (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "\n"
            "@app.post(\"/items\")\n"
            "def create_item():\n"
            "    pass\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_python(files, root)
    assert any(e["method"] == "POST" and e["path"] == "/items" for e in endpoints)

def test_flask_bare_route_defaults_get(tmp_path):
    root = make_project(tmp_path, {
        "app.py": (
            "@app.route(\"/foo\")\n"
            "def foo():\n"
            "    pass\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_python(files, root)
    assert len(endpoints) == 1
    assert endpoints[0]["method"] == "GET"
    assert endpoints[0]["path"] == "/foo"

def test_endpoints_dedup(tmp_path):
    root = make_project(tmp_path, {
        "app.py": "@app.get(\"/users\")\ndef get_users(): pass\n",
        "views.py": "@app.get(\"/users\")\ndef get_users_view(): pass\n",
    })
    files = _walk_files(root)
    endpoints = _extract_api_endpoints(files, "flask", root)
    user_gets = [e for e in endpoints if e["method"] == "GET" and e["path"] == "/users"]
    assert len(user_gets) == 1


# ---------------------------------------------------------------------------
# 5. Django endpoint extraction
# ---------------------------------------------------------------------------

def test_django_urls_basic(tmp_path):
    root = make_project(tmp_path, {
        "myapp/urls.py": (
            "from django.urls import path\n"
            "from . import views\n"
            "urlpatterns = [\n"
            "    path('users/', views.UserList, name='user-list'),\n"
            "    path('users/<int:pk>/', views.UserDetail, name='user-detail'),\n"
            "]\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_django(files, root)
    paths = [e["path"] for e in endpoints]
    assert "/users" in paths
    assert "/users/<int:pk>" in paths

def test_django_skips_include(tmp_path):
    root = make_project(tmp_path, {
        "urls.py": (
            "urlpatterns = [\n"
            "    path('api/', include('myapp.urls')),\n"
            "    path('login/', views.login),\n"
            "]\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_django(files, root)
    paths = [e["path"] for e in endpoints]
    assert "/login" in paths
    assert "/api" not in paths

def test_django_ignores_non_urls_py(tmp_path):
    root = make_project(tmp_path, {
        "views.py": (
            "def user_list(request): pass\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_django(files, root)
    assert endpoints == []


# ---------------------------------------------------------------------------
# 6. Express / NestJS endpoint extraction
# ---------------------------------------------------------------------------

def test_express_basic(tmp_path):
    root = make_project(tmp_path, {
        "server.js": (
            "const app = require('express')();\n"
            "app.get('/users', (req, res) => res.json([]));\n"
            "app.post('/users', (req, res) => res.json({}));\n"
            "app.delete('/users/:id', (req, res) => res.json({}));\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_express(files, root, "express")
    pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/users") in pairs
    assert ("POST", "/users") in pairs
    assert ("DELETE", "/users/:id") in pairs

def test_nestjs_controller_with_base(tmp_path):
    root = make_project(tmp_path, {
        "users.controller.ts": (
            "@Controller('users')\n"
            "export class UsersController {\n"
            "  @Get('')\n"
            "  findAll() {}\n"
            "  @Post('')\n"
            "  create() {}\n"
            "  @Get(':id')\n"
            "  findOne() {}\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_express(files, root, "nestjs")
    pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/users") in pairs
    assert ("POST", "/users") in pairs
    assert ("GET", "/users/:id") in pairs

def test_nestjs_empty_controller_path(tmp_path):
    root = make_project(tmp_path, {
        "app.controller.ts": (
            "@Controller('')\n"
            "export class AppController {\n"
            "  @Get('health')\n"
            "  health() {}\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_express(files, root, "nestjs")
    assert any(e["method"] == "GET" and e["path"] == "/health" for e in endpoints)


# ---------------------------------------------------------------------------
# 7. Spring Boot endpoint extraction
# ---------------------------------------------------------------------------

def test_spring_java_get_post(tmp_path):
    root = make_project(tmp_path, {
        "UserController.java": (
            "import org.springframework.web.bind.annotation.*;\n"
            "@RestController\n"
            "public class UserController {\n"
            "    @GetMapping(\"/users\")\n"
            "    public List<User> getAll() { return null; }\n"
            "    @PostMapping(\"/users\")\n"
            "    public User create() { return null; }\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_spring(files, root)
    pairs = {(e["method"], e["path"]) for e in endpoints}
    handlers = {e["handler"] for e in endpoints}
    assert ("GET", "/users") in pairs
    assert ("POST", "/users") in pairs
    assert "getAll" in handlers
    assert "create" in handlers

def test_spring_java_request_mapping_base(tmp_path):
    root = make_project(tmp_path, {
        "UserController.java": (
            "import org.springframework.web.bind.annotation.*;\n"
            "@RestController\n"
            "@RequestMapping(\"/api/v1\")\n"
            "public class UserController {\n"
            "    @GetMapping(\"/users\")\n"
            "    public List<User> getAll() { return null; }\n"
            "    @DeleteMapping(\"/users/{id}\")\n"
            "    public void delete() {}\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_spring(files, root)
    pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/api/v1/users") in pairs
    assert ("DELETE", "/api/v1/users/{id}") in pairs

def test_spring_java_bare_getmapping(tmp_path):
    root = make_project(tmp_path, {
        "PingController.java": (
            "import org.springframework.web.bind.annotation.*;\n"
            "@RestController\n"
            "@RequestMapping(\"/ping\")\n"
            "public class PingController {\n"
            "    @GetMapping\n"
            "    public String ping() { return \"ok\"; }\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_spring(files, root)
    assert any(e["method"] == "GET" and e["path"] == "/ping" for e in endpoints)

def test_spring_kotlin_regex_fallback(tmp_path):
    root = make_project(tmp_path, {
        "UserController.kt": (
            "@RestController\n"
            "@RequestMapping(\"/api\")\n"
            "class UserController {\n"
            "    @GetMapping(\"/users\")\n"
            "    fun getAll() = listOf<Any>()\n"
            "    @PostMapping(\"/users\")\n"
            "    fun create() = Any()\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    endpoints = _endpoints_spring(files, root)
    pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/api/users") in pairs
    assert ("POST", "/api/users") in pairs


# ---------------------------------------------------------------------------
# 8. Frontend route extraction
# ---------------------------------------------------------------------------

def test_routes_nextjs_pages_dir(tmp_path):
    root = make_project(tmp_path, {
        "pages/index.tsx": "export default function Home() {}",
        "pages/about.tsx": "export default function About() {}",
        "pages/users/[id].tsx": "export default function User() {}",
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "next.js", root)
    assert "/" in routes
    assert "/about" in routes
    assert "/users/[id]" in routes

def test_routes_nextjs_pages_skips_underscore(tmp_path):
    root = make_project(tmp_path, {
        "pages/_app.tsx": "export default function App() {}",
        "pages/index.tsx": "export default function Home() {}",
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "next.js", root)
    assert routes == ["/"]

def test_routes_nextjs_app_router(tmp_path):
    root = make_project(tmp_path, {
        "app/page.tsx": "export default function Home() {}",
        "app/users/page.tsx": "export default function Users() {}",
        "app/users/[id]/page.tsx": "export default function User() {}",
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "next.js", root)
    assert "/" in routes
    assert "/users" in routes
    assert "/users/[id]" in routes

def test_routes_sveltekit(tmp_path):
    root = make_project(tmp_path, {
        "src/routes/+page.svelte": "<script></script>",
        "src/routes/about/+page.svelte": "<script></script>",
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "svelte", root)
    assert "/" in routes
    assert "/about" in routes

def test_routes_react_router_self_closing(tmp_path):
    root = make_project(tmp_path, {
        "src/App.tsx": (
            "import { Route, Routes } from 'react-router-dom';\n"
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            "      <Route path=\"/\" element={<Home />} />\n"
            "      <Route path=\"/about\" element={<About />} />\n"
            "      <Route path=\"/users/:id\" element={<User />} />\n"
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "react", root)
    assert "/" in routes
    assert "/about" in routes
    assert "/users/:id" in routes

def test_routes_react_router_open_element(tmp_path):
    root = make_project(tmp_path, {
        "src/App.tsx": (
            "import { Route, Routes } from 'react-router-dom';\n"
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            "      <Route path=\"/dashboard\">\n"
            "        <Route index element={<Dashboard />} />\n"
            "      </Route>\n"
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "react", root)
    assert "/dashboard" in routes

def test_routes_createbrowserrouter(tmp_path):
    root = make_project(tmp_path, {
        "src/router.tsx": (
            "import { createBrowserRouter } from 'react-router-dom';\n"
            "const router = createBrowserRouter([\n"
            "  { path: '/', element: <Home /> },\n"
            "  { path: '/settings', element: <Settings /> },\n"
            "]);\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "react", root)
    assert "/" in routes
    assert "/settings" in routes

def test_routes_vue_router(tmp_path):
    root = make_project(tmp_path, {
        "src/router/index.ts": (
            "const routes = [\n"
            "  { path: '/', component: Home },\n"
            "  { path: '/dashboard', component: Dashboard },\n"
            "  { path: '/users/:id', component: UserDetail },\n"
            "]\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "vue", root)
    assert "/" in routes
    assert "/dashboard" in routes
    assert "/users/:id" in routes

def test_routes_angular_routing_module(tmp_path):
    root = make_project(tmp_path, {
        "app/app-routing.module.ts": (
            "const routes: Routes = [\n"
            "  { path: '', component: HomeComponent },\n"
            "  { path: 'login', component: LoginComponent },\n"
            "];\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "angular", root)
    assert "/" in routes
    assert "/login" in routes

def test_routes_static_html_fallback(tmp_path):
    root = make_project(tmp_path, {
        "index.html": "<html><body>Home</body></html>",
        "about.html": "<html><body>About</body></html>",
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "", root)
    assert "/" in routes
    assert "/about" in routes

def test_routes_filters_wildcard_catchall(tmp_path):
    root = make_project(tmp_path, {
        "src/App.tsx": (
            "import { Route, Routes } from 'react-router-dom';\n"
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            "      <Route path=\"/\" element={<Home />} />\n"
            "      <Route path=\"/*\" element={<NotFound />} />\n"
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "react", root)
    assert "/" in routes
    assert "/*" not in routes


# ---------------------------------------------------------------------------
# 9. Database model extraction
# ---------------------------------------------------------------------------

def test_models_sqlalchemy(tmp_path):
    root = make_project(tmp_path, {
        "models.py": (
            "from sqlalchemy.orm import DeclarativeBase\n"
            "class Base(DeclarativeBase): pass\n"
            "class User(Base):\n"
            "    __tablename__ = 'users'\n"
            "class Post(Base):\n"
            "    __tablename__ = 'posts'\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "fastapi")
    assert "User" in models
    assert "Post" in models

def test_models_sqlalchemy_skips_abstract(tmp_path):
    root = make_project(tmp_path, {
        "models.py": (
            "class AbstractModel(Base):\n"
            "    __abstract__ = True\n"
            "class ConcreteModel(Base):\n"
            "    __tablename__ = 'concrete'\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "fastapi")
    assert "ConcreteModel" in models
    assert "AbstractModel" not in models

def test_models_django_orm(tmp_path):
    root = make_project(tmp_path, {
        "app/models.py": (
            "from django.db import models\n"
            "class Article(models.Model):\n"
            "    title = models.CharField(max_length=200)\n"
            "class Comment(models.Model):\n"
            "    body = models.TextField()\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "django")
    assert "Article" in models
    assert "Comment" in models

def test_models_jpa_entity(tmp_path):
    root = make_project(tmp_path, {
        "src/main/java/User.java": (
            "import javax.persistence.Entity;\n"
            "@Entity\n"
            "public class User {\n"
            "    private Long id;\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "spring boot")
    assert "User" in models

def test_models_prisma(tmp_path):
    root = make_project(tmp_path, {
        "prisma/schema.prisma": (
            "model User {\n"
            "  id    Int    @id\n"
            "  email String @unique\n"
            "}\n"
            "model Post {\n"
            "  id Int @id\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "express")
    assert "User" in models
    assert "Post" in models

def test_models_mongoose_js(tmp_path):
    root = make_project(tmp_path, {
        "models/User.js": (
            "const mongoose = require('mongoose');\n"
            "const userSchema = new mongoose.Schema({ name: String });\n"
            "const postSchema = new mongoose.Schema({ title: String });\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "express")
    assert "user" in models
    assert "post" in models

def test_models_typeorm_ts(tmp_path):
    root = make_project(tmp_path, {
        "entities/user.entity.ts": (
            "import { Entity, Column } from 'typeorm';\n"
            "@Entity()\n"
            "export class User {\n"
            "    id: number;\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    models = _extract_database_models(files, "nestjs")
    assert "User" in models


# ---------------------------------------------------------------------------
# 10. Test file detection
# ---------------------------------------------------------------------------

def test_find_tests_pytest_naming(tmp_path):
    root = make_project(tmp_path, {
        "tests/test_users.py": "def test_create(): pass",
        "tests/users_test.py": "def test_list(): pass",
    })
    files = _walk_files(root)
    result = _find_test_files(files, root)
    assert any("test_users.py" in r for r in result)
    assert any("users_test.py" in r for r in result)

def test_find_tests_jest_naming(tmp_path):
    root = make_project(tmp_path, {
        "src/users.test.ts": "describe('users', () => {})",
        "src/auth.spec.ts": "describe('auth', () => {})",
    })
    files = _walk_files(root)
    result = _find_test_files(files, root)
    assert any("users.test.ts" in r for r in result)
    assert any("auth.spec.ts" in r for r in result)

def test_find_tests_junit_naming(tmp_path):
    root = make_project(tmp_path, {
        "src/test/UserTest.java": "public class UserTest {}",
        "src/test/UserIT.java": "public class UserIT {}",
    })
    files = _walk_files(root)
    result = _find_test_files(files, root)
    assert any("UserTest.java" in r for r in result)
    assert any("UserIT.java" in r for r in result)

def test_find_tests_by_directory(tmp_path):
    root = make_project(tmp_path, {
        "__tests__/app.ts": "// test",
        "spec/helper.js": "// spec",
    })
    files = _walk_files(root)
    result = _find_test_files(files, root)
    assert any("app.ts" in r for r in result)
    assert any("helper.js" in r for r in result)

def test_find_tests_excludes_node_modules(tmp_path):
    root = make_project(tmp_path, {
        "src/app.test.ts": "// real test",
        "node_modules/jest-runner/test.js": "// internal",
    })
    files = _walk_files(root)
    result = _find_test_files(files, root)
    assert any("app.test.ts" in r for r in result)
    assert not any("node_modules" in r for r in result)


# ---------------------------------------------------------------------------
# 11. Important file detection
# ---------------------------------------------------------------------------

def test_important_entry_names(tmp_path):
    root = make_project(tmp_path, {
        "main.py": "from fastapi import FastAPI",
        "App.tsx": "export default function App() {}",
    })
    files = _walk_files(root)
    important = _identify_important_files(files, root, [])
    assert "main.py" in important
    assert "App.tsx" in important

def test_important_includes_endpoint_files(tmp_path):
    root = make_project(tmp_path, {
        "api/users.py": "# handlers",
        "api/auth.py": "# auth handlers",
    })
    files = _walk_files(root)
    endpoints = [
        {"method": "GET", "path": "/users", "file": "api/users.py", "handler": ""},
        {"method": "POST", "path": "/auth/login", "file": "api/auth.py", "handler": ""},
    ]
    important = _identify_important_files(files, root, endpoints)
    assert "api/users.py" in important
    assert "api/auth.py" in important

def test_important_router_config_in_router_dir(tmp_path):
    root = make_project(tmp_path, {
        "src/router/index.ts": "export const router = {}",
    })
    files = _walk_files(root)
    important = _identify_important_files(files, root, [])
    assert "src/router/index.ts" in important

def test_important_angular_routing_module(tmp_path):
    root = make_project(tmp_path, {
        "app/app-routing.module.ts": "const routes = []",
    })
    files = _walk_files(root)
    important = _identify_important_files(files, root, [])
    assert "app/app-routing.module.ts" in important

def test_important_capped_at_100(tmp_path):
    files_dict = {f"dir{i}/main.py": "# entry" for i in range(110)}
    root = make_project(tmp_path, files_dict)
    files = _walk_files(root)
    important = _identify_important_files(files, root, [])
    assert len(important) <= 100


# ---------------------------------------------------------------------------
# 12. _build_route_to_files
# ---------------------------------------------------------------------------

def test_route_to_files_nextjs_exact_mapping(tmp_path):
    root = make_project(tmp_path, {
        "pages/index.tsx": "export default function Home() {}",
        "pages/about.tsx": "export default function About() {}",
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "next.js", root, [], [])
    assert result.get("/") == ["pages/index.tsx"]
    assert result.get("/about") == ["pages/about.tsx"]

def test_route_to_files_sveltekit_exact_mapping(tmp_path):
    root = make_project(tmp_path, {
        "src/routes/+page.svelte": "<script></script>",
        "src/routes/about/+page.svelte": "<script></script>",
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "svelte", root, [], [])
    assert result.get("/") == ["src/routes/+page.svelte"]
    assert result.get("/about") == ["src/routes/about/+page.svelte"]

def test_route_to_files_react_router_maps_jsx_file(tmp_path):
    root = make_project(tmp_path, {
        "src/App.tsx": (
            "import { Route, Routes } from 'react-router-dom';\n"
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            "      <Route path=\"/dashboard\" element={<Dashboard />} />\n"
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "react", root, [], [])
    assert "src/App.tsx" in result.get("/dashboard", [])

def test_route_to_files_no_mapping_for_missing_route(tmp_path):
    """Routes with no backing file are absent from route_to_files after consolidation."""
    root = make_project(tmp_path, {
        "index.html": "<html/>",
        "about.html": "<html/>",
        "main.py": "# entry",
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "", root, [], [])
    assert "/" in result
    assert "/about" in result
    assert "/dashboard" not in result


# ---------------------------------------------------------------------------
# 13. _build_implementation_units
# ---------------------------------------------------------------------------

def test_impl_units_wraps_endpoints(tmp_path):
    root = make_project(tmp_path, {"placeholder.txt": ""})
    files = _walk_files(root)
    endpoints = [
        {"method": "GET", "path": "/users", "file": "api.py", "handler": "get_users"},
        {"method": "POST", "path": "/users", "file": "api.py", "handler": "create_user"},
    ]
    units = _build_implementation_units(endpoints, files, root)
    api_units = [u for u in units if u["kind"] == "api_endpoint"]
    assert len(api_units) == 2
    paths = {u["path"] for u in api_units}
    assert "/users" in paths
    handlers = {u["handler"] for u in api_units}
    assert "get_users" in handlers
    assert "create_user" in handlers

def test_impl_units_adds_form_handler(tmp_path):
    root = make_project(tmp_path, {
        "templates/login.html": (
            "<html><body>\n"
            "<form method=\"POST\" action=\"/login\">\n"
            "  <input type=\"text\" name=\"username\">\n"
            "  <button type=\"submit\">Login</button>\n"
            "</form>\n"
            "</body></html>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert len(form_units) == 1
    assert form_units[0]["method"] == "POST"
    assert form_units[0]["path"] == "/login"

def test_impl_units_excludes_get_form(tmp_path):
    root = make_project(tmp_path, {
        "templates/search.html": (
            "<form method=\"GET\" action=\"/search\">"
            "<input name=\"q\"></form>"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert form_units == []

def test_impl_units_deduplicates_forms(tmp_path):
    root = make_project(tmp_path, {
        "templates/page.html": (
            "<form method=\"POST\" action=\"/submit\">...</form>\n"
            "<form method=\"POST\" action=\"/submit\">...</form>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    submit_units = [u for u in units if u.get("path") == "/submit"]
    assert len(submit_units) == 1

def test_impl_units_blade_php_template(tmp_path):
    root = make_project(tmp_path, {
        "resources/views/create.blade.php": (
            "<form method=\"POST\" action=\"/items\">\n"
            "  @csrf\n"
            "  <button type=\"submit\">Create</button>\n"
            "</form>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert any(u["path"] == "/items" for u in form_units)


# ---------------------------------------------------------------------------
# 14. Spring Boot + React Vite integration scenario
# ---------------------------------------------------------------------------

def test_springboot_react_vite_full_parse(tmp_path):
    root = make_project(tmp_path, {
        # Backend — Spring Boot Java
        "src/main/java/com/example/UserController.java": (
            "import org.springframework.web.bind.annotation.*;\n"
            "@RestController\n"
            "@RequestMapping(\"/api/users\")\n"
            "public class UserController {\n"
            "    @GetMapping\n"
            "    public List<User> getAll() { return null; }\n"
            "    @PostMapping\n"
            "    public User create() { return null; }\n"
            "    @DeleteMapping(\"/{id}\")\n"
            "    public void delete() {}\n"
            "}\n"
        ),
        "src/main/java/com/example/User.java": (
            "import javax.persistence.Entity;\n"
            "@Entity\n"
            "public class User {\n"
            "    private Long id;\n"
            "    private String name;\n"
            "}\n"
        ),
        "pom.xml": (
            "<project><dependencies><dependency>"
            "<groupId>org.springframework.boot</groupId>"
            "<artifactId>spring-boot-starter-web</artifactId>"
            "</dependency></dependencies></project>"
        ),
        # Frontend — React + Vite
        "frontend/src/App.tsx": (
            "import { Route, Routes } from 'react-router-dom';\n"
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            "      <Route path=\"/\" element={<Home />} />\n"
            "      <Route path=\"/users\" element={<Users />} />\n"
            "      <Route path=\"/users/:id\" element={<UserDetail />} />\n"
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
        "frontend/src/pages/Home.tsx": "export default function Home() {}",
        "frontend/vite.config.ts": "import { defineConfig } from 'vite';",
        "frontend/package.json": (
            "{\"dependencies\":{\"react\":\"^18.0.0\"},"
            "\"devDependencies\":{\"vite\":\"^5.0.0\"}}"
        ),
    })

    files = _walk_files(root)

    # Languages
    languages = _detect_languages(files)
    assert "TypeScript" in languages
    assert "Java" in languages

    # API endpoints (Spring Boot)
    endpoints = _extract_api_endpoints(files, "spring boot", root)
    ep_pairs = {(e["method"], e["path"]) for e in endpoints}
    assert ("GET", "/api/users") in ep_pairs
    assert ("POST", "/api/users") in ep_pairs
    assert ("DELETE", "/api/users/{id}") in ep_pairs

    # Handlers captured
    handlers = {e["handler"] for e in endpoints if e["handler"]}
    assert "getAll" in handlers
    assert "create" in handlers

    # Frontend routes (React Router)
    routes = _extract_frontend_routes(files, "react", root)
    assert "/" in routes
    assert "/users" in routes
    assert "/users/:id" in routes

    # JPA model
    models = _extract_database_models(files, "spring boot")
    assert "User" in models

    # route_to_files: React Router JSX file maps the routes
    important = _identify_important_files(files, root, endpoints)
    rtf = _build_route_to_files(files, "react", root, endpoints, important)
    assert any("frontend/src/App.tsx" in (rtf.get(r) or []) for r in ["/users", "/users/:id", "/"])
    # No SSR templates → no HTML file paths in route_to_files
    all_mapped_files = {f for flist in rtf.values() for f in flist}
    assert not any(f.endswith(".html") for f in all_mapped_files)

    # implementation_units: only api_endpoint kind (no form_handlers — no HTML templates)
    impl_units = _build_implementation_units(endpoints, files, root)
    assert all(u["kind"] == "api_endpoint" for u in impl_units)
    assert len(impl_units) == 3


# ---------------------------------------------------------------------------
# 15. Flask SSR endpoint-based route fallback
# ---------------------------------------------------------------------------

def test_flask_ssr_routes_from_endpoints_not_html(tmp_path):
    """For Flask apps, frontend_routes should come from GET endpoint paths,
    not from HTML template filenames (which include layouts and partials)."""
    root = make_project(tmp_path, {
        "app.py": (
            "from flask import Flask, render_template\n"
            "app = Flask(__name__)\n"
            "@app.get('/')\n"
            "def index(): return render_template('home.html')\n"
            "@app.route('/login', methods=['GET', 'POST'])\n"
            "def login(): return render_template('login.html')\n"
            "@app.get('/logout')\n"
            "def logout(): return redirect('/')\n"
        ),
        "templates/home.html": "<html></html>",
        "templates/login.html": "<html></html>",
        "templates/layout.html": "<html></html>",    # partial — should NOT be a route
        "templates/macros.html": "<html></html>",    # partial — should NOT be a route
    })
    files = _walk_files(root)
    endpoints = _extract_api_endpoints(files, "flask", root)
    routes = _extract_frontend_routes(files, "", root, endpoints=endpoints)
    # Routes from GET endpoints
    assert "/" in routes
    assert "/login" in routes
    assert "/logout" in routes
    # Partial/layout templates must NOT appear as routes
    assert "/layout" not in routes
    assert "/macros" not in routes
    # home.html stem maps to /home — that should NOT appear (no /home GET endpoint)
    assert "/home" not in routes


def test_flask_ssr_root_route_present(tmp_path):
    """/ must appear even when the index template is named home.html (not index.html)."""
    root = make_project(tmp_path, {
        "app.py": (
            "@app.get('/')\n"
            "def index(): return render_template('home.html')\n"
        ),
        "templates/home.html": "<html></html>",
    })
    files = _walk_files(root)
    endpoints = _extract_api_endpoints(files, "flask", root)
    routes = _extract_frontend_routes(files, "", root, endpoints=endpoints)
    assert "/" in routes
    assert "/home" not in routes


# ---------------------------------------------------------------------------
# 16. React SPA / Electron: route_to_files adds App component
# ---------------------------------------------------------------------------

def test_route_to_files_spa_adds_app_component_from_important(tmp_path):
    """When route '/' maps only to an HTML shell, the App component from
    important_files must also be added so Step 5 reads real JSX source."""
    root = make_project(tmp_path, {
        "public/index.html": "<html><body><div id='root'></div></body></html>",
        "src/App.tsx": "export default function App() { return <div>hello</div>; }",
    })
    files = _walk_files(root)
    important = ["public/index.html", "src/App.tsx"]
    result = _build_route_to_files(files, "react", root, [], important)
    mapped = result.get("/", [])
    assert "src/App.tsx" in mapped


def test_route_to_files_spa_finds_app_component_from_walk(tmp_path):
    """App component found via file-walk when not in important_files."""
    root = make_project(tmp_path, {
        "public/index.html": "<html></html>",
        "src/App.jsx": "export default function App() {}",
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "react", root, [], ["public/index.html"])
    mapped = result.get("/", [])
    assert "src/App.jsx" in mapped


def test_route_to_files_spa_no_duplicate_app(tmp_path):
    """App.tsx added only once even if present in both important_files and file-walk."""
    root = make_project(tmp_path, {
        "public/index.html": "<html></html>",
        "src/App.tsx": "export default function App() {}",
    })
    files = _walk_files(root)
    important = ["public/index.html", "src/App.tsx"]
    result = _build_route_to_files(files, "react", root, [], important)
    assert result.get("/", []).count("src/App.tsx") == 1


# ---------------------------------------------------------------------------
# 17. Blade template expression paths filtered from form_handlers
# ---------------------------------------------------------------------------

def test_impl_units_blade_expression_path_is_none(tmp_path):
    """Blade template expressions like {{ route('x') }} cannot be resolved
    statically and must be stored as path=None, not as a literal string."""
    root = make_project(tmp_path, {
        "resources/views/form.blade.php": (
            "<form method='POST' action='{{ route(\"users.store\") }}'>\n"
            "  <input type='text' name='name'>\n"
            "</form>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert len(form_units) == 1
    assert form_units[0]["path"] is None   # expression, not a literal path


def test_impl_units_blade_url_helper_path_is_none(tmp_path):
    """{{ url('...') }} helper in action attribute → path=None."""
    root = make_project(tmp_path, {
        "resources/views/login.blade.php": (
            "<form method='POST' action='{{ url(\"/auth/login\") }}'></form>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert len(form_units) == 1
    assert form_units[0]["path"] is None


def test_impl_units_literal_blade_path_preserved(tmp_path):
    """Literal (non-template-expression) action paths in Blade files are kept."""
    root = make_project(tmp_path, {
        "resources/views/settings.blade.php": (
            "<form method='POST' action='/settings/save'></form>\n"
        ),
    })
    files = _walk_files(root)
    units = _build_implementation_units([], files, root)
    form_units = [u for u in units if u["kind"] == "form_handler"]
    assert len(form_units) == 1
    assert form_units[0]["path"] == "/settings/save"


# ---------------------------------------------------------------------------
# 18. assets/ directory excluded from route and file walk
# ---------------------------------------------------------------------------

def test_walk_files_ignores_assets_dir(tmp_path):
    """Files under assets/ must be excluded from _walk_files."""
    root = make_project(tmp_path, {
        "src/app.py": "# real source",
        "public/assets/js/chart/index.html": "<html>chart lib</html>",
        "public/assets/vendor/lib.js": "// third-party",
    })
    files = _walk_files(root)
    paths = [str(f) for f in files]
    assert any("app.py" in p for p in paths)
    assert not any("chart" in p for p in paths)
    assert not any("vendor" in p for p in paths)


def test_routes_html_fallback_ignores_assets(tmp_path):
    """HTML files inside assets/ must NOT appear in frontend_routes."""
    root = make_project(tmp_path, {
        "index.html": "<html></html>",                          # real entry
        "public/assets/js/chart/index.html": "<html></html>",  # library file
    })
    files = _walk_files(root)
    routes = _extract_frontend_routes(files, "", root)
    assert "/" in routes
    # The chart library html must not create a second '/' or any route
    assert routes.count("/") == 1


# ---------------------------------------------------------------------------
# 19. Shallow component import expansion for Step 5 static fallback
# ---------------------------------------------------------------------------

def test_shallow_component_imports_finds_local_jsx(tmp_path):
    """Local .jsx import in a page component is returned as a relative path."""
    root = make_project(tmp_path, {
        "src/pages/Login.tsx": (
            "import LoginForm from '../components/LoginForm';\n"
            "export default function Login() { return <LoginForm />; }\n"
        ),
        "src/components/LoginForm.jsx": (
            "export default function LoginForm() {\n"
            "  return <form><input type='text' /><button>Submit</button></form>;\n"
            "}\n"
        ),
    })
    results = _shallow_component_imports("src/pages/Login.tsx", root)
    assert "src/components/LoginForm.jsx" in results


def test_shallow_component_imports_skips_node_modules(tmp_path):
    """Imports from third-party packages (no leading '.') must not be included."""
    root = make_project(tmp_path, {
        "src/App.tsx": (
            "import React from 'react';\n"
            "import { Route } from 'react-router-dom';\n"
            "export default function App() {}\n"
        ),
    })
    results = _shallow_component_imports("src/App.tsx", root)
    assert results == []


def test_shallow_component_imports_skips_missing_files(tmp_path):
    """Imports that don't resolve to an existing file are silently skipped."""
    root = make_project(tmp_path, {
        "src/pages/Dashboard.tsx": (
            "import Chart from '../charts/Chart';\n"
            "export default function Dashboard() {}\n"
        ),
        # Chart.tsx intentionally absent
    })
    results = _shallow_component_imports("src/pages/Dashboard.tsx", root)
    assert results == []


def test_shallow_component_imports_resolves_tsx_and_jsx(tmp_path):
    """Both .tsx and .jsx child imports are resolved."""
    root = make_project(tmp_path, {
        "src/pages/Home.tsx": (
            "import HeroSection from '../components/HeroSection';\n"
            "import FooterBar from '../components/FooterBar';\n"
            "export default function Home() {}\n"
        ),
        "src/components/HeroSection.tsx": "export default function HeroSection() {}",
        "src/components/FooterBar.jsx": "export default function FooterBar() {}",
    })
    results = _shallow_component_imports("src/pages/Home.tsx", root)
    assert "src/components/HeroSection.tsx" in results
    assert "src/components/FooterBar.jsx" in results


def test_expand_with_shallow_imports_react_router(tmp_path):
    """For a React Router project, route_to_files must include child components
    imported by the page component, not just the page file itself."""
    root = make_project(tmp_path, {
        "src/App.tsx": (
            'import { Routes, Route } from "react-router-dom";\n'
            'import Login from "./screens/Login";\n'
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            '      <Route path="/login" element={<Login />} />\n'
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
        "src/screens/Login.tsx": (
            'import LoginForm from "../components/LoginForm";\n'
            "export default function Login() { return <LoginForm />; }\n"
        ),
        "src/components/LoginForm.tsx": (
            "export default function LoginForm() {\n"
            '  return <form><input type="text" name="username" />'
            '<button type="submit">Login</button></form>;\n'
            "}\n"
        ),
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "react", root, [], [])
    mapped = result.get("/login", [])
    # Router file + page component (existing behaviour)
    assert "src/App.tsx" in mapped
    assert "src/screens/Login.tsx" in mapped
    # Child component imported by Login.tsx (new behaviour)
    assert "src/components/LoginForm.tsx" in mapped


def test_expand_with_shallow_imports_no_duplicates(tmp_path):
    """A file already in the list via direct mapping is not added again."""
    root = make_project(tmp_path, {
        "src/App.tsx": (
            'import { Routes, Route } from "react-router-dom";\n'
            'import Home from "./screens/Home";\n'
            "export function App() {\n"
            "  return (\n"
            "    <Routes>\n"
            '      <Route path="/" element={<Home />} />\n'
            "    </Routes>\n"
            "  );\n"
            "}\n"
        ),
        "src/screens/Home.tsx": (
            # Home imports App.tsx itself (contrived circular-ish ref)
            'import App from "../App";\n'
            "export default function Home() {}\n"
        ),
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "react", root, [], [])
    mapped = result.get("/", [])
    assert mapped.count("src/App.tsx") == 1


def test_expand_with_shallow_imports_nextjs_page(tmp_path):
    """Next.js page file's child components are included via shallow expansion."""
    root = make_project(tmp_path, {
        "pages/dashboard.tsx": (
            'import StatsCard from "./StatsCard";\n'
            "export default function Dashboard() { return <StatsCard />; }\n"
        ),
        "pages/StatsCard.tsx": (
            "export default function StatsCard() { return <div><button>Refresh</button></div>; }\n"
        ),
    })
    files = _walk_files(root)
    result = _build_route_to_files(files, "next", root, [], [])
    mapped = result.get("/dashboard", [])
    assert "pages/dashboard.tsx" in mapped
    assert "pages/StatsCard.tsx" in mapped
