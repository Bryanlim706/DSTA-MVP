import asyncio

from fastapi import APIRouter, HTTPException

from pipeline import step11_sandbox
from storage.job_store import get_job, list_jobs, update_job

router = APIRouter()


@router.get("/jobs")
async def list_recent_jobs(limit: int = 10):
    return list_jobs(limit)


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/terminate")
async def terminate_job(job_id: str):
    """Stop the in-progress pipeline for a job. Sets status to 'terminated';
    pipeline runners check this at each step boundary and halt the chain.
    Best-effort tears down any Step 11 sandbox containers."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    update_job(job_id, {"status": "terminated"})
    try:
        await asyncio.to_thread(step11_sandbox.teardown, job_id)
    except Exception:
        pass
    return {"status": "terminated"}
