"""Course suggestions for missing skills — the "what should I study" piece.

Matching is semantic (mpnet cosine between the ESCO skill label and the course's
title+description), so the catalog stays free text: no manual skill-course mapping.
The `course` table is loaded by scripts/load_courses.py; when it's missing or empty
this degrades to no suggestions (analyze keeps working).

We only suggest a (skill, course) pair above MIN_COURSE_SIM — a weak match like
"corso di fotografia" for "contabilità" is worse than no suggestion.
"""
import logging
from functools import lru_cache

import numpy as np
from sqlalchemy import text

from .config import engine
from .gap import _encode
from .models import CourseSuggestion, SkillCourses

log = logging.getLogger(__name__)

MIN_COURSE_SIM = 0.55    # smoke-calibrated: genuine matches sit 0.74-0.90, noise at <=0.53
MAX_SKILLS = 5           # suggest courses for at most this many missing skills
PER_SKILL = 2            # courses per skill


@lru_cache(maxsize=1)
def _course_index():
    """All courses + one embedding per course over 'title. description'. Tolerates a
    missing/empty table (returns no courses). Cached; restart to reload the catalog."""
    try:
        with engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT title, provider, url, description, hours FROM course ORDER BY course_id"
            )).mappings().all()
    except Exception:
        log.warning("course table unavailable; no course suggestions")
        return [], np.empty((0, 0))
    courses = [dict(r) for r in rows]
    texts = tuple(f"{c['title']}. {c['description'] or ''}".strip() for c in courses)
    emb = _encode(texts) if texts else np.empty((0, 0))
    log.info("course index: %d courses", len(courses))
    return courses, emb


def suggest_courses(missing_skills: list[str], max_skills: int = MAX_SKILLS,
                    per_skill: int = PER_SKILL) -> list[SkillCourses]:
    """For the missing skills with the best available training, the top matching courses.
    Skills whose best course is below MIN_COURSE_SIM are dropped (no weak suggestions);
    the result is ordered by match quality, at most `max_skills` entries."""
    courses, emb = _course_index()
    if not missing_skills or not courses:
        return []
    sims = _encode(tuple(missing_skills)) @ emb.T      # (n_skills, n_courses)

    scored = []
    for i, skill in enumerate(missing_skills):
        order = np.argsort(-sims[i])[:per_skill]
        picks = [
            CourseSuggestion(
                title=courses[j]["title"], provider=courses[j]["provider"],
                url=courses[j]["url"], hours=courses[j]["hours"],
                score=round(float(sims[i][j]), 3),
            )
            for j in order if sims[i][j] >= MIN_COURSE_SIM
        ]
        if picks:
            scored.append(SkillCourses(skill=skill, courses=picks))
    scored.sort(key=lambda sc: sc.courses[0].score, reverse=True)
    return scored[:max_skills]
