"""Pydantic request/response models — the contract the frontend codes against."""
from typing import Optional

from pydantic import BaseModel, Field


class WorkerProfile(BaseModel):
    """Internal worker profile. `skills` drives the gap; `role` is the target-job fallback.
    (Only these two are used downstream; the benchmark is skill-centric.)"""
    skills: list[str] = Field(default_factory=list, description="Skill labels (free text).")
    role: Optional[str] = Field(None, description="Worker's stated role/title.")


class SkillMatch(BaseModel):
    skill: str
    matched_with: Optional[str] = None  # the worker skill that covered it
    score: float


class BenchmarkGap(BaseModel):
    source: str                    # 'esco' | 'cp2021'
    occupation_label: Optional[str]
    n_total: int
    n_covered: int
    coverage_pct: float
    covered: list[SkillMatch]
    missing: list[str]


class CourseSuggestion(BaseModel):
    title: str
    provider: Optional[str] = None
    url: Optional[str] = None
    hours: Optional[int] = None
    score: float                       # semantic match course <-> skill (0..1)


class SkillCourses(BaseModel):
    """Concrete training for ONE missing skill (best-matching courses first)."""
    skill: str
    courses: list[CourseSuggestion]


class Report(BaseModel):
    strengths: str = Field(description="Paragraph on the worker's strengths vs the target role.")
    gaps: str = Field(description="Paragraph on the main skill gaps.")
    formation: list[str] = Field(description="2-4 concrete training/certification suggestions.")


class RecommendationItem(BaseModel):
    """One candidate target job, ranked by reachability x demand growth."""
    category_id: int
    job_category: str
    score: float                       # combined ranking score (0..1)
    coverage_pct: float                # % of the job's ESCO skills the worker already has
    n_covered: int
    n_total: int
    growth_pct: Optional[float] = None  # posting-demand growth; None = no trend data
    missing_preview: list[str] = Field(
        default_factory=list,
        description="Closest-to-acquire missing skills (best learning targets first).",
    )


class RecommendationResult(BaseModel):
    n_worker_skills: int
    current_category_id: Optional[int] = None    # resolved from the worker's current job
    current_job_category: Optional[str] = None
    current_growth_pct: Optional[float] = None   # demand trend of the CURRENT job
    recommendations: list[RecommendationItem]


class GapResult(BaseModel):
    category_id: int
    job_category: str
    target_confidence: Optional[float] = None  # <1.0 = fuzzy-resolved; None = exact match
    n_worker_skills: int
    esco: BenchmarkGap
    cp2021: BenchmarkGap
    suggested_courses: list[SkillCourses] = Field(
        default_factory=list,
        description="Courses for the best-trainable missing ESCO skills ([] if no catalog).",
    )
    report: Optional[Report] = None  # None if LLM_API_KEY not set
