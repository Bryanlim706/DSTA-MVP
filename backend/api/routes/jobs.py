from fastapi import APIRouter, HTTPException

from storage.job_store import get_job, list_jobs

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
