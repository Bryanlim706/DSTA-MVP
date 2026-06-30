#!/usr/bin/env python3
"""
Requirements Extraction Test Suite

Tests step1_req_extractor.run() against 4 representative projects × 3 input variants.
Compares generated requirements against manually defined ground truth.

Error categories checked:
  OMISSION       — Ground truth requirement not extracted
  WRONG_REQ      — Generated requirement not in ground truth (hallucination)
  COMPOUND       — Two distinct user goals merged into one requirement description
  SYSTEM_ACTOR   — Subject is system/app, not user
  NON_INVOKABLE  — UI appearance detail, not independently user-invokable
  DUPLICATE      — Same requirement extracted twice

Projects:
  P1  Employee Management  (full_stack_web_app, Spring Boot + React)
  P2  Order Management     (full_stack_web_app, Spring Boot + React + JWT)
  P3  Attendance MS        (monorepo, Laravel + Android)
  P4  Todometer            (electron_app, Electron + React)

Variants per project:
  A  No requirements box — README only
  B  Subset of README requirements in req box + README
  C  Subset of README requirements + 2 extras NOT in README

Usage:
    cd backend && python test_req_suite.py

Output:
    req_test_report.md  (detailed findings)
"""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import anthropic

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import step1_req_extractor


# ─── ground truth types ──────────────────────────────────────────────────────

@dataclass
class GTReq:
    """Ground truth requirement with fuzzy-match keyword groups."""
    description: str
    # A match fires if ANY keyword_group is fully present in the generated description.
    # Each keyword_group is a list of strings that must ALL appear (case-insensitive).
    keyword_groups: list[list[str]]
    # Optional: if this GT item is something the LLM should NOT produce (system behavior etc.)
    should_not_extract: bool = False
    should_not_extract_reason: str = ""


@dataclass
class Variant:
    label: str           # "A", "B", "C"
    description: str
    requirements_text: str


@dataclass
class Project:
    name: str
    project_type: str
    extract_to: Path
    must_extract: list[GTReq]      # Requirements that MUST appear
    must_not_extract: list[GTReq]  # Requirements that should NOT appear
    variants: list[Variant]


# ─── auto-error detectors ─────────────────────────────────────────────────────

_SYSTEM_ACTOR_TRIGGERS = [
    "system must", "app must", "system will", "application must",
    "all requests", "is automatically", "are automatically",
    "app performs", "system performs", "server must", "api must",
    "backend must", "auto-reset", "auto reset", "automatically reset",
    "automatically generated", "are sent", "are included",
]

_NON_INVOKABLE_TRIGGERS = [
    "responsive layout", "responsive grid", "grid layout",
    "pagination controls", "paginated view", "display format",
    "loading indicator", "error message when", "success message",
    "tooltip", "placeholder", "visual indicator", "loading screen",
]


def auto_detect_errors(req: dict) -> list[str]:
    """Flag probable structural errors in a single generated requirement."""
    errors: list[str] = []
    desc = req.get("description", "").lower()

    if any(t in desc for t in _SYSTEM_ACTOR_TRIGGERS):
        errors.append("SYSTEM_ACTOR")

    # COMPOUND: "User can X and Y" where X and Y are distinct verbs
    action_verbs = r"\b(add|create|edit|delete|remove|update|view|read|log in|log out|register|upload|download|filter|search|sort|manage|configure|access|navigate|submit|cancel|approve|reject|assign|export|import)\b"
    parts = re.split(r"\band\b", desc)
    verb_matches = [bool(re.search(action_verbs, p)) for p in parts]
    if sum(verb_matches) >= 2:
        errors.append("COMPOUND")

    if any(t in desc for t in _NON_INVOKABLE_TRIGGERS):
        errors.append("NON_INVOKABLE")

    return errors


def find_duplicates(requirements: list[dict]) -> list[tuple[str, str, float]]:
    """Return (req_id_A, req_id_B, jaccard_score) for pairs with > 55% word overlap."""
    stop = {"user", "can", "with", "from", "that", "this", "have", "been",
            "will", "would", "their", "into", "onto", "they", "when", "each"}
    dupes: list[tuple[str, str, float]] = []

    def words(r):
        return set(re.findall(r"\b[a-z]{4,}\b", r.get("description", "").lower())) - stop

    for i in range(len(requirements)):
        wi = words(requirements[i])
        for j in range(i + 1, len(requirements)):
            wj = words(requirements[j])
            union = wi | wj
            if not union:
                continue
            jaccard = len(wi & wj) / len(union)
            if jaccard > 0.55:
                dupes.append((
                    requirements[i].get("req_id", f"#{i}"),
                    requirements[j].get("req_id", f"#{j}"),
                    round(jaccard, 2),
                ))
    return dupes


def match(req: dict, gt: GTReq) -> bool:
    """Return True if generated req satisfies any of the GT keyword groups."""
    desc = req.get("description", "").lower()
    for group in gt.keyword_groups:
        if all(kw.lower() in desc for kw in group):
            return True
    return False


def find_wrong_reqs(requirements: list[dict], must_extract: list[GTReq], must_not_extract: list[GTReq]) -> list[dict]:
    """Generated requirements not matching any must_extract item and not auto-errored = possible hallucination or missed classification."""
    wrong = []
    for req in requirements:
        matched_any = any(match(req, gt) for gt in must_extract)
        matched_wrong = any(match(req, gt) for gt in must_not_extract)
        auto_errors = auto_detect_errors(req)
        if not matched_any and not auto_errors:
            # Didn't match ground truth and no auto-flagged structural error — possible hallucination
            wrong.append(req)
    return wrong


# ─── project definitions ──────────────────────────────────────────────────────

UPLOADS = Path(__file__).parent / "uploads"

PROJECTS: list[Project] = [
    # ── P1: Employee Management ─────────────────────────────────────────────
    Project(
        name="P1 Employee Management",
        project_type="full_stack_web_app",
        extract_to=UPLOADS / "da7e71ab-c365-4485-ba49-c13951b256e1" / "extracted",
        must_extract=[
            GTReq("User can authenticate",
                  [["authenticate"], ["log in", "credential"], ["login", "password"]]),
            GTReq("User can create employee record",
                  [["create", "employee"], ["add", "employee"]]),
            GTReq("User can read / view employee records",
                  [["read", "employee"], ["view", "employee"], ["retrieve", "employee"]]),
            GTReq("User can update employee record",
                  [["update", "employee"], ["edit", "employee"]]),
            GTReq("User can delete employee record",
                  [["delete", "employee"], ["remove", "employee"]]),
            GTReq("User can upload resume in PDF",
                  [["upload", "resume"], ["upload", "pdf"]]),
            GTReq("User can filter employees by Name",
                  [["filter", "name"], ["search", "name"]]),
            GTReq("User can filter employees by Employee ID",
                  [["filter", "employee id"], ["filter", "id"]]),
            GTReq("User can filter employees by Login ID",
                  [["filter", "login id"], ["filter", "login"]]),
            GTReq("User can filter employees by Date of Birth range",
                  [["filter", "date of birth"], ["filter", "dob"], ["filter", "birth"]]),
            GTReq("User can filter employees by Department",
                  [["filter", "department"]]),
            GTReq("User can view paginated employee results",
                  [["paginated"], ["pagination"], ["page", "5"]]),
        ],
        must_not_extract=[
            GTReq("System auto-generates Employee ID (system behavior)",
                  [["auto-generated", "id"], ["auto generated", "id"],
                   ["automatically", "id"], ["generate", "employee id"]],
                  should_not_extract=True, should_not_extract_reason="SYSTEM_ACTOR"),
            GTReq("Responsive grid layout detail (non-invokable UI presentation)",
                  [["responsive grid"], ["grid layout"]],
                  should_not_extract=True, should_not_extract_reason="NON_INVOKABLE"),
        ],
        variants=[
            Variant("A", "No requirements box — README only", ""),
            Variant("B", "Subset of README requirements in req box + README",
                    "User can add employees. User can edit employees. User can upload employee resume in PDF format."),
            Variant("C", "Subset of README requirements + 2 extras NOT in README",
                    "User can add employees. User can edit employees. User can upload employee resume in PDF format.\nUser can export employee data to CSV.\nUser can sort employees by date added."),
        ],
    ),

    # ── P2: Order Management JWT ─────────────────────────────────────────────
    Project(
        name="P2 Order Management (JWT)",
        project_type="full_stack_web_app",
        extract_to=UPLOADS / "00fef7c9-75ee-4bb1-904e-2df7d05e9ddd" / "extracted",
        must_extract=[
            GTReq("User can authenticate with username and password",
                  [["authenticate"], ["log in", "password"], ["login"]]),
            GTReq("User can sign up / register a new account",
                  [["sign up"], ["signup"], ["register"]]),
            GTReq("User can create an order",
                  [["create", "order"]]),
            GTReq("User can retrieve a specific order",
                  [["retrieve", "order"], ["view", "order"]]),
            GTReq("Admin can retrieve all users",
                  [["retrieve", "users"], ["view", "all users"]]),
            GTReq("Admin can delete a user",
                  [["delete", "user"]]),
            GTReq("Admin can retrieve all orders",
                  [["retrieve", "orders"], ["view", "all orders"]]),
            GTReq("Admin can delete an order",
                  [["delete", "order"]]),
            GTReq("User can view number of users in system",
                  [["number", "users"], ["numberofusers"]]),
            GTReq("User can view number of orders in system",
                  [["number", "orders"], ["numberoforders"]]),
        ],
        must_not_extract=[
            GTReq("All requests include JWT token (system behavior, not user action)",
                  [["all requests"], ["jwt", "include"], ["jwt", "sent"], ["token", "requests"]],
                  should_not_extract=True, should_not_extract_reason="SYSTEM_ACTOR"),
            GTReq("Admin can access ALL secured endpoints (vague compound)",
                  [["all secured endpoints"], ["access all secured"]],
                  should_not_extract=True, should_not_extract_reason="COMPOUND/VAGUE"),
        ],
        variants=[
            Variant("A", "No requirements box — README only", ""),
            Variant("B", "Subset of README requirements in req box + README",
                    "Users can log in with username and password. Users can create orders. Admin can view all users."),
            Variant("C", "Subset of README requirements + 2 extras NOT in README",
                    "Users can log in with username and password. Users can create orders. Admin can view all users.\nUser can edit an existing order description.\nUser can filter orders by date range."),
        ],
    ),

    # ── P3: Attendance Management System (monorepo) ──────────────────────────
    Project(
        name="P3 Attendance MS (monorepo)",
        project_type="monorepo",
        extract_to=UPLOADS / "25580800-225a-45de-bc12-a96dc055644b" / "extracted",
        must_extract=[
            GTReq("User can access Welcome Page",
                  [["welcome"], ["welcome page"]]),
            GTReq("User can access Dashboard Page",
                  [["dashboard"]]),
            GTReq("User can access Take Attendance Page",
                  [["take attendance"], ["attendance", "take"]]),
            GTReq("User can access View Attendance Overview Page",
                  [["attendance", "overview"], ["view attendance overview"]]),
            GTReq("User can access View Attendance Page",
                  [["view attendance"], ["attendance", "view", "page"]]),
            GTReq("User (Android) can log in",
                  [["android", "log"], ["android", "login"]]),
            GTReq("User (Android) can access Home screen",
                  [["android", "home"]]),
            GTReq("User (Android) can access Dashboard",
                  [["android", "dashboard"]]),
            GTReq("User can take attendance offline",
                  [["offline"], ["offline", "attendance"]]),
        ],
        must_not_extract=[
            GTReq("Installation commands (not requirements)",
                  [["docker run"], ["artisan migrate"], ["composer install"]],
                  should_not_extract=True, should_not_extract_reason="INSTALL_CMD"),
        ],
        variants=[
            Variant("A", "No requirements box — README only", ""),
            Variant("B", "Subset of README requirements in req box + README",
                    "Users can take attendance. Users can view dashboard."),
            Variant("C", "Subset of README requirements + 2 extras NOT in README",
                    "Users can take attendance. Users can view dashboard.\nUser can add new students to the system.\nUser can generate attendance reports by class."),
        ],
    ),

    # ── P4: Todometer (electron_app) ─────────────────────────────────────────
    Project(
        name="P4 Todometer (electron_app)",
        project_type="electron_app",
        extract_to=UPLOADS / "011e850a-fa43-485f-9d90-953886d03927" / "extracted",
        must_extract=[
            GTReq("User can add to-do items",
                  [["add", "todo"], ["add", "task"], ["add to-do"], ["add todos"]]),
            GTReq("User can complete to-do items",
                  [["complete", "todo"], ["complete", "task"]]),
            GTReq("User can pause to-do items",
                  [["pause", "todo"], ["pause", "task"]]),
            GTReq("User can delete to-do items",
                  [["delete", "todo"], ["delete", "task"]]),
            GTReq("User can drag and drop to reorder items",
                  [["drag", "reorder"], ["drag and drop", "reorder"]]),
            GTReq("User can move items between groups via drag and drop",
                  [["drag", "group"], ["move", "group"]]),
            GTReq("User can configure notification preferences",
                  [["notification", "configure"], ["notification", "preference"],
                   ["notification", "setting"]]),
            GTReq("User can configure data vault location",
                  [["vault"], ["data vault"]]),
            GTReq("User can configure display options",
                  [["display", "option"], ["display option"], ["reset", "button", "display"],
                   ["show", "hide", "button"]]),
            GTReq("User can add todos via web clipper",
                  [["web clipper"], ["clipper"]]),
            GTReq("User can add todos via protocol handler URL",
                  [["protocol handler"], ["todometer://"], ["protocol"]]),
            GTReq("User can control todometer via local REST API",
                  [["rest api"], ["local api"], ["rest", "api"]]),
            GTReq("User can control todometer via MCP server",
                  [["mcp"]]),
        ],
        must_not_extract=[
            GTReq("Daily auto-reset is system behavior, not user action",
                  [["daily auto-reset"], ["daily auto reset"],
                   ["auto-reset", "daily"], ["auto reset", "tasks"]],
                  should_not_extract=True, should_not_extract_reason="SYSTEM_ACTOR"),
        ],
        variants=[
            Variant("A", "No requirements box — README only", ""),
            Variant("B", "Subset of README requirements in req box + README",
                    "User can add tasks. User can delete tasks. User can configure notification settings."),
            Variant("C", "Subset of README requirements + 2 extras NOT in README",
                    "User can add tasks. User can delete tasks. User can configure notification settings.\nUser can create task groups or categories.\nUser can set task priority level."),
        ],
    ),
]


# ─── runner ───────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    project_name: str
    variant_label: str
    variant_description: str
    requirements: list[dict]
    error: Optional[str]
    project_summary: str
    docs_used: list[str]


async def run_variant(project: Project, variant: Variant, client: anthropic.AsyncAnthropic) -> RunResult:
    print(f"  Running {project.name} | Variant {variant.label} ... ", end="", flush=True)
    result = None
    run_error = None
    try:
        result = await step1_req_extractor.run(
            requirements_text=variant.requirements_text,
            extract_to=project.extract_to,
            client=client,
            use_requirements_box=bool(variant.requirements_text.strip()),
            use_readme=True,
        )
    except Exception as exc:
        run_error = str(exc)

    if result is not None:
        reqs = result.get("requirements", [])
        print(f"OK  {len(reqs)} requirements")
        return RunResult(
            project_name=project.name,
            variant_label=variant.label,
            variant_description=variant.description,
            requirements=reqs,
            error=result.get("error"),
            project_summary=result.get("project_summary", ""),
            docs_used=result.get("docs_used", []),
        )
    else:
        print(f"FAILED  {run_error}")
        return RunResult(
            project_name=project.name,
            variant_label=variant.label,
            variant_description=variant.description,
            requirements=[],
            error=run_error,
            project_summary="",
            docs_used=[],
        )


# ─── analysis ─────────────────────────────────────────────────────────────────

@dataclass
class VariantAnalysis:
    run: RunResult
    matched: list[GTReq]            # GT items satisfied
    omitted: list[GTReq]            # GT items NOT found in output
    wrong_reqs: list[dict]          # Generated reqs with no GT match and no auto-error
    auto_errors: list[tuple[dict, list[str]]]   # (req, [error_category, ...])
    must_not_present: list[tuple[dict, str]]    # (req, reason) — must_not item appeared
    duplicates: list[tuple[str, str, float]]    # duplicate pairs
    extras_found: list[dict]        # Req-box extras that appeared in output (Variant C only)
    extras_not_found: list[str]     # Req-box extras NOT found in output (Variant C only)


# Keywords for the 2 extras in each Variant C req box
VARIANT_C_EXTRAS: dict[str, list[tuple[str, list[list[str]]]]] = {
    "P1 Employee Management": [
        ("User can export employee data to CSV",
         [["export", "csv"], ["export", "employee"]]),
        ("User can sort employees by date added",
         [["sort", "employee"], ["sort", "date"]]),
    ],
    "P2 Order Management (JWT)": [
        ("User can edit an existing order description",
         [["edit", "order"], ["update", "order", "description"]]),
        ("User can filter orders by date range",
         [["filter", "order", "date"], ["filter", "order", "range"]]),
    ],
    "P3 Attendance MS (monorepo)": [
        ("User can add new students to the system",
         [["add", "student"], ["new student"]]),
        ("User can generate attendance reports by class",
         [["generate", "report"], ["attendance", "report"]]),
    ],
    "P4 Todometer (electron_app)": [
        ("User can create task groups or categories",
         [["create", "group"], ["task group"], ["categor"]]),
        ("User can set task priority level",
         [["priority"], ["task priority"]]),
    ],
}


def analyse(run: RunResult, project: Project) -> VariantAnalysis:
    reqs = run.requirements

    matched: list[GTReq] = []
    omitted: list[GTReq] = []
    for gt in project.must_extract:
        if any(match(r, gt) for r in reqs):
            matched.append(gt)
        else:
            omitted.append(gt)

    auto_errors: list[tuple[dict, list[str]]] = []
    for r in reqs:
        errs = auto_detect_errors(r)
        if errs:
            auto_errors.append((r, errs))

    auto_errored_ids = {id(r) for r, _ in auto_errors}

    must_not_present: list[tuple[dict, str]] = []
    for gt in project.must_not_extract:
        for r in reqs:
            if match(r, gt):
                must_not_present.append((r, gt.should_not_extract_reason))

    wrong_reqs: list[dict] = []
    for r in reqs:
        is_gt_match = any(match(r, gt) for gt in project.must_extract)
        is_must_not = any(match(r, gt) for gt in project.must_not_extract)
        has_auto_err = bool(auto_detect_errors(r))
        if not is_gt_match and not is_must_not and not has_auto_err:
            wrong_reqs.append(r)

    duplicates = find_duplicates(reqs)

    extras_found: list[dict] = []
    extras_not_found: list[str] = []
    if run.variant_label == "C":
        extra_defs = VARIANT_C_EXTRAS.get(project.name, [])
        for extra_desc, extra_kwgroups in extra_defs:
            gt_extra = GTReq(extra_desc, extra_kwgroups)
            if any(match(r, gt_extra) for r in reqs):
                matching = [r for r in reqs if match(r, gt_extra)]
                extras_found.extend(matching)
            else:
                extras_not_found.append(extra_desc)

    return VariantAnalysis(
        run=run,
        matched=matched,
        omitted=omitted,
        wrong_reqs=wrong_reqs,
        auto_errors=auto_errors,
        must_not_present=must_not_present,
        duplicates=duplicates,
        extras_found=extras_found,
        extras_not_found=extras_not_found,
    )


# ─── report rendering ─────────────────────────────────────────────────────────

def render_report(all_analyses: list[tuple[Project, list[VariantAnalysis]]]) -> str:
    lines: list[str] = []

    def h(level: int, text: str):
        lines.append(f"\n{'#' * level} {text}\n")

    def p(text: str):
        lines.append(text + "\n")

    def li(text: str, indent: int = 0):
        lines.append("  " * indent + f"- {text}\n")

    h(1, "Requirements Extraction Test Suite — Findings Report")
    p(f"4 projects × 3 variants = 12 runs")
    p("Error categories: **OMISSION** | **WRONG_REQ** | **COMPOUND** | **SYSTEM_ACTOR** | **NON_INVOKABLE** | **DUPLICATE**")

    # Summary table
    h(2, "Summary Table")
    lines.append("| Project | Variant | # Extracted | # GT Matched | # Omissions | # Auto-errors | # Wrong | # Dupes |\n")
    lines.append("|---------|---------|------------|-------------|------------|--------------|--------|--------|\n")
    for project, analyses in all_analyses:
        for a in analyses:
            lines.append(
                f"| {project.name} | {a.run.variant_label}: {a.run.variant_description[:40]}… "
                f"| {len(a.run.requirements)} "
                f"| {len(a.matched)}/{len(project.must_extract)} "
                f"| {len(a.omitted)} "
                f"| {len(a.auto_errors)} "
                f"| {len(a.wrong_reqs)} "
                f"| {len(a.duplicates)} |\n"
            )

    # Per-project detailed findings
    for project, analyses in all_analyses:
        h(2, project.name)
        p(f"**Project type:** {project.project_type}")
        p(f"**Ground truth requirements ({len(project.must_extract)}):**")
        for gt in project.must_extract:
            li(gt.description)

        for a in analyses:
            h(3, f"Variant {a.run.variant_label} — {a.run.variant_description}")
            if a.run.error:
                p(f"**RUN FAILED:** {a.run.error}")
                continue

            p(f"**Docs used:** {', '.join(a.run.docs_used) or '(none)'}")
            p(f"**Requirements extracted:** {len(a.run.requirements)}")
            p(f"**GT matched:** {len(a.matched)}/{len(project.must_extract)}")

            # All extracted requirements
            p("**Full extracted list:**")
            for r in a.run.requirements:
                auto_errs = auto_detect_errors(r)
                err_tag = f" [WARN: {'|'.join(auto_errs)}]" if auto_errs else ""
                is_gt = any(match(r, gt) for gt in project.must_extract)
                is_must_not = any(match(r, gt) for gt in project.must_not_extract)
                gt_tag = " [GT_MATCH]" if is_gt else (" [MUST_NOT_EXTRACT]" if is_must_not else " [UNMATCHED]")
                li(f"`{r['req_id']}` {r['description']}{gt_tag}{err_tag}")

            # Omissions
            if a.omitted:
                p(f"\n**OMISSIONS ({len(a.omitted)}) — ground truth requirements not extracted:**")
                for gt in a.omitted:
                    li(f"**OMISSION:** {gt.description}", 1)

            # Auto-detected structural errors
            if a.auto_errors:
                p(f"\n**AUTO-DETECTED STRUCTURAL ERRORS ({len(a.auto_errors)}):**")
                for r, errs in a.auto_errors:
                    li(f"**{'+'.join(errs)}:** `{r['req_id']}` — {r['description']}", 1)

            # Must-not items that appeared
            if a.must_not_present:
                p(f"\n**MUST-NOT-EXTRACT ITEMS THAT APPEARED ({len(a.must_not_present)}):**")
                for r, reason in a.must_not_present:
                    li(f"**{reason}:** `{r['req_id']}` — {r['description']}", 1)

            # Unmatched reqs (no GT match, no auto-error)
            if a.wrong_reqs:
                p(f"\n**UNMATCHED / POTENTIAL WRONG REQUIREMENTS ({len(a.wrong_reqs)}):**")
                for r in a.wrong_reqs:
                    li(f"**UNMATCHED:** `{r['req_id']}` — {r['description']}", 1)

            # Duplicates
            if a.duplicates:
                p(f"\n**DUPLICATES ({len(a.duplicates)}):**")
                for id_a, id_b, score in a.duplicates:
                    req_a = next((r for r in a.run.requirements if r.get("req_id") == id_a), {})
                    req_b = next((r for r in a.run.requirements if r.get("req_id") == id_b), {})
                    li(f"**DUPLICATE** ({score:.0%} overlap): `{id_a}` \"{req_a.get('description', '')}\" <-> `{id_b}` \"{req_b.get('description', '')}\"", 1)

            # Variant C: extras found/not-found
            if a.run.variant_label == "C":
                p("\n**VARIANT C — Req-box extras (not in README):**")
                if a.extras_found:
                    for r in a.extras_found:
                        li(f"✓ EXTRA INCLUDED: `{r['req_id']}` — {r['description']}", 1)
                if a.extras_not_found:
                    for desc in a.extras_not_found:
                        li(f"✗ EXTRA MISSING: {desc}", 1)

    # Cross-project error log
    h(2, "Cross-Project Error Log")
    p("All detected errors consolidated:")
    lines.append("| Project | Variant | Error Type | Req ID | Description |\n")
    lines.append("|---------|---------|------------|--------|-------------|\n")
    for project, analyses in all_analyses:
        for a in analyses:
            if a.run.error:
                lines.append(f"| {project.name} | {a.run.variant_label} | RUN_FAILED | — | {a.run.error} |\n")
                continue
            for gt in a.omitted:
                lines.append(f"| {project.name} | {a.run.variant_label} | OMISSION | — | {gt.description} |\n")
            for r, errs in a.auto_errors:
                for e in errs:
                    lines.append(f"| {project.name} | {a.run.variant_label} | {e} | {r.get('req_id','')} | {r.get('description','')} |\n")
            for r, reason in a.must_not_present:
                lines.append(f"| {project.name} | {a.run.variant_label} | {reason} | {r.get('req_id','')} | {r.get('description','')} |\n")
            for r in a.wrong_reqs:
                lines.append(f"| {project.name} | {a.run.variant_label} | WRONG_REQ | {r.get('req_id','')} | {r.get('description','')} |\n")
            for id_a, id_b, score in a.duplicates:
                ra = next((r for r in a.run.requirements if r.get("req_id") == id_a), {})
                rb = next((r for r in a.run.requirements if r.get("req_id") == id_b), {})
                lines.append(f"| {project.name} | {a.run.variant_label} | DUPLICATE | {id_a}+{id_b} | \"{ra.get('description','')}\" ↔ \"{rb.get('description','')}\" |\n")

    # Variant-effect analysis
    h(2, "Variant Effect Analysis")
    p("For each project, how does adding a requirements box change extraction quality?")
    for project, analyses in all_analyses:
        h(3, project.name)
        if len(analyses) < 3:
            p("Insufficient data.")
            continue
        va, vb, vc = analyses
        p(f"- **A (README only):** {len(va.matched)}/{len(project.must_extract)} GT matched, {len(va.omitted)} omissions, {len(va.auto_errors)} structural errors")
        p(f"- **B (Subset in req box):** {len(vb.matched)}/{len(project.must_extract)} GT matched, {len(vb.omitted)} omissions, {len(vb.auto_errors)} structural errors")
        p(f"- **C (Subset + extras):** {len(vc.matched)}/{len(project.must_extract)} GT matched, {len(vc.omitted)} omissions, {len(vc.auto_errors)} structural errors")

        a_set = {gt.description for gt in va.omitted}
        b_set = {gt.description for gt in vb.omitted}
        c_set = {gt.description for gt in vc.omitted}

        recovered_by_b = a_set - b_set
        recovered_by_c = a_set - c_set
        new_in_b = set(r['description'] for r in vb.run.requirements) - set(r['description'] for r in va.run.requirements)
        new_in_c = set(r['description'] for r in vc.run.requirements) - set(r['description'] for r in va.run.requirements)

        if recovered_by_b:
            p(f"  - Adding req box (B) recovered: {', '.join(recovered_by_b)}")
        if new_in_b - {gt.description for gt in project.must_extract}:
            extra_b = new_in_b - {gt.description for gt in project.must_extract}
            p(f"  - New in B not in GT: {', '.join(list(extra_b)[:3])}")
        if vc.extras_found:
            p(f"  - C extras included in output: {', '.join(r['description'] for r in vc.extras_found)}")
        if vc.extras_not_found:
            p(f"  - C extras NOT included: {', '.join(vc.extras_not_found)}")

    return "".join(lines)


# ─── main ─────────────────────────────────────────────────────────────────────

async def main():
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found in .env")
        sys.exit(1)

    client = anthropic.AsyncAnthropic(api_key=api_key)

    all_analyses: list[tuple[Project, list[VariantAnalysis]]] = []
    all_results_json: list[dict] = []

    for project in PROJECTS:
        print(f"\n{'='*60}")
        print(f"Project: {project.name}")
        print(f"{'='*60}")
        if not project.extract_to.exists():
            print(f"  SKIP: extract_to not found: {project.extract_to}")
            continue

        project_analyses: list[VariantAnalysis] = []
        for variant in project.variants:
            run = await run_variant(project, variant, client)
            analysis = analyse(run, project)
            project_analyses.append(analysis)

            # Save raw JSON
            all_results_json.append({
                "project": project.name,
                "variant": variant.label,
                "variant_description": variant.description,
                "requirements_text": variant.requirements_text,
                "requirements": run.requirements,
                "error": run.error,
                "project_summary": run.project_summary,
                "docs_used": run.docs_used,
            })

        all_analyses.append((project, project_analyses))

    # Save raw JSON results
    json_path = Path(__file__).parent / "req_test_results.json"
    json_path.write_text(json.dumps(all_results_json, indent=2), encoding="utf-8")
    print(f"\nRaw results saved to: {json_path}")

    # Render and save report
    report = render_report(all_analyses)
    report_path = Path(__file__).parent / "req_test_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Report saved to: {report_path}")

    # Print summary to stdout
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for project, analyses in all_analyses:
        print(f"\n{project.name}")
        for a in analyses:
            print(f"  Variant {a.run.variant_label}: {len(a.matched)}/{len(project.must_extract)} GT matched, "
                  f"{len(a.omitted)} omissions, {len(a.auto_errors)} structural errors, "
                  f"{len(a.duplicates)} dupes, {len(a.wrong_reqs)} unmatched")


if __name__ == "__main__":
    asyncio.run(main())
