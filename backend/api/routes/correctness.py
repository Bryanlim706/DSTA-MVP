"""Correctness phase endpoints — Step 8 (behavioral gen) + Step 8.5 (AC generation)."""
import anthropic

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from pipeline import step8_behavioral_gen, step8_5_ac_generator
from storage.job_store import add_step_result, get_job, is_terminated, update_job

router = APIRouter()


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _run_step8(job_id: str) -> None:
    if is_terminated(job_id):
        return
    try:
        job = get_job(job_id)
        if not job:
            return

        client = anthropic.AsyncAnthropic()
        requirements_text = job.get("requirements_text", "")
        step3_5 = job["step_results"]["step_3_5"]
        step4 = job["step_results"].get("step_4", {})

        result = await step8_behavioral_gen.run(
            requirements_text=requirements_text,
            step3_5=step3_5,
            step4=step4,
            client=client,
        )

        if is_terminated(job_id):
            return
        add_step_result(job_id, "step_8", result)
        update_job(job_id, {
            "status": "step_8_complete" if not result.get("error") else "step_8_error",
        })

    except Exception as exc:
        if is_terminated(job_id):
            return
        add_step_result(job_id, "step_8", {"behavioral_requirements": [], "error": str(exc)})
        update_job(job_id, {"status": "step_8_error"})


async def _run_step8_5(job_id: str, selected_ids: list[str]) -> None:
    if is_terminated(job_id):
        return
    try:
        job = get_job(job_id)
        if not job:
            return

        client = anthropic.AsyncAnthropic()
        step3_5 = job["step_results"]["step_3_5"]
        step8 = job["step_results"].get("step_8", {"behavioral_requirements": []})
        existing_step8_5 = job["step_results"].get("step_8_5")

        result = await step8_5_ac_generator.run(
            selected_ids=selected_ids,
            step3_5=step3_5,
            step8=step8,
            client=client,
            existing_step8_5=existing_step8_5,
        )

        if is_terminated(job_id):
            return
        add_step_result(job_id, "step_8_5", result)
        update_job(job_id, {
            "status": "step_8_5_complete" if not result.get("error") else "step_8_5_error",
        })

    except Exception as exc:
        if is_terminated(job_id):
            return
        add_step_result(job_id, "step_8_5", {
            "acceptance_criteria": [],
            "selected_ids": selected_ids,
            "total_acs": 0,
            "error": str(exc),
        })
        update_job(job_id, {"status": "step_8_5_error"})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/behavioral")
async def trigger_behavioral(job_id: str, background_tasks: BackgroundTasks):
    """Start behavioral requirement generation (Step 8).

    Requires step_7_5_complete. Returns immediately if step_8 already cached.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if "step_3_5" not in job.get("step_results", {}):
        raise HTTPException(status_code=400, detail="Step 3.5 not complete")
    if "step_7_5" not in job.get("step_results", {}):
        raise HTTPException(
            status_code=400,
            detail="Step 7.5 not complete — presence phase must finish first",
        )

    # Cache hit — return immediately without re-running
    if "step_8" in job.get("step_results", {}):
        return {"status": job["status"], "job_id": job_id, "cached": True}

    if job.get("status") == "step_8_running":
        raise HTTPException(status_code=409, detail="Behavioral generation already running")

    update_job(job_id, {"status": "step_8_running"})
    background_tasks.add_task(_run_step8, job_id)
    return {"status": "step_8_running", "job_id": job_id}


class ACSRequest(BaseModel):
    selected_ids: list[str]


@router.post("/jobs/{job_id}/acs")
async def generate_acs(job_id: str, body: ACSRequest, background_tasks: BackgroundTasks):
    """Generate acceptance criteria for the selected requirement IDs (Step 8.5).

    Called once on Confirm. Per-req caching means already-generated req_ids are skipped.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if "step_3_5" not in job.get("step_results", {}):
        raise HTTPException(status_code=400, detail="Step 3.5 not complete")

    if job.get("status") == "step_8_5_running":
        raise HTTPException(status_code=409, detail="AC generation already running")

    update_job(job_id, {"status": "step_8_5_running"})
    background_tasks.add_task(_run_step8_5, job_id, body.selected_ids)
    return {"status": "step_8_5_running", "job_id": job_id}
