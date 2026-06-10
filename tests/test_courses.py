"""Tests for course suggestions (mocked index + encode; no DB, no model)."""
import numpy as np
import pytest

import app.courses as courses_mod
from app.courses import suggest_courses


@pytest.fixture
def fake_catalog(monkeypatch):
    """3 courses on orthogonal-ish axes; skills are unit vectors so similarities are
    exactly the embedding components we set."""
    catalog = [
        {"title": "Corso Cucina", "provider": "P", "url": None, "description": "", "hours": 10},
        {"title": "Corso Python", "provider": "P", "url": None, "description": "", "hours": 20},
        {"title": "Corso Vendite", "provider": "P", "url": None, "description": "", "hours": 30},
    ]
    emb = np.eye(3, dtype=np.float32)
    vecs = {
        "cucinare":  [0.9, 0.0, 0.0],      # strong cucina match
        "saldatura": [0.3, 0.2, 0.1],      # nothing good -> dropped
        "python":    [0.0, 0.99, 0.6],     # python strong, vendite above floor
    }
    monkeypatch.setattr(courses_mod, "_course_index", lambda: (catalog, emb))
    monkeypatch.setattr(courses_mod, "_encode",
                        lambda texts: np.array([vecs[t] for t in texts], dtype=np.float32))


class TestSuggestCourses:
    def test_strong_match_is_suggested(self, fake_catalog):
        out = suggest_courses(["cucinare"])
        assert len(out) == 1
        assert out[0].skill == "cucinare"
        assert out[0].courses[0].title == "Corso Cucina"
        assert out[0].courses[0].score == pytest.approx(0.9)

    def test_skill_without_decent_course_is_dropped(self, fake_catalog):
        assert suggest_courses(["saldatura"]) == []

    def test_results_ordered_by_best_match_and_capped(self, fake_catalog):
        out = suggest_courses(["cucinare", "python"], max_skills=1)
        assert len(out) == 1
        assert out[0].skill == "python"          # 0.99 beats 0.9

    def test_per_skill_cap_and_floor(self, fake_catalog):
        out = suggest_courses(["python"], per_skill=2)
        titles = [c.title for c in out[0].courses]
        assert titles == ["Corso Python", "Corso Vendite"]   # 0.99 and 0.6, both >= 0.55
        out1 = suggest_courses(["python"], per_skill=1)
        assert [c.title for c in out1[0].courses] == ["Corso Python"]

    def test_empty_inputs(self, fake_catalog, monkeypatch):
        assert suggest_courses([]) == []
        monkeypatch.setattr(courses_mod, "_course_index", lambda: ([], np.empty((0, 0))))
        assert suggest_courses(["cucinare"]) == []
