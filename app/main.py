"""Workint skills-gap API — two endpoints for the frontend:

  POST /skills-gap/analyze-cv           Flow 1: upload a PDF -> extractor -> gap
  POST /skills-gap/analyze-worker/{id}  Flow 2: stored CV from `workers` table -> gap

Both converge on the deterministic gap engine (app/gap.analyze), comparing the worker's
skills to the target job's ESCO + CP2021 benchmark.
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .gap import TargetNotFound, analyze, _category_index, _load_emb_store
from .models import GapResult
from .sources import (
    ExtractorError,
    WorkerNotFound,
    WorkersSchemaUnknown,
    call_extractor,
    load_worker,
    profile_from_extracted,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm: load model, the precomputed label embeddings, and the category index so
    # the first real request is fast even right after a restart.
    from .config import model
    model()
    _load_emb_store()
    _category_index()
    yield


app = FastAPI(
    title="Workint Skills-Gap API",
    version="0.1.0",
    description="Compare a worker (PDF CV or stored worker) to a job's ESCO + CP2021 benchmark.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _run(skills: list[str], category_id: Optional[int], job_category: Optional[str]) -> GapResult:
    try:
        return analyze(worker_skills=skills, category_id=category_id, job_category=job_category)
    except TargetNotFound as e:
        # Carry best-guess categories so the FE can show a "did you mean…?" picker;
        # the user re-submits with target_category_id.
        raise HTTPException(
            status_code=404, detail={"message": str(e), "candidates": e.candidates}
        )


@app.post("/skills-gap/analyze-cv", response_model=GapResult)
def analyze_cv(
    file: UploadFile = File(..., description="CV in PDF format"),
    target_category_id: Optional[int] = Query(None),
    target_job_category: Optional[str] = Query(None, description="Target job; falls back to the CV's role"),
) -> GapResult:
    """Flow 1: proxy the uploaded PDF to the external extractor, parse its markdown, return gap."""
    try:
        extracted = call_extractor(file.file.read(), filename=file.filename or "cv.pdf")
    except ExtractorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not isinstance(extracted, dict):
        raise HTTPException(status_code=502, detail="Unexpected extractor response (expected JSON object).")
    profile = profile_from_extracted(extracted)
    if not profile.skills:
        raise HTTPException(status_code=422, detail="No skills parsed from the extractor output.")
    return _run(profile.skills, target_category_id, target_job_category or profile.role)


@app.post("/skills-gap/analyze-worker/{worker_id}", response_model=GapResult)
def analyze_worker(worker_id: int) -> GapResult:
    """Flow 2: read the stored worker's profile from `workers` and return the gap."""
    try:
        profile, target_job = load_worker(worker_id)
    except WorkersSchemaUnknown as e:
        raise HTTPException(status_code=501, detail=str(e))
    except WorkerNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not profile.skills:
        raise HTTPException(status_code=422, detail="Worker has no skills to analyze.")
    if not target_job:
        raise HTTPException(status_code=422, detail="Worker has no preferred/current job; cannot pick a target benchmark.")
    return _run(profile.skills, None, target_job)
