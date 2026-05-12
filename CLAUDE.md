# CLAUDE.md — Software Quality Evaluator

Read this file at the start of every session to get full context on the project.

---

## What this project is

A system that evaluates software **Functional Suitability (ISO 25010)** by analysing an uploaded codebase against user-provided requirements. Scores are formula-driven — the LLM only explains results, never overrides them.

See `PLAN.md` for the full pipeline design, 4-layer model, and scoring formulas.

---

## What has been built

### Step 0 — Project Type & Scope Classifier (COMPLETE)
- User uploads a `.zip` of their project + requirements text via the React frontend
- Backend saves the zip, creates a job (JSON file), runs Step 0 in the background
- Rule-based first (config files + extension counts); LLM (claude-haiku, prompt caching) called only when confidence is medium or rules produce no match
- `test_strategy` always formula-derived from `project_type` + `backend_framework` — LLM never overrides it
- Frontend polls `/api/jobs/{job_id}` every 2s until `step_0_complete`, then displays the result
- Job status state machine: `created` → `running` → `step_0_complete` (or `error`)

**Step 0 output fields** (stored in `step_results.step_0`):
```
project_type, frontend_framework, backend_framework,
confidence, reasoning, test_strategy,
config_files_found, llm_used, llm_model
```
`primary_language` is NOT in Step 0 output — Step 1 produces a `languages` array from actual source parsing.

### Frontend (COMPLETE)
- React + TypeScript + Vite + Tailwind CSS
- Upload page: drag-and-drop zip + requirements textarea, file size display, validation
- Loading view: spinner + step name
- Result page: project type, confidence badge, framework pills, reasoning, test strategy, config files found, AI-assisted badge
- Error view: message + retry button

### Backend infrastructure (COMPLETE)
- Python 3.12 + FastAPI
- `POST /api/upload` — validates zip + requirements, creates job, starts background pipeline
- `GET /api/jobs/{job_id}` — returns job JSON
- Job store: one JSON file per job in `./jobs/{job_id}.json`
- Uploads stored in `./uploads/{job_id}/project.zip`

---

## What has NOT been built yet

- Steps 1–16 plus Step −1 handling (see PLAN.md for full pipeline)
- Human confirmation UI (Step 3.5)
- Dashboard (Step 16)
- Docker sandbox (Step 10)

---

## Project structure

```
d:\first-project\
  backend/
    main.py                          # FastAPI entry point (port 8000)
    .env                             # ANTHROPIC_API_KEY, UPLOAD_DIR, JOBS_DIR (not committed)
    .env.example                     # Template
    requirements.txt
    api/
      routes/
        upload.py                    # POST /api/upload
        jobs.py                      # GET /api/jobs/{job_id}
    pipeline/
      step0_classifier.py            # LLM-based project classifier
    storage/
      job_store.py                   # JSON file job persistence
  frontend/
    src/
      api/client.ts                  # uploadProject(), getJob(), pollJob()
      types/index.ts                 # Job, Step0Result, etc.
      pages/UploadPage.tsx           # Upload form
      components/ClassificationResult.tsx  # Step 0 result display
      App.tsx                        # Stage state machine
  uploads/                           # Runtime — gitignored
  jobs/                              # Runtime — gitignored
  PLAN.md
  CLAUDE.md
```

---

## How to run locally

### Backend (port 8000)
```bash
cd d:\first-project\backend
venv\Scripts\activate          # Python 3.12 venv
uvicorn main:app --reload
```

### Frontend (port 5173)
```bash
cd d:\first-project\frontend
npm run dev
```

**npm SSL issue (corporate proxy):** If `npm install` fails with `SELF_SIGNED_CERT_IN_CHAIN`, run:
```bash
npm config set strict-ssl false
npm install
```
Or copy `package-lock.json` from another machine where install succeeded — npm will use it without re-hitting the registry.

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

---

## Key technical decisions

- **AsyncAnthropic** with `cache_control: ephemeral` on system prompt — keeps classification fast and cheap
- **JSON files per job** in `./jobs/` — no database for MVP; easy to inspect and debug
- **Async background task** (FastAPI `BackgroundTasks`) — upload returns immediately with `job_id`, frontend polls
- **Python 3.12 required** — Python 3.14 (pre-release) causes pydantic-core Rust compilation failure on install
- **Formula-driven scores** — LLM never overrides the formula

---

## Git workflow

PAT stored via git credential store. To push:
```bash
cd d:\first-project
git add <files>
git commit -m "describe what you did"
git push origin main
```

Before pushing, check:
- Did the design or formulas change? → Update `PLAN.md`
- Is there new context Claude needs next session? → Update `CLAUDE.md`

---

## Next steps

1. Build Step 1 — Repo Parser (Tree-sitter, file structure extraction, outputs `languages` array)
2. Build Steps 2, 2.5, 3, 3.5 — Stated + Obvious Requirement Extractors, L1b Generator, Human Confirmation UI
