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


class Report(BaseModel):
    strengths: str = Field(description="Paragraph on the worker's strengths vs the target role.")
    gaps: str = Field(description="Paragraph on the main skill gaps.")
    formation: list[str] = Field(description="2-4 concrete training/certification suggestions.")


class GapResult(BaseModel):
    category_id: int
    job_category: str
    target_confidence: Optional[float] = None  # <1.0 = fuzzy-resolved; None = exact match
    n_worker_skills: int
    esco: BenchmarkGap
    cp2021: BenchmarkGap
    report: Optional[Report] = None  # None if LLM_API_KEY not set
