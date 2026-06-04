"""Deterministic skills-gap engine: worker skills vs a job_benchmark row (ESCO + CP2021).

For each benchmark skill we find the worker's most similar skill (cosine over mpnet
embeddings); it's 'covered' when similarity >= COVER_THRESHOLD, else 'missing'. No LLM.
"""
import json
from functools import lru_cache

import numpy as np
from sqlalchemy import text

from .config import COVER_THRESHOLD, engine, model
from .models import BenchmarkGap, GapResult, SkillMatch

# A free-text target job resolves to a benchmark category when similarity >= this.
RESOLVE_MIN_SCORE = 0.55


class TargetNotFound(Exception):
    pass


@lru_cache(maxsize=1)
def _category_index():
    """Cache (ids, labels, embeddings) of all benchmark job_categories for target resolution."""
    rows = engine().connect().execute(
        text("SELECT category_id, job_category FROM job_benchmark ORDER BY category_id")
    ).all()
    ids = [r[0] for r in rows]
    labels = [r[1] for r in rows]
    emb = model().encode(labels, normalize_embeddings=True)
    return ids, labels, np.asarray(emb)


def resolve_category(job_text: str):
    """Map a free-text job (e.g. 'Cuoca') to the nearest benchmark category_id, or None."""
    ids, labels, emb = _category_index()
    q = model().encode([job_text], normalize_embeddings=True)[0]
    sims = emb @ q
    j = int(np.argmax(sims))
    score = float(sims[j])
    return (ids[j], labels[j], score) if score >= RESOLVE_MIN_SCORE else (None, None, score)


def _labels(jsonb_value) -> list[str]:
    data = jsonb_value if isinstance(jsonb_value, list) else (json.loads(jsonb_value) if jsonb_value else [])
    return [d["label"] for d in data if d.get("label")]


def _load_benchmark(category_id: int | None, job_category: str | None) -> dict:
    select = ("SELECT category_id, job_category, occupation_label_it, essential_skills, "
              "optional_skills, cp2021_label, cp2021_skills FROM job_benchmark WHERE ")

    def _by(where, params):
        return engine().connect().execute(text(select + where), params).mappings().first()

    if category_id is not None:
        row = _by("category_id = :v", {"v": category_id})
        if not row:
            raise TargetNotFound(f"No benchmark for category_id {category_id}.")
        return dict(row)

    if not job_category:
        raise TargetNotFound("Provide target_category_id or target_job_category.")

    # Try exact (case-insensitive) match first, then fall back to nearest-category resolution.
    row = _by("lower(job_category) = lower(:v)", {"v": job_category})
    if row:
        return dict(row)
    cid, label, score = resolve_category(job_category)
    if cid is None:
        raise TargetNotFound(f"No benchmark close to {job_category!r} (best score {score:.2f}).")
    return dict(_by("category_id = :v", {"v": cid}))


def _gap(source: str, occupation_label: str | None, bench_labels: list[str],
         worker_skills: list[str], sims: np.ndarray | None) -> BenchmarkGap:
    covered, missing = [], []
    for i, skill in enumerate(bench_labels):
        if sims is not None and len(worker_skills):
            j = int(np.argmax(sims[i]))
            score = float(sims[i][j])
            if score >= COVER_THRESHOLD:
                covered.append(SkillMatch(skill=skill, matched_with=worker_skills[j],
                                          score=round(score, 3)))
                continue
        missing.append(skill)
    n = len(bench_labels)
    return BenchmarkGap(
        source=source, occupation_label=occupation_label, n_total=n, n_covered=len(covered),
        coverage_pct=round(100.0 * len(covered) / n, 1) if n else 0.0,
        covered=covered, missing=missing,
    )


def analyze(worker_skills: list[str], category_id: int | None = None,
            job_category: str | None = None) -> GapResult:
    bm = _load_benchmark(category_id, job_category)
    esco_labels = _labels(bm["essential_skills"]) + _labels(bm["optional_skills"])
    cp_labels = _labels(bm["cp2021_skills"])

    worker_skills = [s.strip() for s in worker_skills if s and s.strip()]
    all_bench = esco_labels + cp_labels
    if worker_skills and all_bench:
        m = model()
        w = m.encode(worker_skills, normalize_embeddings=True)
        b = m.encode(all_bench, normalize_embeddings=True)
        sims_all = b @ w.T
        esco_sims = sims_all[: len(esco_labels)]
        cp_sims = sims_all[len(esco_labels):]
    else:
        esco_sims = cp_sims = None

    return GapResult(
        category_id=bm["category_id"],
        job_category=bm["job_category"],
        n_worker_skills=len(worker_skills),
        esco=_gap("esco", bm["occupation_label_it"], esco_labels, worker_skills, esco_sims),
        cp2021=_gap("cp2021", bm["cp2021_label"], cp_labels, worker_skills, cp_sims),
    )
