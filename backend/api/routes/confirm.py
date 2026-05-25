from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage.job_store import add_step_result, get_job, update_job

router = APIRouter()

STEP0_CONTEXT_FIELDS = (
    "project_type", "frontend_framework", "frontend_tooling", "backend_framework",
    "template_engine", "service_layout", "server_routes_detected", "discovered_pages",
    "test_strategy", "runtime",
)


class PathEntity(BaseModel):
    type: str
    label: str
    primary: bool = True
    ui_node: str | None = None
    from_: str | None = None
    to: str | None = None

    model_config = {"populate_by_name": True}

    def model_dump(self, **kwargs) -> dict[str, Any]:
        d = super().model_dump(**kwargs)
        if "from_" in d:
            d["from"] = d.pop("from_")
        return d


class ConfirmedRequirement(BaseModel):
    req_id: str
    description: str
    path: list[PathEntity] = []
    vague: bool = False
    tag: str
    priority: str = "medium"
    weight: float = 2.0
    functional_area: str | None = None
    testable: bool = True
    source: str
    promoted: bool = False
    unpacks: str | None = None
    depends_on: list[str] = []
    source_quote: str | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        d = super().model_dump(**kwargs)
        d["path"] = [e.model_dump() for e in self.path]
        return d


class ConfirmRequest(BaseModel):
    requirements: list[ConfirmedRequirement]
    skipped: bool = False


@router.post("/jobs/{job_id}/confirm")
async def confirm_requirements(job_id: str, body: ConfirmRequest):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "waiting_for_confirmation":
        raise HTTPException(
            status_code=422,
            detail=f"Job is not awaiting confirmation (status: {job.get('status')})",
        )
    if not body.requirements:
        raise HTTPException(status_code=422, detail="requirements must not be empty")

    step_results = job.get("step_results", {})
    step0 = step_results.get("step_0", {})
    step1 = step_results.get("step_1", {})
    step2 = step_results.get("step_2", {})
    step3 = step_results.get("step_3", {})

    # Build req_id lookup across all prior steps for depends_on / source_quote enrichment
    prior_reqs = (
        step1.get("requirements", [])
        + step2.get("requirements", [])
        + step3.get("requirements", [])
    )
    lookup = {r["req_id"]: r for r in prior_reqs if "req_id" in r}

    # Serialise confirmed requirements and enrich with depends_on / source_quote server-side
    req_dicts = []
    for r in body.requirements:
        d = r.model_dump()
        original = lookup.get(r.req_id, {})
        if not d.get("depends_on"):
            d["depends_on"] = original.get("depends_on", [])
        if d.get("source_quote") is None:
            d["source_quote"] = original.get("source_quote")
        req_dicts.append(d)

    step1_ids = {r["req_id"] for r in step1.get("requirements", [])}
    step2_ids = {r["req_id"] for r in step2.get("requirements", [])}
    confirmed_ids = {r["req_id"] for r in req_dicts}

    l1a_count = len(req_dicts)
    promoted_count = sum(1 for r in req_dicts if r["req_id"].startswith("GEN-"))
    deleted_count = len((step1_ids | step2_ids) - confirmed_ids)
    added_count = sum(1 for r in req_dicts if r["req_id"].startswith("CUSTOM-"))

    # Advisory requirements: Step 3 l1b items not promoted to l1a
    advisory_requirements = [
        r for r in step3.get("requirements", [])
        if r.get("placement") == "l1b" and r["req_id"] not in confirmed_ids
    ]

    # Project context passthrough from Step 0
    project_context = {k: step0.get(k) for k in STEP0_CONTEXT_FIELDS}

    result = {
        "confirmed_requirements": req_dicts,
        "advisory_requirements": advisory_requirements,
        "project_context": project_context,
        "project_summary": step1.get("project_summary"),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "skipped": body.skipped,
        "l1a_count": l1a_count,
        "promoted_count": promoted_count,
        "deleted_count": deleted_count,
        "added_count": added_count,
    }

    add_step_result(job_id, "step_3_5", result)
    update_job(job_id, {"status": "confirmed", "current_step": 4})

    return {"status": "confirmed", "l1a_count": l1a_count}
