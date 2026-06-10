"""Tests for the career-transition recommender (pure scoring + mocked-index ranking)."""
import numpy as np
import pytest

import app.recommend as rec
from app.recommend import _combined_score, _trend_score


class TestTrendScore:
    def test_none_is_neutral(self):
        assert _trend_score(None) == 0.5

    def test_zero_growth_is_neutral(self):
        assert _trend_score(0.0) == 0.5

    def test_plus_100_maps_to_1(self):
        assert _trend_score(100.0) == 1.0

    def test_minus_100_maps_to_0(self):
        assert _trend_score(-100.0) == 0.0

    def test_extreme_growth_is_clipped(self):
        assert _trend_score(500.0) == 1.0
        assert _trend_score(-500.0) == 0.0


class TestCombinedScore:
    def test_full_coverage_full_growth_is_1(self):
        assert _combined_score(100.0, 100.0) == 1.0

    def test_zero_coverage_scores_zero_whatever_the_growth(self):
        # Demand gates reachability multiplicatively: an unreachable job never ranks.
        assert _combined_score(0.0, None) == 0.0
        assert _combined_score(0.0, 999.0) == 0.0

    def test_unreachable_boom_never_outranks_reachable_decline(self):
        assert _combined_score(40.0, -100.0) > _combined_score(8.0, 999.0)

    def test_demand_factor_range_is_half_to_full(self):
        assert _combined_score(100.0, -100.0) == pytest.approx(0.5)   # worst demand halves
        assert _combined_score(100.0, None) == pytest.approx(0.75)    # neutral


@pytest.fixture
def fake_index(monkeypatch):
    """3 categories over unique labels [a, b, c] with orthogonal embeddings, so a worker
    knowing 'a' covers exactly the labels named 'a'. No DB, no model."""
    cats = [
        {"id": 1, "label": "Current Job",   "skills": ["a", "b"], "idxs": np.array([0, 1])},
        {"id": 2, "label": "Growing Job",   "skills": ["a", "c"], "idxs": np.array([0, 2])},
        {"id": 3, "label": "Declining Job", "skills": ["a", "c"], "idxs": np.array([0, 2])},
    ]
    emb = np.eye(3, dtype=np.float32)
    vecs = {"a": [1.0, 0, 0], "b": [0, 1.0, 0], "c": [0, 0, 1.0]}
    monkeypatch.setattr(rec, "_benchmark_skill_index", lambda: (cats, emb))
    monkeypatch.setattr(rec, "_load_trends", lambda: {1: -30.0, 2: 50.0, 3: -50.0})
    monkeypatch.setattr(rec, "_encode",
                        lambda texts: np.array([vecs[t] for t in texts], dtype=np.float32))
    monkeypatch.setattr(rec, "resolve_category", lambda _: (1, "Current Job", 1.0))


class TestRecommend:
    def test_growing_job_outranks_declining_at_equal_coverage(self, fake_index):
        r = rec.recommend(["a"], current_job="whatever")
        labels = [it.job_category for it in r.recommendations]
        assert labels.index("Growing Job") < labels.index("Declining Job")

    def test_current_job_is_excluded_and_its_trend_reported(self, fake_index):
        r = rec.recommend(["a"], current_job="whatever")
        assert all(it.job_category != "Current Job" for it in r.recommendations)
        assert r.current_job_category == "Current Job"
        assert r.current_growth_pct == -30.0

    def test_coverage_and_missing_preview(self, fake_index):
        r = rec.recommend(["a"], current_job="whatever")
        growing = next(it for it in r.recommendations if it.job_category == "Growing Job")
        assert growing.coverage_pct == 50.0
        assert growing.n_covered == 1 and growing.n_total == 2
        assert growing.missing_preview == ["c"]      # covered 'a' is not in the preview
        assert growing.growth_pct == 50.0

    def test_no_current_job_keeps_all_categories(self, fake_index):
        r = rec.recommend(["a"], current_job=None)
        assert len(r.recommendations) == 3
        assert r.current_category_id is None and r.current_growth_pct is None

    def test_k_truncates(self, fake_index):
        assert len(rec.recommend(["a"], current_job=None, k=1).recommendations) == 1

    def test_scores_match_formula(self, fake_index):
        r = rec.recommend(["a"], current_job="whatever")
        growing = next(it for it in r.recommendations if it.job_category == "Growing Job")
        # coverage 0.5 * demand factor (0.5 + 0.5 * 0.75) = 0.4375 -> rounded 0.438
        assert growing.score == pytest.approx(0.438)
