import os

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="ISO 25010 Functional Suitability Evaluator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    app.state.anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)


from api.routes import jobs, upload  # noqa: E402

app.include_router(upload.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
