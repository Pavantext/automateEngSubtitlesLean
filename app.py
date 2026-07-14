#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — FastAPI backend + static web UI for the subtitle review pipeline.

Auth: a single shared password (env APP_PASSWORD). Clients send it as
`X-App-Password`. This is lightweight gatekeeping for a private/team tool,
not enterprise auth — always serve over HTTPS (Render does this for you).

Endpoints:
    GET  /                       -> web UI
    GET  /healthz                -> liveness (no auth)
    POST /api/login              -> validate password
    POST /api/jobs               -> upload subtitle, start translation job
    GET  /api/jobs/{id}          -> job status + progress log
    GET  /api/jobs/{id}/files/{artifact}  -> download brief|workbook|raw
"""

from __future__ import annotations

import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import pipeline

load_dotenv()
load_dotenv(".env.local")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

APP_PASSWORD = os.getenv("APP_PASSWORD", "")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))  # 2 MB

ARTIFACT_KEYS = {"brief", "workbook", "raw"}

app = FastAPI(title="Telugu Subtitle Review Pipeline")


# --------------------------------------------------------------------------- #
# Job store (in-memory; artifacts on disk)
# --------------------------------------------------------------------------- #
@dataclass
class Job:
    id: str
    filename: str
    status: str = "queued"  # queued | running | done | error
    progress: List[str] = field(default_factory=list)
    error: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)  # key -> abs path
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def public(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "artifacts": sorted(self.artifacts.keys()),
            "created_at": self.created_at,
        }


JOBS: Dict[str, Job] = {}
_LOCK = threading.Lock()


def _run_job(job: Job, source_text: str, chunk_size: int, overlap: int, model: Optional[str]) -> None:
    def progress(msg: str) -> None:
        with _LOCK:
            job.progress.append(msg)

    try:
        with _LOCK:
            job.status = "running"
        skill_text = pipeline.load_skill_text(None)
        out_dir = JOBS_DIR / job.id
        artifacts = pipeline.translate_to_files(
            source_text=source_text,
            source_name=job.filename,
            out_dir=out_dir,
            skill_text=skill_text,
            model=model,
            chunk_size=chunk_size,
            overlap=overlap,
            progress=progress,
        )
        with _LOCK:
            job.artifacts = {k: str(v) for k, v in artifacts.items()}
            job.status = "done"
    except Exception as err:  # surface failure to the UI
        with _LOCK:
            job.error = str(err)
            job.status = "error"
            job.progress.append(f"ERROR: {err}")


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def require_password(x_app_password: str = Header(default="")) -> None:
    if not APP_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Server not configured: APP_PASSWORD is not set.",
        )
    if not secrets.compare_digest(x_app_password, APP_PASSWORD):
        raise HTTPException(status_code=401, detail="Invalid password.")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "configured": bool(APP_PASSWORD)}


@app.post("/api/login")
def login(_: None = Depends(require_password)) -> dict:
    return {"ok": True}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile,
    chunk_size: int = Form(pipeline.DEFAULT_CHUNK_SIZE),
    overlap: int = Form(pipeline.DEFAULT_OVERLAP),
    model: str = Form(""),
    _: None = Depends(require_password),
) -> JSONResponse:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        source_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text (.sbv/.srt).")

    # Fail fast on unparseable input before spawning a job.
    try:
        cues = pipeline.parse_source_text(source_text)
        if not cues:
            raise ValueError("No subtitle cues found.")
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Could not parse subtitle file: {err}")

    job = Job(id=uuid.uuid4().hex, filename=file.filename or "subtitle.sbv")
    with _LOCK:
        JOBS[job.id] = job

    threading.Thread(
        target=_run_job,
        args=(job, source_text, chunk_size, overlap, model or None),
        daemon=True,
    ).start()

    return JSONResponse(status_code=202, content={**job.public(), "cue_count": len(cues)})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(require_password)) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.public()


@app.get("/api/jobs/{job_id}/files/{artifact}")
def download_artifact(
    job_id: str, artifact: str, _: None = Depends(require_password)
) -> FileResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if artifact not in ARTIFACT_KEYS or artifact not in job.artifacts:
        raise HTTPException(status_code=404, detail="Artifact not available.")
    path = Path(job.artifacts[artifact])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on server.")
    return FileResponse(path, filename=path.name)


# Serve the web UI (index.html) and static assets at the root.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
