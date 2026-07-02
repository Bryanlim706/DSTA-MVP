import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

JOBS_DIR = Path(os.getenv("JOBS_DIR", "./jobs"))
UPLOADS_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
MAX_JOBS = 50


def _path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cleanup_old_jobs() -> None:
    """Delete oldest jobs beyond MAX_JOBS, removing both job JSON and uploads directory."""
    if not JOBS_DIR.exists():
        return
    job_files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    excess = job_files[: max(0, len(job_files) - MAX_JOBS)]
    for p in excess:
        job_id = p.stem
        p.unlink(missing_ok=True)
        upload_dir = UPLOADS_DIR / job_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)


def create_job(job_id: str, initial_data: dict) -> dict:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_old_jobs()
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
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def update_job(job_id: str, updates: dict) -> dict:
    job = get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job.update(updates)
    job["updated_at"] = _now()
    _write(job_id, job)
    return job


def is_terminated(job_id: str) -> bool:
    """True if the job has been terminated by the user. Pipeline runners check
    this at step boundaries to halt the chain without overwriting the status."""
    job = get_job(job_id)
    return bool(job and job.get("status") == "terminated")


def add_step_result(job_id: str, step_key: str, result: dict) -> dict:
    job = get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job["step_results"][step_key] = result
    job["updated_at"] = _now()
    _write(job_id, job)
    return job


def list_jobs(limit: int = 10) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    summaries = []
    for p in JOBS_DIR.glob("*.json"):
        try:
            j = get_job(p.stem)
        except Exception:
            continue
        if j and j.get("job_id"):
            summaries.append({
                "job_id": j.get("job_id", p.stem),
                "status": j.get("status", "unknown"),
                "current_step": j.get("current_step", -1),
                "created_at": j.get("created_at"),
                "steps_complete": list(j.get("step_results", {}).keys()),
            })
    summaries.sort(key=lambda j: j["created_at"] or "")
    return summaries[-limit:] if limit else summaries


def _write(job_id: str, job: dict) -> None:
    with open(_path(job_id), "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
