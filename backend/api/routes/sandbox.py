import asyncio
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pathlib import Path

from pipeline import step11_sandbox
from storage.job_store import get_job, update_job

router = APIRouter()


async def _run_step11(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    try:
        step_3_5        = job["step_results"]["step_3_5"]
        project_context = step_3_5["project_context"]
        extract_to      = Path(job.get("extracted_path", f"./uploads/{job_id}/extracted")).resolve()

        result = await step11_sandbox.run(
            job_id=job_id,
            extract_to=extract_to,
            project_context=project_context,
        )

        job = get_job(job_id)
        job["step_results"]["step_11"] = result
        job["status"] = (
            "step_11_complete"
            if result.get("boot_status") in ("success", "partial")
            else "step_11_error"
        )
        update_job(job_id, job)

    except Exception as exc:
        job = get_job(job_id)
        if job:
            job["step_results"]["step_11"] = {"boot_status": "boot_failed", "error": str(exc)}
            job["status"] = "step_11_error"
            update_job(job_id, job)


@router.post("/jobs/{job_id}/sandbox/stop")
async def stop_sandbox(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await asyncio.to_thread(step11_sandbox.teardown, job_id)
    job = get_job(job_id)
    if job:
        if "step_11" in job.get("step_results", {}):
            job["step_results"]["step_11"]["sandbox_alive"] = False
        update_job(job_id, job)
    return {"status": "torn_down"}


@router.post("/jobs/{job_id}/sandbox")
async def trigger_sandbox(job_id: str, background_tasks: BackgroundTasks):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if "step_3_5" not in job.get("step_results", {}):
        raise HTTPException(status_code=400, detail="Step 3.5 not complete — confirm requirements first")
    if job.get("status") == "step_11_running":
        raise HTTPException(status_code=409, detail="Sandbox already running")

    job["status"] = "step_11_running"
    update_job(job_id, job)
    background_tasks.add_task(_run_step11, job_id)
    return {"status": "step_11_running", "job_id": job_id}
