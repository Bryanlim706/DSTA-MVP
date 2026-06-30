"""
Steps 1-3 test harness.

Runs Steps 1, 2, 3 for three project types × four requirements-box variants
and saves a structured JSON result for later analysis.

Usage:
    cd backend
    venv/Scripts/activate
    python run_steps1_3_test.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# ── project root on path ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from dotenv import load_dotenv
load_dotenv()

from pipeline import step1_req_extractor, step2_obvious_generator, step3_implied_generator

# ── project configurations ────────────────────────────────────────────────────

PROJECTS = {
    "spring_ecommerce": {
        "name": "Spring Boot + React E-commerce",
        "type": "full_stack_web_app",
        "extracted_path": Path("uploads/1971789b-fd11-4a5b-8f94-30abbcf25e68/extracted"),
        # Step 0 result reused from this job
        "step0": {
            "project_type": "full_stack_web_app",
            "frontend_framework": "React",
            "frontend_tooling": "Vite",
            "backend_framework": "Spring Boot",
            "template_engine": None,
            "service_layout": "separate_frontend_backend",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Spring Boot backend + React/Vite frontend",
            "test_strategy": {"primary": "Playwright", "secondary": "JUnit/MockMvc"},
            "config_files_found": ["pom.xml", "package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": ["AddProduct.jsx", "ProductList.jsx", "UpdateProduct.jsx"],
        },
        # Ground truth from README
        "readme_ground_truth": [
            "User can view all products",
            "User can view product details by ID",
            "User can add new product",
            "User can update product",
            "User can delete product",
        ],
        # Variants: (description, requirements_text, use_requirements_box, use_readme)
        "variants": [
            {
                "id": "A_no_req_box",
                "label": "No requirements box — README only",
                "requirements_text": "",
                "use_requirements_box": False,
                "use_readme": True,
            },
            {
                "id": "B_subset",
                "label": "Requirements box = 40% subset of README features",
                "requirements_text": (
                    "User can view all products.\n"
                    "User can add a new product."
                ),
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "C_subset_plus_extra",
                "label": "Requirements box = 40% subset + 2 invented features",
                "requirements_text": (
                    "User can view all products.\n"
                    "User can add a new product.\n"
                    "User can add items to a shopping cart.\n"
                    "User can checkout and pay for their order."
                ),
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "D_req_box_equals_readme",
                "label": "Requirements box = full README feature list (no README source)",
                "requirements_text": (
                    "Fetch all products.\n"
                    "Get product by ID.\n"
                    "Add new product.\n"
                    "Update product.\n"
                    "Delete product."
                ),
                "use_requirements_box": True,
                "use_readme": False,
            },
        ],
    },

    "todometer_electron": {
        "name": "Electron + React Todometer",
        "type": "electron_app",
        "extracted_path": Path("uploads/8208feb0-9b95-4b0c-983d-47a33265c9c9/extracted"),
        "step0": {
            "project_type": "electron_app",
            "frontend_framework": "React",
            "frontend_tooling": "Webpack",
            "backend_framework": "Electron",
            "template_engine": None,
            "service_layout": "single_project",
            "server_routes_detected": False,
            "confidence": "high",
            "reasoning": "Electron + React todo app",
            "test_strategy": {"primary": "Playwright", "secondary": None},
            "config_files_found": ["package.json"],
            "llm_used": False,
            "llm_model": None,
            "discovered_pages": [],
            "runtime": "Electron",
        },
        "readme_ground_truth": [
            "User can add to-do items",
            "User can complete to-do items",
            "User can pause to-do items",
            "User can delete to-do items",
            "User can drag and drop to reorder items",
            "User can drag and drop to move items between groups",
            "User can configure notification preferences",
            "User can configure data vault location",
            "User can configure display options",
            "User can add todos via protocol handler URL",
        ],
        "variants": [
            {
                "id": "A_no_req_box",
                "label": "No requirements box — README only",
                "requirements_text": "",
                "use_requirements_box": False,
                "use_readme": True,
            },
            {
                "id": "B_subset",
                "label": "Requirements box = 40% subset of README features",
                "requirements_text": (
                    "User can add to-do items.\n"
                    "User can complete to-do items.\n"
                    "User can delete to-do items.\n"
                    "User can drag and drop to reorder items."
                ),
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "C_subset_plus_extra",
                "label": "Requirements box = 40% subset + 3 invented features",
                "requirements_text": (
                    "User can add to-do items.\n"
                    "User can complete to-do items.\n"
                    "User can delete to-do items.\n"
                    "User can drag and drop to reorder items.\n"
                    "User can share tasks with other users.\n"
                    "User can assign tasks to team members.\n"
                    "User can set task priority levels."
                ),
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "D_req_box_equals_readme",
                "label": "Requirements box = full README feature list (no README source)",
                "requirements_text": (
                    "Add, complete, pause, and delete to-do items.\n"
                    "Drag and drop to reorder items or move them between groups.\n"
                    "Daily auto-reset with optional notifications and reminders.\n"
                    "Settings drawer to configure notification preferences, data vault location, "
                    "display options, and local REST API/MCP server.\n"
                    "Protocol handler to add todos via URL."
                ),
                "use_requirements_box": True,
                "use_readme": False,
            },
        ],
    },

    "react_shopping_cart": {
        "name": "React Shopping Cart (frontend-only)",
        "type": "frontend_only",
        "extracted_path": Path("uploads/40b7c631-e2a7-4e6c-8fdd-e66e2e58aabb/extracted"),
        "step0": {
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
        "readme_ground_truth": [
            "User can add products to cart",
            "User can remove products from cart",
            "User can filter products by available sizes",
        ],
        "variants": [
            {
                "id": "A_no_req_box",
                "label": "No requirements box — README only",
                "requirements_text": "",
                "use_requirements_box": False,
                "use_readme": True,
            },
            {
                "id": "B_subset",
                "label": "Requirements box = single README feature (33% subset)",
                "requirements_text": "User can add products to the shopping cart.",
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "C_subset_plus_extra",
                "label": "Requirements box = 1 README feature + 3 invented features",
                "requirements_text": (
                    "User can add products to the shopping cart.\n"
                    "User can apply coupon codes at checkout.\n"
                    "User can save their cart for later.\n"
                    "User can view their order history."
                ),
                "use_requirements_box": True,
                "use_readme": True,
            },
            {
                "id": "D_req_box_equals_readme",
                "label": "Requirements box = full README feature list (no README source)",
                "requirements_text": (
                    "Add and remove products from the floating cart.\n"
                    "Filter products by available sizes.\n"
                    "Responsive design."
                ),
                "use_requirements_box": True,
                "use_readme": False,
            },
        ],
    },
}

# ── runner ─────────────────────────────────────────────────────────────────────

async def run_variant(project_key: str, variant: dict, project_cfg: dict, client) -> dict:
    extract_path = Path(__file__).parent / project_cfg["extracted_path"]
    step0 = project_cfg["step0"]

    print(f"  [{variant['id']}] {variant['label']}")
    print(f"    extract_path: {extract_path}")

    # Step 1
    print("    -> Step 1 ...")
    s1 = await step1_req_extractor.run(
        requirements_text=variant["requirements_text"],
        extract_to=extract_path,
        client=client,
        use_requirements_box=variant["use_requirements_box"],
        use_readme=variant["use_readme"],
    )
    s1_count = s1.get("total_count", 0)
    s1_error = s1.get("error")
    print(f"    Step 1: {s1_count} requirements{'  ERROR: ' + s1_error if s1_error else ''}")

    # Step 2
    print("    -> Step 2 ...")
    s2 = await step2_obvious_generator.run(
        s1.get("requirements", []),
        step0,
        client,
    )
    s2_count = s2.get("total_count", 0)
    s2_error = s2.get("error")
    print(f"    Step 2: {s2_count} obvious requirements{'  ERROR: ' + s2_error if s2_error else ''}")

    # Step 3
    print("    -> Step 3 ...")
    s3 = await step3_implied_generator.run(
        s1.get("requirements", []),
        s2.get("requirements", []),
        step0,
        client,
        project_summary=s1.get("project_summary", ""),
    )
    s3_count = s3.get("total_count", 0)
    s3_error = s3.get("error")
    print(f"    Step 3: {s3_count} generated requirements{'  ERROR: ' + s3_error if s3_error else ''}")

    return {
        "project": project_key,
        "variant_id": variant["id"],
        "variant_label": variant["label"],
        "requirements_text": variant["requirements_text"],
        "use_requirements_box": variant["use_requirements_box"],
        "use_readme": variant["use_readme"],
        "step1": s1,
        "step2": s2,
        "step3": s3,
    }


async def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment / .env")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    all_results = []
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for project_key, project_cfg in PROJECTS.items():
        print(f"\n{'='*60}")
        print(f"PROJECT: {project_cfg['name']}")
        print(f"{'='*60}")
        for variant in project_cfg["variants"]:
            result = await run_variant(project_key, variant, project_cfg, client)
            # Attach ground truth for analysis
            result["readme_ground_truth"] = project_cfg["readme_ground_truth"]
            all_results.append(result)

    # Save raw results
    out_path = Path(__file__).parent / f"test_results_steps1_3_{run_ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nOK Raw results saved to: {out_path}")

    # Print quick summary table
    print("\n" + "="*80)
    print("QUICK SUMMARY")
    print("="*80)
    print(f"{'Project':<26} {'Variant':<20} {'S1':>4} {'S2':>4} {'S3':>4}")
    print("-"*60)
    for r in all_results:
        proj = r["project"][:25]
        vid = r["variant_id"][:19]
        s1 = r["step1"].get("total_count", "ERR")
        s2 = r["step2"].get("total_count", "ERR")
        s3 = r["step3"].get("total_count", "ERR")
        print(f"{proj:<26} {vid:<20} {str(s1):>4} {str(s2):>4} {str(s3):>4}")

    return str(out_path)


if __name__ == "__main__":
    result_path = asyncio.run(main())
    print(f"\nDone. Results at: {result_path}")
