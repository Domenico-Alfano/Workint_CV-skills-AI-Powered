"""Tests for the gap engine.

`_labels` is a pure function (fast). The `resolve_category` / `analyze` tests are marked
`integration`: they need the local DB up and the mpnet model, and skip gracefully otherwise.
"""
import json

import pytest

from app.gap import _labels


class TestLabels:
    def test_list_of_dicts(self):
        assert _labels([{"label": "Python"}, {"label": "SQL"}]) == ["Python", "SQL"]

    def test_json_string_is_parsed(self):
        assert _labels(json.dumps([{"label": "Python"}])) == ["Python"]

    def test_none_yields_empty(self):
        assert _labels(None) == []

    def test_empty_string_yields_empty(self):
        assert _labels("") == []

    def test_dicts_without_label_are_filtered(self):
        assert _labels([{"label": "Python"}, {"foo": "bar"}, {"label": ""}]) == ["Python"]


@pytest.fixture(scope="session")
def _index_ready():
    """Skip integration tests unless the DB + model are actually available."""
    from app.gap import _category_index
    try:
        ids, labels, emb = _category_index()
    except Exception as e:  # DB down (Docker asleep) or model not downloaded
        pytest.skip(f"benchmark index unavailable: {e}")
    if not ids:
        pytest.skip("benchmark is empty")
    return ids, labels, emb


@pytest.mark.integration
def test_synonym_resolves_sviluppatore(_index_ready):
    from app.gap import resolve_category
    cid, label, score = resolve_category("Sviluppatore Python senior")
    assert label == "Software Developer"
    assert score == 1.0  # synonym pass => exact confidence


@pytest.mark.integration
def test_analyze_returns_populated_esco_gap(_index_ready, monkeypatch):
    import app.config
    monkeypatch.setattr(app.config, "LLM_ENABLED", False)  # no network in tests
    from app.gap import analyze
    result = analyze(
        worker_skills=["Python", "SQL", "Docker", "Java"],
        job_category="Sviluppatore",
    )
    assert result.job_category == "Software Developer"
    assert result.esco.n_total > 0
    assert 0.0 <= result.esco.coverage_pct <= 100.0
    assert result.report is None  # LLM disabled


@pytest.mark.integration
def test_cp2021_threshold_suppresses_proper_noun_false_positives(_index_ready, monkeypatch):
    """A tech CV must NOT 'cover' physical CP2021 competences via proper-noun noise
    (e.g. "Java" matching "Resistenza"/"Forza del busto" at ~0.62-0.67)."""
    import app.config
    monkeypatch.setattr(app.config, "LLM_ENABLED", False)
    from app.gap import analyze
    result = analyze(worker_skills=["Python", "Java", "SQL", "Docker"], job_category="Sviluppatore")
    covered_cp = {m.skill.lower() for m in result.cp2021.covered}
    assert "resistenza" not in covered_cp
    assert "forza del busto" not in covered_cp
