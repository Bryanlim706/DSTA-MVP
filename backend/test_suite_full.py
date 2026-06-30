#!/usr/bin/env python3
"""
Full Requirements Pipeline Test Suite — 5 projects × 2 variants

Projects:
  P1  Employee Management FS   (full_stack_web_app, Spring Boot + React + Vite, auth + filters)
  P2  Ecommerce                (full_stack_web_app, Spring Boot + React + Vite, product CRUD)
  P3  Todometer                (electron_app, Electron + React, todo list)
  P4  React Shopping Cart      (frontend_only, React/CRA, cart + filter)
  P5  Employee CRUD            (full_stack_web_app, Spring Boot + React JS, basic CRUD)

Variants per project:
  B  req box = subset of README features
  C  req box = subset + extra PASSABLE requirements (Steps 1-3 should output them)
              + JUNK requirements (Steps 1-3 must NOT output them)

Usage:
    cd backend && python test_suite_full.py

Output:
    test_suite_full_results_<ts>.json   raw step output
    test_suite_full_report_<ts>.md      analysis report
"""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import step1_req_extractor, step2_obvious_generator, step3_implied_generator

load_dotenv()

UPLOADS = Path(__file__).parent / "uploads"


# ─── data models ──────────────────────────────────────────────────────────────

@dataclass
class GTItem:
    description: str
    keyword_groups: list[list[str]]
    should_appear: bool = True  # False = must NOT appear in output
    note: str = ""


@dataclass
class Project:
    key: str
    name: str
    project_type: str
    extract_to: Path
    step0: dict
    must_appear: list[GTItem]    # readme features that MUST be extracted
    junk_items: list[GTItem]     # requirements that must NOT appear
    passable_extras: list[GTItem]  # extra-passable items (should appear in Variant C)
    variant_b_text: str          # req box for variant B
    variant_c_text: str          # req box for variant C (B subset + extras + junk)


# ─── ground-truth matching ─────────────────────────────────────────────────────

_STOP = {"user", "can", "with", "from", "that", "this", "have", "been",
         "will", "would", "their", "into", "onto", "they", "when", "each"}

_SYSTEM_ACTOR = [
    "system must", "app must", "system will", "application must",
    "all requests", "is automatically", "are automatically",
    "app performs", "system performs", "server must", "api must",
    "backend must", "auto-reset", "auto reset", "automatically reset",
    "automatically generated", "are sent", "are included",
]
_NON_INVOKABLE = [
    "responsive layout", "responsive grid", "grid layout",
    "pagination controls", "loading indicator", "error message when",
    "success message", "tooltip", "placeholder", "visual indicator",
]


def _match(req: dict, gt: GTItem) -> bool:
    desc = req.get("description", "").lower()
    for group in gt.keyword_groups:
        if all(kw.lower() in desc for kw in group):
            return True
    return False


def _auto_errors(req: dict) -> list[str]:
    errs: list[str] = []
    desc = req.get("description", "").lower()
    if any(t in desc for t in _SYSTEM_ACTOR):
        errs.append("SYSTEM_ACTOR")
    parts = re.split(r"\band\b", desc)
    verbs = r"\b(add|create|edit|delete|remove|update|view|read|log in|log out|register|upload|download|filter|search|sort|configure|access|navigate|submit|checkout|pay)\b"
    if sum(bool(re.search(verbs, p)) for p in parts) >= 2:
        errs.append("COMPOUND")
    if any(t in desc for t in _NON_INVOKABLE):
        errs.append("NON_INVOKABLE")
    return errs


def _junk_leak(reqs: list[dict], junk_items: list[GTItem]) -> list[tuple[dict, str]]:
    leaks = []
    for r in reqs:
        for j in junk_items:
            if _match(r, j):
                leaks.append((r, j.description))
    return leaks


def _passable_found(reqs: list[dict], extras: list[GTItem]) -> tuple[list[GTItem], list[GTItem]]:
    found, missing = [], []
    for e in extras:
        if any(_match(r, e) for r in reqs):
            found.append(e)
        else:
            missing.append(e)
    return found, missing


# ─── project definitions ──────────────────────────────────────────────────────

PROJECTS: list[Project] = [

    # ── P1: Full-Stack Employee Management (Spring Boot + React + Vite) ─────────
    # Features: auth, CRUD employee, file upload, filters (name/ID/login/DOB/dept), pagination
    Project(
        key="P1_emp_mgmt_fs",
        name="P1 Employee Management (Full-Stack, Auth+Filters)",
        project_type="full_stack_web_app",
        extract_to=UPLOADS / "da7e71ab-c365-4485-ba49-c13951b256e1" / "extracted",
        step0={
            "project_type": "full_stack_web_app",
            "frontend_framework": "React",
            "frontend_tooling": "Vite",
            "backend_framework": "Spring Boot",
            "template_engine": None,
            "service_layout": "separate_frontend_backend",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Spring Boot backend + React/Vite frontend with auth",
            "test_strategy": {"primary": "Playwright", "secondary": "JUnit/MockMvc"},
            "config_files_found": ["pom.xml", "package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": [],
        },
        must_appear=[
            GTItem("User can authenticate / log in",
                   [["log in"], ["authenticate"], ["login", "password"], ["login", "credential"]]),
            GTItem("User can add / create an employee",
                   [["add", "employee"], ["create", "employee"]]),
            GTItem("User can view the employee list",
                   [["view", "employee"], ["list", "employee"], ["employee", "list"]]),
            GTItem("User can update / edit an employee",
                   [["update", "employee"], ["edit", "employee"]]),
            GTItem("User can delete an employee",
                   [["delete", "employee"], ["remove", "employee"]]),
            GTItem("User can upload an employee resume (PDF)",
                   [["upload", "resume"], ["upload", "pdf"]]),
            GTItem("User can filter employees by name",
                   [["filter", "name"], ["search", "name"], ["filter", "employee", "name"]]),
            GTItem("User can filter employees by Employee ID",
                   [["filter", "employee id"], ["filter", "id"], ["search", "id"]]),
            GTItem("User can filter employees by Login ID",
                   [["filter", "login id"], ["filter", "login"]]),
            GTItem("User can filter employees by Date of Birth",
                   [["filter", "date of birth"], ["filter", "dob"], ["filter", "birth"]]),
            GTItem("User can filter employees by Department",
                   [["filter", "department"], ["search", "department"]]),
        ],
        junk_items=[
            GTItem("User can launch a satellite into orbit",
                   [["satellite"], ["orbit"]], should_appear=False,
                   note="nonsensical requirement"),
            GTItem("User can order pizza from the employee portal",
                   [["order pizza"], ["pizza"]], should_appear=False,
                   note="nonsensical requirement"),
        ],
        passable_extras=[
            GTItem("User can view paginated employee results",
                   [["paginated"], ["pagination"], ["page", "result"]]),
            GTItem("User can log out",
                   [["log out"], ["logout"], ["sign out"]]),
            GTItem("User can manage their profile or account",
                   [["profile"], ["account", "manage"], ["account setting"]]),
        ],
        variant_b_text=(
            "User can add new employees.\n"
            "User can view the employee list.\n"
            "User can delete an employee."
        ),
        variant_c_text=(
            "User can add new employees.\n"
            "User can view the employee list.\n"
            "User can delete an employee.\n"
            # extra passable — in README, Step 1 should pick up from README + req box
            "User can update existing employee records.\n"
            "User can upload a PDF resume for each employee.\n"
            # extra passable — domain-standard, Step 3 INF should generate
            "User can reset their password.\n"
            "User can export the employee list to a file.\n"
            # junk — must NOT appear
            "User can launch a satellite into orbit.\n"
            "User can order pizza from the employee portal."
        ),
    ),

    # ── P2: Ecommerce (Spring Boot + React + Vite, product CRUD) ─────────────────
    # README features: list products, view product by ID, add product, update product, delete product
    Project(
        key="P2_ecommerce",
        name="P2 Ecommerce (Full-Stack, Product CRUD)",
        project_type="full_stack_web_app",
        extract_to=UPLOADS / "db3920bc-6b39-4b2c-b391-6c523447f96a" / "extracted",
        step0={
            "project_type": "full_stack_web_app",
            "frontend_framework": "React",
            "frontend_tooling": "Vite",
            "backend_framework": "Spring Boot",
            "template_engine": None,
            "service_layout": "separate_frontend_backend",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Spring Boot + React/Vite ecommerce with product CRUD",
            "test_strategy": {"primary": "Playwright", "secondary": "JUnit/MockMvc"},
            "config_files_found": ["pom.xml", "package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": ["AddProduct.jsx", "ProductList.jsx", "UpdateProduct.jsx"],
        },
        must_appear=[
            GTItem("User can view all products",
                   [["view", "product"], ["list", "product"], ["product", "list"], ["fetch", "product"]]),
            GTItem("User can view a specific product by ID",
                   [["view", "product", "id"], ["product", "detail"], ["product by id"]]),
            GTItem("User can add a new product",
                   [["add", "product"], ["create", "product"]]),
            GTItem("User can update a product",
                   [["update", "product"], ["edit", "product"]]),
            GTItem("User can delete a product",
                   [["delete", "product"], ["remove", "product"]]),
        ],
        junk_items=[
            GTItem("User can travel through time using the product page",
                   [["travel through time"], ["time travel"]], should_appear=False,
                   note="nonsensical requirement"),
            GTItem("User can talk to houseplants via the app",
                   [["houseplant"], ["talk to plant"]], should_appear=False,
                   note="nonsensical requirement"),
        ],
        passable_extras=[
            GTItem("User can search or filter products",
                   [["search", "product"], ["filter", "product"]]),
            GTItem("User can add a product to a shopping cart",
                   [["cart"], ["add to cart"], ["shopping cart"]]),
            GTItem("User can manage product categories",
                   [["categor"], ["product categor"]]),
        ],
        variant_b_text=(
            "User can view all products.\n"
            "User can add a new product."
        ),
        variant_c_text=(
            "User can view all products.\n"
            "User can add a new product.\n"
            # extra passable — in README, Step 1 picks from req box
            "User can update an existing product.\n"
            "User can delete a product.\n"
            # extra passable — domain-inferred, Step 3 should generate
            "User can search products by name.\n"
            "User can add a product to a shopping cart.\n"
            # junk
            "User can travel through time using the product page.\n"
            "User can talk to houseplants via the app."
        ),
    ),

    # ── P3: Todometer (Electron + React) ────────────────────────────────────────
    # Features: add/complete/pause/delete items, drag-drop reorder, drag-drop between groups,
    #           settings (notifications, vault, display, API/MCP), web clipper, protocol handler
    Project(
        key="P3_todometer",
        name="P3 Todometer (Electron + React)",
        project_type="electron_app",
        extract_to=UPLOADS / "011e850a-fa43-485f-9d90-953886d03927" / "extracted",
        step0={
            "project_type": "electron_app",
            "frontend_framework": "React",
            "frontend_tooling": "Webpack",
            "backend_framework": "Electron",
            "template_engine": None,
            "service_layout": "single_project",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Electron + React todometer app",
            "test_strategy": {"primary": "Playwright", "secondary": None},
            "config_files_found": ["package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": [],
            "runtime": "Electron",
        },
        must_appear=[
            GTItem("User can add to-do items",
                   [["add", "todo"], ["add", "task"], ["add to-do"], ["add todos"]]),
            GTItem("User can complete to-do items",
                   [["complete", "todo"], ["complete", "task"], ["mark", "complete"]]),
            GTItem("User can pause to-do items",
                   [["pause", "todo"], ["pause", "task"]]),
            GTItem("User can delete to-do items",
                   [["delete", "todo"], ["delete", "task"], ["remove", "todo"]]),
            GTItem("User can drag and drop to reorder items",
                   [["drag", "reorder"], ["drag and drop", "reorder"], ["drag", "drop", "reorder"]]),
            GTItem("User can move items between groups via drag and drop",
                   [["drag", "group"], ["move", "group"], ["drag and drop", "group"]]),
            GTItem("User can configure notification preferences",
                   [["notification", "configure"], ["notification", "preference"],
                    ["notification", "setting"]]),
            GTItem("User can configure data vault location",
                   [["vault"], ["data vault"]]),
            GTItem("User can configure display options",
                   [["display", "option"], ["display option"], ["show", "hide", "button"]]),
            GTItem("User can add todos via protocol handler URL",
                   [["protocol handler"], ["todometer://"], ["protocol"]]),
        ],
        junk_items=[
            GTItem("User can breed virtual pets inside todometer",
                   [["virtual pet"], ["breed pet"]], should_appear=False,
                   note="nonsensical requirement"),
            GTItem("User can order food delivery from the todo app",
                   [["food delivery"], ["order food"]], should_appear=False,
                   note="nonsensical requirement"),
        ],
        passable_extras=[
            GTItem("User can add todos via web clipper",
                   [["web clipper"], ["clipper"]]),
            GTItem("User can control todometer via local REST API or MCP",
                   [["rest api"], ["mcp"], ["local api"]]),
            GTItem("User can create or manage task groups",
                   [["group"], ["task group"], ["create group"]]),
        ],
        variant_b_text=(
            "User can add to-do items.\n"
            "User can delete to-do items.\n"
            "User can complete to-do items."
        ),
        variant_c_text=(
            "User can add to-do items.\n"
            "User can delete to-do items.\n"
            "User can complete to-do items.\n"
            # extra passable — in README, Step 1 picks from req box
            "User can pause to-do items.\n"
            "User can configure notification settings.\n"
            "User can configure data vault location.\n"
            # extra passable — domain-inferred, Step 3 should generate
            "User can create and manage task groups or categories.\n"
            "User can set task priority level.\n"
            # junk
            "User can breed virtual pets inside todometer.\n"
            "User can order food delivery from the todo app."
        ),
    ),

    # ── P4: React Shopping Cart (frontend-only) ──────────────────────────────────
    # Features: add products to cart, remove products from cart, filter by size
    Project(
        key="P4_react_cart",
        name="P4 React Shopping Cart (frontend-only)",
        project_type="frontend_only",
        extract_to=UPLOADS / "40b7c631-e2a7-4e6c-8fdd-e66e2e58aabb" / "extracted",
        step0={
            "project_type": "frontend_only",
            "frontend_framework": "React",
            "frontend_tooling": "Create React App",
            "backend_framework": None,
            "template_engine": None,
            "service_layout": "single_project",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "React SPA shopping cart, no backend",
            "test_strategy": {"primary": "Playwright", "secondary": None},
            "config_files_found": ["package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": [],
        },
        must_appear=[
            GTItem("User can add products to the cart",
                   [["add", "cart"], ["add", "product", "cart"]]),
            GTItem("User can remove products from the cart",
                   [["remove", "cart"], ["remove", "product"], ["remove", "item"]]),
            GTItem("User can filter products by size",
                   [["filter", "size"], ["filter", "product", "size"]]),
        ],
        junk_items=[
            GTItem("User can book a flight through the shopping cart",
                   [["book", "flight"], ["flight booking"]], should_appear=False,
                   note="nonsensical requirement"),
            GTItem("User can perform open-heart surgery in the app",
                   [["surgery"], ["heart surgery"]], should_appear=False,
                   note="nonsensical requirement"),
        ],
        passable_extras=[
            GTItem("User can view the total price or cart summary",
                   [["total price"], ["cart total"], ["total"], ["summary", "cart"], ["price", "cart"]]),
            GTItem("User can view an empty cart state",
                   [["empty cart"], ["cart", "empty"]]),
            GTItem("User can proceed to checkout",
                   [["checkout"], ["proceed", "checkout"]]),
        ],
        variant_b_text=(
            "User can add products to the shopping cart."
        ),
        variant_c_text=(
            "User can add products to the shopping cart.\n"
            # extra passable — in README, Step 1 picks from req box
            "User can remove products from the cart.\n"
            "User can filter products by available size.\n"
            # extra passable — domain-inferred, Step 3 should generate
            "User can view the total price of items in the cart.\n"
            "User can proceed to checkout.\n"
            # junk
            "User can book a flight through the shopping cart.\n"
            "User can perform open-heart surgery in the app."
        ),
    ),

    # ── P5: Employee CRUD (EMS — Spring Boot + React JS) ─────────────────────────
    # Features: add employee (firstname/lastname/email), view all employees, edit employee, delete employee
    Project(
        key="P5_emp_crud",
        name="P5 Employee CRUD App (Spring Boot + React JS)",
        project_type="full_stack_web_app",
        extract_to=UPLOADS / "0ae75930-4dd0-4f0b-aee7-d35a3fe10ce1" / "extracted",
        step0={
            "project_type": "full_stack_web_app",
            "frontend_framework": "React",
            "frontend_tooling": "Create React App",
            "backend_framework": "Spring Boot",
            "template_engine": None,
            "service_layout": "separate_frontend_backend",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Spring Boot + React JS basic employee CRUD",
            "test_strategy": {"primary": "Playwright", "secondary": "JUnit/MockMvc"},
            "config_files_found": ["pom.xml", "package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": [],
        },
        must_appear=[
            GTItem("User can add a new employee",
                   [["add", "employee"], ["create", "employee"]]),
            GTItem("User can view the employee list",
                   [["view", "employee"], ["list", "employee"], ["employee", "list"]]),
            GTItem("User can edit / update an employee",
                   [["edit", "employee"], ["update", "employee"]]),
            GTItem("User can delete an employee",
                   [["delete", "employee"], ["remove", "employee"]]),
        ],
        junk_items=[
            GTItem("User can launch a rocket ship from the employee dashboard",
                   [["launch", "rocket"], ["rocket ship"]], should_appear=False,
                   note="nonsensical requirement"),
            GTItem("User can grow mushrooms using the employee database",
                   [["grow mushroom"], ["mushroom"]], should_appear=False,
                   note="nonsensical requirement"),
        ],
        passable_extras=[
            GTItem("User can search employees by name or email",
                   [["search", "employee"], ["search", "name"], ["search", "email"]]),
            GTItem("User can view employee details",
                   [["view", "detail"], ["employee detail"], ["view employee", "detail"]]),
            GTItem("User can manage their account or profile",
                   [["profile"], ["account"], ["account setting"]]),
        ],
        variant_b_text=(
            "User can add employees.\n"
            "User can view the employee list."
        ),
        variant_c_text=(
            "User can add employees.\n"
            "User can view the employee list.\n"
            # extra passable — in README, Step 1 picks from req box
            "User can edit employee information.\n"
            "User can delete an employee record.\n"
            # extra passable — domain-inferred, Step 3 should generate
            "User can search employees by name.\n"
            "User can view detailed employee information.\n"
            # junk
            "User can launch a rocket ship from the employee dashboard.\n"
            "User can grow mushrooms using the employee database."
        ),
    ),
]


# ─── runner ───────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    project_key: str
    project_name: str
    variant: str   # "B" or "C"
    requirements_text: str
    step1: dict
    step2: dict
    step3: dict
    all_reqs: list[dict] = field(default_factory=list)  # s1+s2+s3 combined
    error: Optional[str] = None


async def run_one(project: Project, variant: str, client) -> RunResult:
    req_text = project.variant_b_text if variant == "B" else project.variant_c_text
    use_box = bool(req_text.strip())
    label = f"{project.key} | Variant {variant}"
    print(f"  [{label}] Step1 ...", end="", flush=True)

    try:
        s1 = await step1_req_extractor.run(
            requirements_text=req_text,
            extract_to=project.extract_to,
            client=client,
            use_requirements_box=use_box,
            use_readme=True,
        )
    except Exception as exc:
        print(f"  FAILED (s1): {exc}")
        return RunResult(project.key, project.name, variant, req_text, {}, {}, {}, error=str(exc))

    print(f" {s1.get('total_count',0)}r", end="", flush=True)

    try:
        s2 = await step2_obvious_generator.run(
            s1.get("requirements", []),
            project.step0,
            client,
        )
    except Exception as exc:
        print(f"  FAILED (s2): {exc}")
        return RunResult(project.key, project.name, variant, req_text, s1, {}, {}, error=str(exc))

    print(f" +{s2.get('total_count',0)}o", end="", flush=True)

    try:
        s3 = await step3_implied_generator.run(
            s1.get("requirements", []),
            s2.get("requirements", []),
            project.step0,
            client,
            project_summary=s1.get("project_summary", ""),
        )
    except Exception as exc:
        print(f"  FAILED (s3): {exc}")
        return RunResult(project.key, project.name, variant, req_text, s1, s2, {}, error=str(exc))

    print(f" +{s3.get('total_count',0)}g  OK")

    all_reqs = (
        s1.get("requirements", []) +
        s2.get("requirements", []) +
        s3.get("requirements", [])
    )
    return RunResult(project.key, project.name, variant, req_text, s1, s2, s3, all_reqs)


# ─── analysis ─────────────────────────────────────────────────────────────────

@dataclass
class Analysis:
    run: RunResult
    project: Project

    # Step 1 recall
    s1_matched: list[GTItem]
    s1_missed: list[GTItem]

    # Combined (s1+s2+s3) coverage
    all_matched: list[GTItem]
    all_missed: list[GTItem]

    # Junk leakage
    junk_leaked: list[tuple[dict, str]]

    # Passable extras (Variant C only)
    passable_found: list[GTItem]
    passable_missing: list[GTItem]

    # Auto-detected structural errors
    auto_errors: list[tuple[dict, list[str]]]


def analyse(run: RunResult, project: Project) -> Analysis:
    s1_reqs = run.step1.get("requirements", [])
    all_reqs = run.all_reqs

    def matched_missed(reqs, items):
        matched, missed = [], []
        for gt in items:
            if any(_match(r, gt) for r in reqs):
                matched.append(gt)
            else:
                missed.append(gt)
        return matched, missed

    s1_m, s1_x = matched_missed(s1_reqs, project.must_appear)
    all_m, all_x = matched_missed(all_reqs, project.must_appear)
    junk = _junk_leak(all_reqs, project.junk_items)
    pf, pm = ([], [])
    if run.variant == "C":
        pf, pm = _passable_found(all_reqs, project.passable_extras)

    auto = []
    for r in all_reqs:
        errs = _auto_errors(r)
        if errs:
            auto.append((r, errs))

    return Analysis(run, project, s1_m, s1_x, all_m, all_x, junk, pf, pm, auto)


# ─── report ────────────────────────────────────────────────────────────────────

def render_report(all_analyses: list[Analysis], run_ts: str) -> str:
    lines: list[str] = []

    def h(level: int, text: str):
        lines.append(f"\n{'#' * level} {text}\n")

    def p(text: str):
        lines.append(text + "\n")

    def li(text: str, indent: int = 0):
        lines.append("  " * indent + f"- {text}\n")

    h(1, f"Full Pipeline Test Suite — {run_ts}")
    p("5 projects × 2 variants (B: subset, C: subset + extras + junk)")
    p("Columns: S1=Step1 extracted | S2=obvious | S3=generated | GT=must-appear matched | Junk=leaked junk items")

    # Summary table
    h(2, "Summary Table")
    lines.append("| Project | V | S1 | S2 | S3 | GT matched | Junk leaked | Passable found (C) | Auto-errors |\n")
    lines.append("|---------|---|----|----|----|-----------:|------------:|-------------------:|------------:|\n")
    for a in all_analyses:
        s1n = a.run.step1.get("total_count", "ERR")
        s2n = a.run.step2.get("total_count", "ERR")
        s3n = a.run.step3.get("total_count", "ERR")
        gt_frac = f"{len(a.all_matched)}/{len(a.project.must_appear)}"
        junk_n = len(a.junk_leaked)
        pass_str = f"{len(a.passable_found)}/{len(a.project.passable_extras)}" if a.run.variant == "C" else "—"
        lines.append(f"| {a.project.name[:40]} | {a.run.variant} | {s1n} | {s2n} | {s3n} | {gt_frac} | {junk_n} | {pass_str} | {len(a.auto_errors)} |\n")

    # Per-project detail
    grouped: dict[str, list[Analysis]] = {}
    for a in all_analyses:
        grouped.setdefault(a.project.key, []).append(a)

    for key, analyses in grouped.items():
        project = analyses[0].project
        h(2, project.name)
        p(f"**Project type:** {project.project_type}")
        p(f"**Must-appear GT items ({len(project.must_appear)}):**")
        for gt in project.must_appear:
            li(gt.description)

        for a in analyses:
            h(3, f"Variant {a.run.variant}")

            if a.run.error:
                p(f"**FAILED:** {a.run.error}")
                continue

            p(f"**Req box (first 200 chars):** `{a.run.requirements_text[:200].replace(chr(10), ' | ')}`")
            p(f"**Step1:** {a.run.step1.get('total_count',0)} | "
              f"**Step2:** {a.run.step2.get('total_count',0)} | "
              f"**Step3:** {a.run.step3.get('total_count',0)} | "
              f"**Total:** {len(a.run.all_reqs)}")
            p(f"**GT matched (combined):** {len(a.all_matched)}/{len(a.project.must_appear)}")
            p(f"**GT matched (Step 1 only):** {len(a.s1_matched)}/{len(a.project.must_appear)}")

            # Full extracted list
            p("\n**All extracted requirements (S1 / S2 / S3):**")
            for r in a.run.step1.get("requirements", []):
                tag = " [GT]" if any(_match(r, gt) for gt in project.must_appear) else ""
                err = _auto_errors(r)
                etag = f" [WARN:{'+'.join(err)}]" if err else ""
                li(f"`{r.get('req_id','?')}` (S1) {r.get('description','')}{tag}{etag}")
            for r in a.run.step2.get("requirements", []):
                li(f"`{r.get('req_id','?')}` (S2) {r.get('description','')}")
            for r in a.run.step3.get("requirements", []):
                li(f"`{r.get('req_id','?')}` (S3/{r.get('placement','?')}) {r.get('description','')}")

            # Missed
            if a.all_missed:
                p(f"\n**MISSED GT items ({len(a.all_missed)}) — not found in any step:**")
                for gt in a.all_missed:
                    li(f"**MISS:** {gt.description}", 1)

            # Junk leakage
            if a.junk_leaked:
                p(f"\n**JUNK LEAKED ({len(a.junk_leaked)}) — nonsense appeared in output:**")
                for r, jdesc in a.junk_leaked:
                    li(f"**JUNK_LEAK:** `{r.get('req_id')}` \"{r.get('description')}\" (matched junk: \"{jdesc}\")", 1)
            else:
                p("\n**Junk: none leaked** ✓")

            # Passable extras (Variant C only)
            if a.run.variant == "C":
                p(f"\n**Passable extras (Variant C — extra req-box items):**")
                for gt in a.passable_found:
                    li(f"✓ FOUND: {gt.description}", 1)
                for gt in a.passable_missing:
                    li(f"✗ MISSING: {gt.description}", 1)

            # Auto-detected errors
            if a.auto_errors:
                p(f"\n**Auto-detected structural errors ({len(a.auto_errors)}):**")
                for r, errs in a.auto_errors:
                    li(f"**{'+'.join(errs)}:** `{r.get('req_id')}` — {r.get('description')}", 1)

    # Cross-project error log
    h(2, "Cross-Project Error Log")
    lines.append("| Project | Var | Type | Req ID | Description |\n")
    lines.append("|---------|-----|------|--------|-------------|\n")
    for a in all_analyses:
        if a.run.error:
            lines.append(f"| {a.project.name[:30]} | {a.run.variant} | RUN_FAILED | — | {a.run.error[:80]} |\n")
            continue
        for gt in a.all_missed:
            lines.append(f"| {a.project.name[:30]} | {a.run.variant} | MISS | — | {gt.description} |\n")
        for r, jdesc in a.junk_leaked:
            lines.append(f"| {a.project.name[:30]} | {a.run.variant} | JUNK_LEAK | {r.get('req_id','')} | {r.get('description','')[:60]} |\n")
        for r, errs in a.auto_errors:
            for e in errs:
                lines.append(f"| {a.project.name[:30]} | {a.run.variant} | {e} | {r.get('req_id','')} | {r.get('description','')[:60]} |\n")

    # B→C comparison per project
    h(2, "Variant B vs C Comparison (same project)")
    for key, analyses in grouped.items():
        if len(analyses) < 2:
            continue
        ab = next((a for a in analyses if a.run.variant == "B"), None)
        ac = next((a for a in analyses if a.run.variant == "C"), None)
        if not ab or not ac:
            continue
        h(3, analyses[0].project.name)
        bgt = len(ab.all_matched)
        cgt = len(ac.all_matched)
        bs1 = ab.run.step1.get("total_count", 0)
        cs1 = ac.run.step1.get("total_count", 0)
        total_gt = len(analyses[0].project.must_appear)
        p(f"- GT matched: B={bgt}/{total_gt}  C={cgt}/{total_gt}  (delta: {cgt - bgt:+d})")
        p(f"- Step 1 extracted: B={bs1}  C={cs1}  (delta: {cs1 - bs1:+d})")
        p(f"- Junk leaked: B={len(ab.junk_leaked)}  C={len(ac.junk_leaked)}")
        if ac.passable_found or ac.passable_missing:
            p(f"- Passable extras found in C: {len(ac.passable_found)}/{len(ac.project.passable_extras)}")
            for gt in ac.passable_found:
                li(f"✓ {gt.description}", 1)
            for gt in ac.passable_missing:
                li(f"✗ {gt.description}", 1)

    return "".join(lines)


# ─── main ─────────────────────────────────────────────────────────────────────

async def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found")
        sys.exit(1)

    client = anthropic.AsyncAnthropic(api_key=api_key)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results: list[RunResult] = []
    all_analyses: list[Analysis] = []

    for project in PROJECTS:
        print(f"\n{'='*60}")
        print(f"Project: {project.name}")
        if not project.extract_to.exists():
            print(f"  SKIP: extract_to not found: {project.extract_to}")
            continue

        for variant in ("B", "C"):
            run = await run_one(project, variant, client)
            all_results.append(run)
            analysis = analyse(run, project)
            all_analyses.append(analysis)

    # Save raw JSON
    json_path = Path(__file__).parent / f"test_suite_full_results_{run_ts}.json"
    json_data = []
    for r in all_results:
        json_data.append({
            "project_key": r.project_key,
            "project_name": r.project_name,
            "variant": r.variant,
            "requirements_text": r.requirements_text,
            "step1": r.step1,
            "step2": r.step2,
            "step3": r.step3,
            "error": r.error,
        })
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRaw JSON: {json_path}")

    # Render report
    report = render_report(all_analyses, run_ts)
    report_path = Path(__file__).parent / f"test_suite_full_report_{run_ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report:   {report_path}")

    # Quick summary
    print("\n" + "=" * 70)
    print(f"{'Project':<42} {'V':2} {'S1':>4} {'S2':>4} {'S3':>4} {'GT':>7} {'Junk':>5}")
    print("-" * 70)
    for a in all_analyses:
        s1n = a.run.step1.get("total_count", "E")
        s2n = a.run.step2.get("total_count", "E")
        s3n = a.run.step3.get("total_count", "E")
        gt = f"{len(a.all_matched)}/{len(a.project.must_appear)}"
        jk = str(len(a.junk_leaked))
        print(f"{a.project.name[:42]:<42} {a.run.variant:2} {str(s1n):>4} {str(s2n):>4} {str(s3n):>4} {gt:>7} {jk:>5}")


if __name__ == "__main__":
    asyncio.run(main())
