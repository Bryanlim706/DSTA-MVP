import asyncio
import uuid
import zipfile
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from pipeline import step0_classifier
from storage.job_store import create_job, update_job

router = APIRouter()

UPLOAD_DIR = Path("./uploads")


@router.post("/upload")
async def upload_project(
    request: Request,
    background_tasks: BackgroundTasks,
    project_zip: UploadFile = File(...),
    requirements: str = Form(...),
):
    if not project_zip.filename or not project_zip.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")
    if not requirements.strip():
        raise HTTPException(status_code=400, detail="Requirements text is required")

    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    zip_path = job_dir / "project.zip"
    async with aiofiles.open(zip_path, "wb") as f:
        await f.write(await project_zip.read())

    create_job(
        job_id,
        {
            "zip_path": str(zip_path),
            "requirements_text": requirements.strip(),
            "extracted_path": str(job_dir / "extracted"),
        },
    )

    client = request.app.state.anthropic_client
    background_tasks.add_task(_run_pipeline, job_id, zip_path, job_dir / "extracted", client)

    return {"job_id": job_id, "status": "created"}


async def _run_pipeline(job_id: str, zip_path: Path, extract_to: Path, client):
    try:
        update_job(job_id, {"status": "running", "current_step": 0})

        try:
            await asyncio.to_thread(_extract_zip, zip_path, extract_to)
        except zipfile.BadZipFile:
            update_job(job_id, {"status": "error", "errors": ["Uploaded file is not a valid zip archive"]})
            return

        result = await step0_classifier.run(extract_to, client)

        update_job(
            job_id,
            {
                "status": "step_0_complete",
                "current_step": 0,
                "step_results": {"step_0": result},
            },
        )
    except Exception as e:
        update_job(job_id, {"status": "error", "errors": [str(e)]})


def _extract_zip(zip_path: Path, extract_to: Path) -> None:
    extract_to.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)
