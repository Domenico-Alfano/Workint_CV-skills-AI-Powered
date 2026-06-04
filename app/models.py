"""Pydantic request/response models — the contract the frontend codes against."""
from typing import Optional

from pydantic import BaseModel, Field


class WorkerProfile(BaseModel):
    """Structured worker profile. `skills` drives the gap; the rest is captured for later
    (education/experience/language comparison is not benchmarked yet — see DESIGN_NOTES §19)."""
    skills: list[str] = Field(default_factory=list, description="Skill labels (free text).")
    role: Optional[str] = Field(None, description="Worker's stated role/title.")
    experience: Optional[str] = None
    education: Optional[str] = None
    languages: list[str] = Field(default_factory=list)


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


class GapResult(BaseModel):
    category_id: int
    job_category: str
    n_worker_skills: int
    esco: BenchmarkGap
    cp2021: BenchmarkGap
