from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage.job_store import add_step_result, get_job, update_job

router = APIRouter()


class ConfirmedRequirement(BaseModel):
    req_id: str
    description: str
    tag: str
    priority: str
    weight: float
    functional_area: str | None = None
    testable: bool = True
    source: str
    promoted: bool = False


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

    req_dicts = [r.model_dump() for r in body.requirements]

    # Compute stats
    step1_ids = {r["req_id"] for r in job.get("step_results", {}).get("step_1", {}).get("requirements", [])}
    step2_ids = {r["req_id"] for r in job.get("step_results", {}).get("step_2", {}).get("requirements", [])}
    confirmed_ids = {r["req_id"] for r in req_dicts}

    l1a_count = len(req_dicts)
    promoted_count = sum(1 for r in req_dicts if r["req_id"].startswith("GEN-"))
    deleted_count = len((step1_ids | step2_ids) - confirmed_ids)
    added_count = sum(1 for r in req_dicts if r["req_id"].startswith("CUSTOM-"))

    result = {
        "confirmed_requirements": req_dicts,
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
