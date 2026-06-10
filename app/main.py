"""Workint skills-gap API — endpoints for the frontend:

  POST /skills-gap/analyze-cv             Flow 1: upload a PDF -> extractor -> gap
  POST /skills-gap/analyze-worker/{id}    Flow 2: stored CV from `workers` table -> gap
  POST /skills-gap/recommend-cv           Flow 1 source -> ranked career-transition targets
  POST /skills-gap/recommend-worker/{id}  Flow 2 source -> ranked career-transition targets

analyze-* compare the worker to ONE target job's ESCO + CP2021 benchmark (app/gap.analyze);
recommend-* rank ALL benchmark jobs by skill reachability x demand growth (app/recommend).
"""
import hashlib
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader

from . import config
from .config import CORS_ORIGINS
from .gap import TargetNotFound, analyze, _category_index, _load_emb_store
from .models import GapResult, RecommendationResult, WorkerProfile
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

_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


def require_api_key(key: Optional[str] = Security(_api_key_header)) -> None:
    """No-op when API_KEY is unset (dev / trusted LAN); 401 on mismatch otherwise.
    Read from config at call time so tests can monkeypatch it."""
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid API key (x-api-key header).")


# All business endpoints live under /skills-gap and share the API-key guard;
# /health stays open for load-balancer liveness probes.
router = APIRouter(prefix="/skills-gap", dependencies=[Security(require_api_key)])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/reload-courses")
def reload_courses() -> dict:
    """Re-read the `course` table after a catalog load (scripts/load_courses.py) without
    restarting the server. Cheap: course embeddings are memoized per text in the store."""
    from .courses import _course_index
    _course_index.cache_clear()
    courses, _ = _course_index()
    return {"status": "ok", "courses": len(courses)}


def _run(skills: list[str], category_id: Optional[int], job_category: Optional[str]) -> GapResult:
    try:
        return analyze(worker_skills=skills, category_id=category_id, job_category=job_category)
    except TargetNotFound as e:
        # Carry best-guess categories so the FE can show a "did you mean…?" picker;
        # the user re-submits with target_category_id.
        raise HTTPException(
            status_code=404, detail={"message": str(e), "candidates": e.candidates}
        )


# Extraction cache keyed on PDF content hash. The recommended FE flow uploads the SAME
# file twice (recommend-cv, then analyze-cv on the chosen target): the extractor costs
# ~7s per call, the cache makes the second one instant. Bounded LRU; failures not cached.
_EXTRACT_CACHE: "OrderedDict[str, WorkerProfile]" = OrderedDict()
_EXTRACT_CACHE_MAX = 64


def _extract_profile(file: UploadFile) -> WorkerProfile:
    """Shared Flow-1 source: PDF -> extractor -> WorkerProfile (raises HTTP 502/422)."""
    content = file.file.read()
    digest = hashlib.md5(content).hexdigest()
    if digest in _EXTRACT_CACHE:
        _EXTRACT_CACHE.move_to_end(digest)
        return _EXTRACT_CACHE[digest]
    try:
        extracted = call_extractor(content, filename=file.filename or "cv.pdf")
    except ExtractorError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not isinstance(extracted, dict):
        raise HTTPException(status_code=502, detail="Unexpected extractor response (expected JSON object).")
    profile = profile_from_extracted(extracted)
    if not profile.skills:
        raise HTTPException(status_code=422, detail="No skills parsed from the extractor output.")
    _EXTRACT_CACHE[digest] = profile
    if len(_EXTRACT_CACHE) > _EXTRACT_CACHE_MAX:
        _EXTRACT_CACHE.popitem(last=False)
    return profile


@router.post("/analyze-cv", response_model=GapResult)
def analyze_cv(
    file: UploadFile = File(..., description="CV in PDF format"),
    target_category_id: Optional[int] = Query(None),
    target_job_category: Optional[str] = Query(None, description="Target job; falls back to the CV's role"),
) -> GapResult:
    """Flow 1: proxy the uploaded PDF to the external extractor, parse its output, return gap."""
    profile = _extract_profile(file)
    return _run(profile.skills, target_category_id, target_job_category or profile.role)


@router.post("/analyze-worker/{worker_id}", response_model=GapResult)
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


@router.post("/recommend-cv", response_model=RecommendationResult)
def recommend_cv(
    file: UploadFile = File(..., description="CV in PDF format"),
    current_job: Optional[str] = Query(None, description="Worker's current job; falls back to the CV's role"),
    k: int = Query(10, ge=1, le=50, description="How many target jobs to return"),
) -> RecommendationResult:
    """Career transition from a PDF CV: rank all benchmark jobs by reachability x demand growth."""
    profile = _extract_profile(file)
    return recommend(profile.skills, current_job=current_job or profile.role, k=k)


@router.post("/recommend-worker/{worker_id}", response_model=RecommendationResult)
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


app.include_router(router)
