"""Workint skills-gap API — endpoints for the frontend:

  POST /skills-gap/analyze-cv             Flow 1: upload a PDF -> extractor -> gap
  POST /skills-gap/analyze-worker/{id}    Flow 2: stored CV from `workers` table -> gap
  POST /skills-gap/recommend-cv           Flow 1 source -> ranked career-transition targets
  POST /skills-gap/recommend-worker/{id}  Flow 2 source -> ranked career-transition targets

analyze-* compare the worker to ONE target job's ESCO + CP2021 benchmark (app/gap.analyze);
recommend-* rank ALL benchmark jobs by skill reachability x demand growth (app/recommend).
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .gap import TargetNotFound, analyze, _category_index, _load_emb_store
from .models import GapResult, RecommendationResult
from .recommend import recommend
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
    from .courses import _course_index
    from .recommend import _benchmark_skill_index
    model()
    _load_emb_store()
    _category_index()
    _benchmark_skill_index()
    _course_index()
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


def _extract_profile(file: UploadFile):
    """Shared Flow-1 source: PDF -> extractor -> WorkerProfile (raises HTTP 502/422)."""
    try:
        extracted = call_extractor(file.file.read(), filename=file.filename or "cv.pdf")
    except ExtractorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not isinstance(extracted, dict):
        raise HTTPException(status_code=502, detail="Unexpected extractor response (expected JSON object).")
    profile = profile_from_extracted(extracted)
    if not profile.skills:
        raise HTTPException(status_code=422, detail="No skills parsed from the extractor output.")
    return profile


@app.post("/skills-gap/analyze-cv", response_model=GapResult)
def analyze_cv(
    file: UploadFile = File(..., description="CV in PDF format"),
    target_category_id: Optional[int] = Query(None),
    target_job_category: Optional[str] = Query(None, description="Target job; falls back to the CV's role"),
) -> GapResult:
    """Flow 1: proxy the uploaded PDF to the external extractor, parse its output, return gap."""
    profile = _extract_profile(file)
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


@app.post("/skills-gap/recommend-cv", response_model=RecommendationResult)
def recommend_cv(
    file: UploadFile = File(..., description="CV in PDF format"),
    current_job: Optional[str] = Query(None, description="Worker's current job; falls back to the CV's role"),
    k: int = Query(10, ge=1, le=50, description="How many target jobs to return"),
) -> RecommendationResult:
    """Career transition from a PDF CV: rank all benchmark jobs by reachability x demand growth."""
    profile = _extract_profile(file)
    return recommend(profile.skills, current_job=current_job or profile.role, k=k)


@app.post("/skills-gap/recommend-worker/{worker_id}", response_model=RecommendationResult)
def recommend_worker(
    worker_id: int,
    k: int = Query(10, ge=1, le=50, description="How many target jobs to return"),
) -> RecommendationResult:
    """Career transition for a stored worker: rank all benchmark jobs by reachability x demand growth."""
    try:
        profile, target_job = load_worker(worker_id)
    except WorkersSchemaUnknown as e:
        raise HTTPException(status_code=501, detail=str(e))
    except WorkerNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not profile.skills:
        raise HTTPException(status_code=422, detail="Worker has no skills to analyze.")
    return recommend(profile.skills, current_job=target_job or profile.role, k=k)
