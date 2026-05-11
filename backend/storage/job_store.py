import json
import os
from pathlib import Path
from datetime import datetime, timezone

JOBS_DIR = Path(os.getenv("JOBS_DIR", "./jobs"))


def _path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, initial_data: dict) -> dict:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "status": "created",
        "current_step": -1,
        "created_at": _now(),
        "updated_at": _now(),
        "step_results": {},
        "errors": [],
        **initial_data,
    }
    _write(job_id, job)
    return job


def get_job(job_id: str) -> dict | None:
    p = _path(job_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def update_job(job_id: str, updates: dict) -> dict:
    job = get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job.update(updates)
    job["updated_at"] = _now()
    _write(job_id, job)
    return job


def _write(job_id: str, job: dict) -> None:
    with open(_path(job_id), "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
