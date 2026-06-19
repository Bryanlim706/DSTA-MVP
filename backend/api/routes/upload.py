import asyncio
import uuid
import zipfile
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from pipeline import step0_classifier, step1_req_extractor, step2_obvious_generator, step3_implied_generator
from storage.job_store import add_step_result, create_job, get_job, update_job

router = APIRouter()

UPLOAD_DIR = Path("./uploads")


@router.post("/upload")
async def upload_project(
    request: Request,
    background_tasks: BackgroundTasks,
    project_zip: UploadFile = File(...),
    requirements: str = Form(""),
    use_requirements_box: bool = Form(True),
    use_readme: bool = Form(True),
    use_spec_files: bool = Form(False),
):
    if not project_zip.filename or not project_zip.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")
    if not use_requirements_box and not use_readme and not use_spec_files:
        raise HTTPException(status_code=400, detail="At least one input source must be selected")

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
            "use_requirements_box": use_requirements_box,
            "use_readme": use_readme,
            "use_spec_files": use_spec_files,
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

        step0_result = await step0_classifier.run(extract_to, client)
        add_step_result(job_id, "step_0", step0_result)
        update_job(job_id, {"status": "running", "current_step": 1})

        job = get_job(job_id)
        step1_result = await step1_req_extractor.run(
            job["requirements_text"], extract_to, client,
            use_requirements_box=job.get("use_requirements_box", True),
            use_readme=job.get("use_readme", True),
            use_spec_files=job.get("use_spec_files", False),
        )
        add_step_result(job_id, "step_1", step1_result)
        update_job(job_id, {"status": "running", "current_step": 2})

        step2_result = await step2_obvious_generator.run(
            step1_result["requirements"], step0_result, client
        )
        add_step_result(job_id, "step_2", step2_result)
        update_job(job_id, {"status": "running", "current_step": 3})

        step3_result = await step3_implied_generator.run(
            step1_result["requirements"],
            step2_result["requirements"],
            step0_result,
            client,
            project_summary=step1_result.get("project_summary", ""),
        )
        add_step_result(job_id, "step_3", step3_result)
        update_job(job_id, {"status": "waiting_for_confirmation", "current_step": 3})
    except Exception as e:
        update_job(job_id, {"status": "error", "errors": [str(e)]})


def _extract_zip(zip_path: Path, extract_to: Path) -> None:
    extract_to.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)
