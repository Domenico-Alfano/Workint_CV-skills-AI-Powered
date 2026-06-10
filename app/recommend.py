"""Career-transition recommender: rank ALL benchmark jobs by how reachable they are
from the worker's current skills, weighted by posting-demand growth.

Reachability is the same deterministic signal as the gap engine (cosine over mpnet
embeddings vs the job's ESCO skills — CP2021 is excluded: transversal competences
don't discriminate between targets). Demand comes from `category_trend` (built by
scripts/compute_trends.py); when absent the trend weight degrades to neutral, so the
endpoint still works on a benchmark-only DB.

Cheap by construction: every benchmark label is already in the precomputed .npz
(gap._EMB_STORE), so scoring 306 categories is a single matrix multiplication.
"""
import json
import logging
from functools import lru_cache

import numpy as np
from sqlalchemy import text

from .config import COVER_THRESHOLD, engine
from .gap import _encode, _labels, resolve_category
from .models import RecommendationItem, RecommendationResult

log = logging.getLogger(__name__)

MISSING_PREVIEW_N = 8


def _trend_score(growth_pct: float | None) -> float:
    """Map demand growth % to [0, 1] for ranking: -100% -> 0, 0% -> 0.5, +100% -> 1.
    Unknown trend is neutral (0.5) so missing data neither boosts nor buries a job."""
    if growth_pct is None:
        return 0.5
    return 0.5 + max(-100.0, min(100.0, growth_pct)) / 200.0


def _combined_score(coverage_pct: float, growth_pct: float | None) -> float:
    """Reachability GATED by demand (multiplicative, not additive): coverage scaled by a
    demand factor in [0.5, 1.0]. A booming job the worker can't reach must not outrank a
    reachable one — additive scoring let 999%-growth micro-categories dominate the top-k."""
    demand_factor = 0.5 + 0.5 * _trend_score(growth_pct)
    return round((coverage_pct / 100.0) * demand_factor, 3)


@lru_cache(maxsize=1)
def _benchmark_skill_index():
    """All benchmark categories with their ESCO labels, plus one embedding matrix over the
    UNIQUE labels (many skills recur across jobs). Cached like gap._category_index."""
    with engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT category_id, job_category, essential_skills, optional_skills "
            "FROM job_benchmark ORDER BY category_id"
        )).all()
    label_idx: dict[str, int] = {}
    cats = []
    for cid, job_cat, ess, opt in rows:
        labels = _labels(ess) + _labels(opt)
        idxs = []
        for lbl in labels:
            if lbl not in label_idx:
                label_idx[lbl] = len(label_idx)
            idxs.append(label_idx[lbl])
        cats.append({"id": cid, "label": job_cat, "skills": labels, "idxs": np.array(idxs)})
    unique_labels = list(label_idx)
    emb = _encode(tuple(unique_labels)) if unique_labels else np.empty((0, 0))
    log.info("benchmark skill index: %d categories, %d unique labels", len(cats), len(unique_labels))
    return cats, emb


@lru_cache(maxsize=1)
def _load_trends() -> dict[int, float]:
    """category_id -> growth_pct. Tolerates a missing/empty table (returns {})."""
    try:
        with engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT category_id, growth_pct FROM category_trend WHERE growth_pct IS NOT NULL"
            )).all()
        return {int(r[0]): float(r[1]) for r in rows}
    except Exception:
        log.warning("category_trend unavailable; recommendations use neutral trend")
        return {}


def recommend(worker_skills: list[str], current_job: str | None = None,
              k: int = 10) -> RecommendationResult:
    worker_skills = [s.strip() for s in worker_skills if s and s.strip()]
    cats, emb = _benchmark_skill_index()
    trends = _load_trends()

    # Resolve the worker's current job so we can (a) report its own demand trend and
    # (b) exclude it from the suggestions. Resolution failure is fine — just skip both.
    current_id = current_label = None
    if current_job:
        current_id, current_label, _ = resolve_category(current_job)

    w = _encode(tuple(worker_skills))
    # Best similarity of each unique benchmark label against any worker skill.
    best = (emb @ w.T).max(axis=1) if len(worker_skills) and emb.size else np.zeros(emb.shape[0])

    items = []
    for cat in cats:
        if cat["id"] == current_id or not len(cat["idxs"]):
            continue
        sims = best[cat["idxs"]]
        covered_mask = sims >= COVER_THRESHOLD
        n_total = len(sims)
        n_covered = int(covered_mask.sum())
        coverage = 100.0 * n_covered / n_total
        growth = trends.get(cat["id"])
        # Missing skills the worker is already closest to = cheapest learning targets.
        missing_order = np.argsort(-sims)
        preview = [cat["skills"][j] for j in missing_order if not covered_mask[j]][:MISSING_PREVIEW_N]
        items.append(RecommendationItem(
            category_id=cat["id"], job_category=cat["label"],
            score=_combined_score(coverage, growth),
            coverage_pct=round(coverage, 1), n_covered=n_covered, n_total=n_total,
            growth_pct=growth, missing_preview=preview,
        ))
    items.sort(key=lambda it: it.score, reverse=True)

    result = RecommendationResult(
        n_worker_skills=len(worker_skills),
        current_category_id=current_id,
        current_job_category=current_label,
        current_growth_pct=trends.get(current_id) if current_id is not None else None,
        recommendations=items[:k],
    )
    log.info(
        "recommend: current=%r (growth=%s) n_skills=%d -> top=%s",
        current_label, result.current_growth_pct, len(worker_skills),
        [(it.job_category, it.score) for it in result.recommendations[:3]],
    )
    return result
