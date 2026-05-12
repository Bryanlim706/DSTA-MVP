import os
import ssl

import anthropic
import httpx
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
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    http_client = httpx.AsyncClient(verify=False)
    app.state.anthropic_client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client)


from api.routes import jobs, upload  # noqa: E402

app.include_router(upload.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
