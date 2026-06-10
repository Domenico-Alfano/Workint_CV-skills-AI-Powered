"""HTTP-contract tests: status codes, error shapes, auth, extraction cache.

TestClient WITHOUT the context manager -> lifespan (model/DB pre-warm) never runs;
all heavy dependencies are monkeypatched, so these stay in the fast suite.
"""
import io

import pytest
from fastapi.testclient import TestClient

import app.config
import app.courses
import app.main as main
from app.gap import TargetNotFound
from app.models import (
    BenchmarkGap,
    GapResult,
    RecommendationResult,
    WorkerProfile,
)

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _open_api(monkeypatch):
    """Default: no API key required (a real .env may set one). Auth tests override."""
    monkeypatch.setattr(app.config, "API_KEY", None)


def _gap_result() -> GapResult:
    empty = lambda src: BenchmarkGap(source=src, occupation_label=None, n_total=0,
                                     n_covered=0, coverage_pct=0.0, covered=[], missing=[])
    return GapResult(category_id=1, job_category="X", n_worker_skills=1,
                     esco=empty("esco"), cp2021=empty("cp2021"))


@pytest.fixture
def fake_extract(monkeypatch):
    monkeypatch.setattr(main, "_extract_profile",
                        lambda f: WorkerProfile(skills=["python"], role="dev"))


class TestHealthAndAuth:
    def test_health_is_open_even_with_api_key_set(self, monkeypatch):
        monkeypatch.setattr(app.config, "API_KEY", "s3cret")
        assert client.get("/health").status_code == 200

    def test_missing_key_is_401_when_configured(self, monkeypatch):
        monkeypatch.setattr(app.config, "API_KEY", "s3cret")
        r = client.post("/skills-gap/reload-courses")
        assert r.status_code == 401

    def test_valid_key_passes(self, monkeypatch):
        monkeypatch.setattr(app.config, "API_KEY", "s3cret")
        called = {}

        class FakeIndex:
            def cache_clear(self):
                called["cleared"] = True

            def __call__(self):
                return [], None

        monkeypatch.setattr(app.courses, "_course_index", FakeIndex())
        r = client.post("/skills-gap/reload-courses", headers={"x-api-key": "s3cret"})
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "courses": 0}
        assert called.get("cleared")

    def test_no_key_configured_means_open(self, monkeypatch):
        monkeypatch.setattr(app.config, "API_KEY", None)

        class FakeIndex:
            def cache_clear(self): pass
            def __call__(self): return [], None

        monkeypatch.setattr(app.courses, "_course_index", FakeIndex())
        assert client.post("/skills-gap/reload-courses").status_code == 200


class TestAnalyzeCvContract:
    def test_target_not_found_is_404_with_candidates(self, fake_extract, monkeypatch):
        cands = [{"category_id": 3, "job_category": "Cuoco", "score": 0.41}]

        def boom(**kwargs):
            raise TargetNotFound("nope", candidates=cands)

        monkeypatch.setattr(main, "analyze", boom)
        r = client.post("/skills-gap/analyze-cv?target_job_category=xyz",
                        files={"file": ("cv.pdf", b"%PDF-fake", "application/pdf")})
        assert r.status_code == 404
        detail = r.json()["detail"]
        assert detail["message"] == "nope"
        assert detail["candidates"] == cands   # the FE "did you mean" picker contract

    def test_happy_path_returns_gap_result(self, fake_extract, monkeypatch):
        monkeypatch.setattr(main, "analyze", lambda **kw: _gap_result())
        r = client.post("/skills-gap/analyze-cv",
                        files={"file": ("cv.pdf", b"%PDF-fake", "application/pdf")})
        assert r.status_code == 200
        body = r.json()
        assert body["job_category"] == "X"
        assert body["suggested_courses"] == [] and body["report"] is None


class TestRecommendContract:
    def test_k_is_validated(self, fake_extract, monkeypatch):
        monkeypatch.setattr(main, "recommend",
                            lambda *a, **kw: RecommendationResult(n_worker_skills=1, recommendations=[]))
        bad = client.post("/skills-gap/recommend-cv?k=0",
                          files={"file": ("cv.pdf", b"%PDF-fake", "application/pdf")})
        assert bad.status_code == 422
        ok = client.post("/skills-gap/recommend-cv?k=1",
                         files={"file": ("cv.pdf", b"%PDF-fake", "application/pdf")})
        assert ok.status_code == 200


class TestExtractionCache:
    def test_same_pdf_hits_extractor_once(self, monkeypatch):
        main._EXTRACT_CACHE.clear()
        calls = {"n": 0}

        def fake_extractor(content, filename="cv.pdf"):
            calls["n"] += 1
            return {"competenze_tecniche": ["python"]}

        monkeypatch.setattr(main, "call_extractor", fake_extractor)

        class F:  # minimal UploadFile stand-in
            filename = "cv.pdf"
            def __init__(self, data): self.file = io.BytesIO(data)

        p1 = main._extract_profile(F(b"same-bytes"))
        p2 = main._extract_profile(F(b"same-bytes"))
        p3 = main._extract_profile(F(b"other-bytes"))
        assert calls["n"] == 2                  # 2 distinct contents, 3 calls
        assert p1.skills == p2.skills == p3.skills == ["python"]

    def test_failures_are_not_cached(self, monkeypatch):
        main._EXTRACT_CACHE.clear()
        from app.sources import ExtractorError
        calls = {"n": 0}

        def flaky(content, filename="cv.pdf"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ExtractorError("down")
            return {"skills": ["sql"]}

        monkeypatch.setattr(main, "call_extractor", flaky)

        class F:
            filename = "cv.pdf"
            def __init__(self, data): self.file = io.BytesIO(data)

        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            main._extract_profile(F(b"x"))
        assert main._extract_profile(F(b"x")).skills == ["sql"]   # retry succeeded
        assert calls["n"] == 2


class TestSynonymPatterns:
    """Word-boundary semantics of the synonym map (no DB needed)."""

    def _target(self, text: str):
        from app.gap import _SYNONYM_PATTERNS
        for pat, target in _SYNONYM_PATTERNS:
            if pat.search(text.lower()):
                return target
        return None

    def test_prefix_stem_matches_inflected_word(self):
        assert self._target("Sviluppatore Python senior") == "Software Developer"

    def test_stem_does_not_match_inside_a_word(self):
        # "hr" must not fire inside unrelated words.
        assert self._target("schreiber") is None

    def test_whole_word_stem_matches_alone_and_in_phrase(self):
        assert self._target("hr") == "Risorse Umane/HR"
        assert self._target("hr manager") == "Risorse Umane/HR"
