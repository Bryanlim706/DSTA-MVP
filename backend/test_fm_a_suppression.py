"""
FM-A Suppression Test
=====================
Tests whether a requirements box anchored to a different domain suppresses
README requirements that would otherwise be extracted.

Variants per project:
  A — README only (no req box)
  B — README + req box from a completely different domain
  C — README + req box from yet another different domain

Output: which requirements from A were suppressed in B and C.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from pipeline.step1_req_extractor import LLM_SYSTEM_PROMPT, _build_user_message, _parse_llm_response, _validate_and_normalise

# ─────────────────────────────────────────────────────────────────────────────
# PROJECT READMES
# ─────────────────────────────────────────────────────────────────────────────

PROJECTS = {

    "EMS": {
        "readme": """\
# Employee Management System

A web application for HR teams to manage the full employee lifecycle.

## Features

### Authentication
- Employees and admins can log in with their credentials
- Admins can log out of the system

### Employee Records
- Admins can add a new employee record (name, department, role, contact details)
- Admins can edit an existing employee's details
- Admins can delete an employee record
- Users can search for employees by name or department
- Users can view a detailed employee profile

### Attendance Tracking
- Employees can mark their daily attendance (clock in / clock out)
- Admins can view the attendance report for any employee
- Admins can manually correct an attendance entry

### Leave Management
- Employees can submit a leave request (type, dates, reason)
- Admins can approve or reject a leave request
- Employees can view the status of their submitted leave requests

### Department Management
- Admins can create a new department
- Admins can assign an employee to a department
- Admins can view all employees in a department

### Performance Reviews
- Admins can create a performance review for an employee
- Employees can view their own performance reviews
""",
        "req_b": """\
Product catalog management:
- User can add a new product with name, price, and category
- User can edit product details
- User can delete a product from the catalog
- User can view the full product list
""",
        "req_c": """\
E-commerce checkout:
- User can add items to shopping cart
- User can view cart contents
- User can apply a discount coupon
- User can complete checkout and place an order
- User can view order history
""",
    },

    "LibraryMS": {
        "readme": """\
# Library Management System

A system for public libraries to manage their collection and member activity.

## Features

### Member Registration
- Members can register an account with name, address, and contact info
- Members can log in to the library portal
- Members can update their profile details
- Members can log out

### Book Catalogue
- Members can search for books by title, author, or genre
- Members can view a book's detail page (availability, description, location)
- Librarians can add a new book to the catalogue
- Librarians can edit an existing book record
- Librarians can remove a book from the catalogue

### Borrowing & Returns
- Members can borrow an available book
- Members can view their currently borrowed books
- Members can return a borrowed book
- Librarians can extend a loan period for a member

### Reservations
- Members can reserve a book that is currently on loan
- Members can cancel a reservation
- Members can view their active reservations

### Fines
- Members can view any outstanding fines on their account
- Members can pay a fine online

### Reporting (Librarian)
- Librarians can view an overdue loans report
- Librarians can view the most-borrowed books report
""",
        "req_b": """\
Hospital appointment system:
- Patient can register with personal and insurance details
- Patient can schedule an appointment with a doctor
- Patient can view upcoming appointments
- Patient can cancel an appointment
""",
        "req_c": """\
Event ticketing platform:
- User can browse upcoming events by category
- User can purchase tickets for an event
- User can view their purchased tickets
- User can request a refund for a ticket
""",
    },

    "TaskTracker": {
        "readme": """\
# TaskTracker — Project & Task Management Tool

A collaborative tool for software teams to plan, assign, and track work.

## Features

### Workspaces & Projects
- Users can create a new workspace
- Users can create a project within a workspace
- Users can archive a project
- Users can delete a project

### Task Management
- Users can create a task with a title, description, and due date
- Users can assign a task to a team member
- Users can change the status of a task (To Do / In Progress / Done)
- Users can set a priority level on a task (low, medium, high, urgent)
- Users can delete a task
- Users can search for tasks by keyword or assignee

### Comments & Collaboration
- Users can add a comment to a task
- Users can edit their own comment
- Users can delete their own comment
- Users can @mention a team member in a comment

### File Attachments
- Users can attach a file to a task
- Users can download an attachment from a task
- Users can remove an attachment they uploaded

### Team Management
- Admins can invite a new member to a workspace by email
- Admins can remove a member from a workspace
- Admins can change a member's role (viewer, member, admin)

### Notifications
- Users can view their notification feed
- Users can mark a notification as read
- Users can configure which events trigger email notifications
""",
        "req_b": """\
Restaurant ordering system:
- Customer can browse menu by category
- Customer can add items to an order
- Customer can customise a menu item (e.g. remove ingredients)
- Customer can place the order and select delivery or pickup
- Customer can track delivery status
""",
        "req_c": """\
Banking mobile app:
- User can log in with biometric authentication
- User can view account balance and recent transactions
- User can transfer money to another account
- User can pay a bill
- User can download a monthly statement
""",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def extract(client: anthropic.AsyncAnthropic, readme: str, req_box: str, label: str) -> list[dict]:
    spec_docs = {"README.md": readme}
    msg = _build_user_message(req_box, spec_docs)
    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8000,
        system=[{"type": "text", "text": LLM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": msg}],
    )
    raw, _ = _parse_llm_response(resp.content[0].text)
    reqs, _ = _validate_and_normalise(raw)
    print(f"  {label}: {len(reqs)} requirements extracted")
    return reqs


def descriptions(reqs: list[dict]) -> list[str]:
    return [r["description"] for r in reqs]


def find_suppressed(a_reqs: list[dict], b_reqs: list[dict]) -> list[dict]:
    """Return README-sourced reqs in A that have no close match among README-sourced reqs in B."""
    # Only compare README-sourced requirements on both sides
    a_readme = [r for r in a_reqs if r.get("source", "").lower() != "user_input"]
    b_readme = [r for r in b_reqs if r.get("source", "").lower() != "user_input"]

    b_words = set()
    for r in b_readme:
        b_words.update(r["description"].lower().split())

    suppressed = []
    stop = {"user", "can", "a", "an", "the", "to", "their", "its", "of", "in", "and", "or"}
    for r in a_readme:
        a_words = set(r["description"].lower().split()) - stop
        if not a_words:
            continue
        overlap = len(a_words & b_words) / len(a_words)
        if overlap < 0.5:
            suppressed.append(r)
    return suppressed


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    all_results = {}

    for proj_name, proj in PROJECTS.items():
        print(f"\n{'='*60}")
        print(f"PROJECT: {proj_name}")
        print(f"{'='*60}")

        # Run A, B, C concurrently
        a_task = extract(client, proj["readme"], "",           "A (no req box)")
        b_task = extract(client, proj["readme"], proj["req_b"], "B (cross-domain req box)")
        c_task = extract(client, proj["readme"], proj["req_c"], "C (cross-domain req box)")
        a_reqs, b_reqs, c_reqs = await asyncio.gather(a_task, b_task, c_task)

        sup_b = find_suppressed(a_reqs, b_reqs)
        sup_c = find_suppressed(a_reqs, c_reqs)

        a_readme_count = sum(1 for r in a_reqs if r.get("source", "").lower() != "user_input")
        b_readme_count = sum(1 for r in b_reqs if r.get("source", "").lower() != "user_input")
        c_readme_count = sum(1 for r in c_reqs if r.get("source", "").lower() != "user_input")

        all_results[proj_name] = {
            "A": [{"desc": r["description"], "source": r.get("source", ""), "area": r.get("functional_area", "")} for r in a_reqs],
            "B": [{"desc": r["description"], "source": r.get("source", ""), "area": r.get("functional_area", "")} for r in b_reqs],
            "C": [{"desc": r["description"], "source": r.get("source", ""), "area": r.get("functional_area", "")} for r in c_reqs],
            "suppressed_in_B": [{"description": r["description"], "source_quote": r.get("source_quote", ""), "source": r.get("source", ""), "functional_area": r.get("functional_area", "")} for r in sup_b],
            "suppressed_in_C": [{"description": r["description"], "source_quote": r.get("source_quote", ""), "source": r.get("source", ""), "functional_area": r.get("functional_area", "")} for r in sup_c],
            "counts": {
                "A_total": len(a_reqs),
                "A_readme": a_readme_count,
                "B_total": len(b_reqs),
                "B_readme": b_readme_count,
                "C_total": len(c_reqs),
                "C_readme": c_readme_count,
                "suppressed_B": len(sup_b),
                "suppressed_C": len(sup_c),
            },
        }

    # ── Save full JSON first ──────────────────────────────────────────────────
    out_path = Path(__file__).parent / "fm_a_suppression_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {out_path}")

    # ── Print report (ASCII-safe) ─────────────────────────────────────────────
    print("\n\n" + "="*70)
    print("FM-A SUPPRESSION REPORT")
    print("="*70)

    for proj_name, data in all_results.items():
        c = data["counts"]
        print(f"\n-- {proj_name} " + "-"*50)
        print(f"  A (baseline):         {c['A_total']} total  ({c['A_readme']} from README)")
        print(f"  B (cross-domain box): {c['B_total']} total  ({c['B_readme']} from README)  |  README suppressed: {c['suppressed_B']}")
        print(f"  C (cross-domain box): {c['C_total']} total  ({c['C_readme']} from README)  |  README suppressed: {c['suppressed_C']}")

        if data["suppressed_in_B"]:
            print(f"\n  Suppressed in B ({len(data['suppressed_in_B'])} items):")
            for r in data["suppressed_in_B"]:
                print(f"    * [{r['functional_area']}] {r['description']}")
                quote = r['source_quote'][:90].encode('ascii', 'replace').decode('ascii')
                print(f"      src: \"{quote}\"")
        else:
            print("  Suppressed in B: none")

        if data["suppressed_in_C"]:
            print(f"\n  Suppressed in C ({len(data['suppressed_in_C'])} items):")
            for r in data["suppressed_in_C"]:
                print(f"    * [{r['functional_area']}] {r['description']}")
                quote = r['source_quote'][:90].encode('ascii', 'replace').decode('ascii')
                print(f"      src: \"{quote}\"")
        else:
            print("  Suppressed in C: none")


if __name__ == "__main__":
    asyncio.run(main())
