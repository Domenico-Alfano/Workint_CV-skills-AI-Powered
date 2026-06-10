"""Deterministic skills-gap engine: worker skills vs a job_benchmark row (ESCO + CP2021).

For each benchmark skill we find the worker's most similar skill (cosine over mpnet
embeddings); it's 'covered' when similarity >= COVER_THRESHOLD, else 'missing'. No LLM.
"""
import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz
from sqlalchemy import text

from .config import COVER_THRESHOLD, CP2021_COVER_THRESHOLD, EMBEDDING_MODEL, engine, model
from .models import BenchmarkGap, GapResult, SkillMatch

log = logging.getLogger(__name__)

RESOLVE_MIN_SCORE = 0.55
RESOLVE_ALPHA = 0.5     # same weight as classify_categories.py

# Italian job-title synonyms that the hybrid matcher misses (benchmark uses different
# labels, often English). Each stem matches case-insensitively at a WORD START anywhere
# in the input ("sviluppator" -> "Sviluppatore senior" but not "*svilupator"); a stem
# with a trailing space means whole-word only ("hr " matches "hr" / "hr manager", never
# the "hr" inside "schreiber").
_SYNONYMS: list[tuple[str, str]] = [
    ("sviluppator", "Software Developer"),
    ("programmator", "Programmatore"),
    ("informatico", "Software Developer"),
    ("sistemista",  "Sistemista"),
    ("devops",      "Software Developer"),
    ("full stack",  "Software Developer"),
    ("frontend",    "Software Developer"),
    ("backend",     "Software Developer"),
    ("data scientist", "Data Scientist"),
    ("data analyst",   "Data Analyst"),
    ("cuoc",        "Cuoco"),
    ("chef",        "Cuoco"),
    ("infermier",   "Infermiere"),
    ("contabil",    "Contabile"),
    ("ragionier",   "Contabile"),
    ("elettricist", "Elettricista"),
    ("idraulic",    "Idraulico"),
    ("muratore",    "Muratore"),
    ("magazzin",    "Magazziniere"),
    ("commess",     "Commesso/a"),
    ("camerier",    "Cameriere/a"),
    ("parrucchier", "Parrucchiere/a"),
    ("meccanico",   "Meccanico"),
    ("autista",     "Autista"),
    ("operaio",     "Operaio di Produzione"),
    ("saldatore",   "Saldatore"),
    ("falegname",   "Falegname"),
    ("giardinier",  "Giardiniere"),
    ("insegnante",  "Insegnante"),
    ("medico",      "Medico"),
    ("avvocat",     "Avvocato"),
    ("architett",   "Architetto"),
    ("geometra",    "Geometra"),
    ("commerciale", "Impiegato Commerciale"),
    ("marketing",   "Digital Marketing Specialist"),
    ("hr ",         "Risorse Umane/HR"),
    ("risorse umane", "Risorse Umane/HR"),
    ("vendit",      "Venditore"),
    ("receptionist","Receptionist"),
    ("segretari",   "Assistente Amministrativo"),
    ("amministrat", "Assistente Amministrativo"),
]

# Compiled once: word-boundary prefix match; trailing-space stems become whole words.
_SYNONYM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + re.escape(stem.strip()) + (r"\b" if stem != stem.strip() else "")),
     target)
    for stem, target in _SYNONYMS
]


class TargetNotFound(Exception):
    """Raised when no benchmark resolves for the requested target.

    Carries `candidates` (best-guess categories) so the API can offer the FE a
    'did you mean…?' picker instead of a dead-end 404.
    """
    def __init__(self, message: str, candidates: list[dict] | None = None):
        super().__init__(message)
        self.candidates = candidates or []


# Persistent per-label embedding store. Benchmark labels are static (built offline), so
# we precompute them once into an .npz and load it here — surviving restarts and avoiding
# the 306x duplication a per-category cache would incur (CP2021 labels are shared).
# The filename is keyed on the model so a model swap can't load stale vectors.
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
_EMB_FILE = _CACHE_DIR / f"label_emb_{hashlib.md5(EMBEDDING_MODEL.encode()).hexdigest()[:12]}.npz"
_EMB_STORE: dict[str, np.ndarray] = {}   # text -> embedding; persists across requests
_emb_loaded = False


def _load_emb_store() -> dict[str, np.ndarray]:
    """Lazily fill the in-memory store from the precomputed .npz (if present). Safe no-op
    when the file is missing — `_encode` then just encodes on demand."""
    global _emb_loaded
    if not _emb_loaded:
        _emb_loaded = True
        if _EMB_FILE.exists():
            data = np.load(_EMB_FILE)
            for lbl, vec in zip(data["labels"], data["embeddings"]):
                _EMB_STORE[str(lbl)] = vec
            log.info("loaded %d precomputed embeddings from %s", len(_EMB_STORE), _EMB_FILE.name)
    return _EMB_STORE


def _encode(texts: tuple[str, ...]) -> np.ndarray:
    """Embed `texts` (order preserved) via the store; encode only the misses — labels absent
    from the .npz or novel worker skills — and memoize them. Returns (len(texts), dim)."""
    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    store = _load_emb_store()
    missing = [t for t in dict.fromkeys(texts) if t not in store]   # unique, order-stable
    if missing:
        vecs = np.asarray(model().encode(missing, normalize_embeddings=True))
        for t, v in zip(missing, vecs):
            store[t] = v
    return np.stack([store[t] for t in texts])


@lru_cache(maxsize=1)
def _category_index():
    """Cache (ids, labels, embeddings) of all benchmark job_categories for target resolution."""
    with engine().connect() as conn:
        rows = conn.execute(
            text("SELECT category_id, job_category FROM job_benchmark ORDER BY category_id")
        ).all()
    ids = [r[0] for r in rows]
    labels = [r[1] for r in rows]
    emb = model().encode(labels, normalize_embeddings=True)
    return ids, labels, np.asarray(emb)


def _hybrid_scores(job_text: str):
    """Hybrid (semantic + lexical) score of `job_text` against every benchmark category.
    Returns (ids, labels, combined) where combined is a per-category score array."""
    ids, labels, emb = _category_index()
    q = model().encode([job_text], normalize_embeddings=True)[0]
    sem = emb @ q
    lex = np.array([fuzz.WRatio(job_text, l) / 100.0 for l in labels], dtype=np.float32)
    combined = RESOLVE_ALPHA * sem + (1 - RESOLVE_ALPHA) * lex
    return ids, labels, combined


def resolve_category(job_text: str):
    """Map a free-text job to the nearest benchmark category (synonym lookup then hybrid)."""
    ids, labels, _ = _category_index()
    lower = job_text.lower()

    # Fast synonym pass: if the input matches a known Italian stem, map to its target label.
    for pattern, target_label in _SYNONYM_PATTERNS:
        if pattern.search(lower):
            for i, lbl in enumerate(labels):
                if lbl.lower() == target_label.lower():
                    log.info("target resolved via synonym: %r -> %r", job_text, labels[i])
                    return (ids[i], labels[i], 1.0)
            break  # stem matched but target not in benchmark — fall through to hybrid

    ids, labels, combined = _hybrid_scores(job_text)
    j = int(np.argmax(combined))
    score = float(combined[j])
    if score >= RESOLVE_MIN_SCORE:
        log.info("target resolved via hybrid: %r -> %r (score %.2f)", job_text, labels[j], score)
        return (ids[j], labels[j], score)
    log.warning("target not resolved: %r (best score %.2f)", job_text, score)
    return (None, None, score)


def suggest_categories(job_text: str, k: int = 3) -> list[dict]:
    """Top-k nearest benchmark categories for a free-text job — fed to the FE as a
    'did you mean…?' picker when resolution fails."""
    ids, labels, combined = _hybrid_scores(job_text)
    top = np.argsort(-combined)[:k]
    return [
        {"category_id": int(ids[j]), "job_category": labels[j], "score": round(float(combined[j]), 3)}
        for j in top
    ]


def _labels(jsonb_value) -> list[str]:
    data = jsonb_value if isinstance(jsonb_value, list) else (json.loads(jsonb_value) if jsonb_value else [])
    return [d["label"] for d in data if d.get("label")]


def _load_benchmark(category_id: int | None, job_category: str | None) -> dict:
    select = ("SELECT category_id, job_category, occupation_label_it, essential_skills, "
              "optional_skills, cp2021_label, cp2021_skills FROM job_benchmark WHERE ")

    def _by(where, params):
        with engine().connect() as conn:
            return conn.execute(text(select + where), params).mappings().first()

    if category_id is not None:
        row = _by("category_id = :v", {"v": category_id})
        if not row:
            raise TargetNotFound(f"No benchmark for category_id {category_id}.")
        return dict(row)

    if not job_category:
        raise TargetNotFound("Provide target_category_id or target_job_category.")

    row = _by("lower(job_category) = lower(:v)", {"v": job_category})
    if row:
        return dict(row) | {"_target_confidence": 1.0}
    cid, label, score = resolve_category(job_category)
    if cid is None:
        raise TargetNotFound(
            f"No benchmark close to {job_category!r} (best score {score:.2f}).",
            candidates=suggest_categories(job_category),
        )
    return dict(_by("category_id = :v", {"v": cid})) | {"_target_confidence": round(score, 3)}


def _gap(source: str, occupation_label: str | None, bench_labels: list[str],
         worker_skills: list[str], sims: np.ndarray | None, threshold: float) -> BenchmarkGap:
    covered, missing = [], []
    for i, skill in enumerate(bench_labels):
        if sims is not None and len(worker_skills):
            j = int(np.argmax(sims[i]))
            score = float(sims[i][j])
            if score >= threshold:
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
    log.info("analyze: job=%r category_id=%s n_skills=%d", job_category, category_id, len(worker_skills))
    bm = _load_benchmark(category_id, job_category)
    esco_labels = _labels(bm["essential_skills"]) + _labels(bm["optional_skills"])
    cp_labels = _labels(bm["cp2021_skills"])

    worker_skills = [s.strip() for s in worker_skills if s and s.strip()]
    if worker_skills and (esco_labels or cp_labels):
        w = _encode(tuple(worker_skills))                       # small, sometimes cached
        esco_sims = _encode(tuple(esco_labels)) @ w.T if esco_labels else None  # labels cached
        cp_sims = _encode(tuple(cp_labels)) @ w.T if cp_labels else None
    else:
        esco_sims = cp_sims = None

    from .courses import suggest_courses     # deferred: courses imports gap._encode
    from .llm import generate_report
    conf = bm.get("_target_confidence")
    result = GapResult(
        category_id=bm["category_id"],
        job_category=bm["job_category"],
        target_confidence=None if conf == 1.0 else conf,
        n_worker_skills=len(worker_skills),
        esco=_gap("esco", bm["occupation_label_it"], esco_labels, worker_skills, esco_sims,
                  COVER_THRESHOLD),
        cp2021=_gap("cp2021", bm["cp2021_label"], cp_labels, worker_skills, cp_sims,
                    CP2021_COVER_THRESHOLD),
    )
    result.suggested_courses = suggest_courses(result.esco.missing)
    result.report = generate_report(result)
    log.info(
        "gap result: %r -> %r | esco %.1f%% (%d/%d) | cp2021 %.1f%% (%d/%d) | conf=%s",
        job_category, bm["job_category"],
        result.esco.coverage_pct, result.esco.n_covered, result.esco.n_total,
        result.cp2021.coverage_pct, result.cp2021.n_covered, result.cp2021.n_total,
        result.target_confidence,
    )
    return result
