# CLAUDE.md — project map (auto-loaded; keep it SHORT)

Workint skills-gap backend: builds a deterministic per-job skills benchmark (ESCO + CP2021)
and compares a worker CV against it → gap + LLM report. FastAPI backend; Angular FE consumes it.

## Where things are
- `app/` — FastAPI service: `main.py` (analyze-* + recommend-* endpoints), `gap.py` (gap
  engine + target resolution), `recommend.py` (career-transition ranking: coverage of ALL
  benchmarks × demand trend from `category_trend`), `courses.py` (semantic course match for
  missing skills), `sources.py` (extractor + workers adapters), `llm.py` (report),
  `models.py`, `config.py`.
- `scripts/` — offline benchmark-build pipeline (run order in README §9, "La pipeline di
  build del benchmark"; README is now the full Italian operating manual).
- `sql/schema.sql` — DB schema. `data/` — ESCO/CP2021 downloads (gitignored).

## Run
- venv python: `./.venv/Scripts/python.exe`  (Python 3.12; IDE diagnostics point at system py — ignore)
- API: `python -m uvicorn app.main:app --port 8077`  → Swagger at /docs
- Local Postgres: `docker compose up -d` (port 5433). Config in `.env` (gitignored).
- Tests: `pytest -m "not integration"` (fast, no DB). `pytest -m integration` needs DB+model up.

## Gotchas (read before debugging)
- mpnet (~400MB) is pre-warmed at startup (lifespan in `main.py`) → first request already fast.
- Benchmark label embeddings are precomputed offline to `data/cache/label_emb_<model>.npz`
  (`scripts/precompute_embeddings.py`) and loaded into `gap._EMB_STORE` at startup, so requests
  stay fast across restarts. Re-run that script after a benchmark rebuild or model change.
- Extractor host has a self-signed cert → `EXTRACTOR_VERIFY_SSL=false`.
- `/tmp` differs between git-bash and Windows python — pipe stdin, don't share temp files.
- CP2021 (transversal competences) uses a higher cover threshold (0.68 vs ESCO 0.62) to kill
  proper-noun false positives (e.g. "java"→"Resistenza"). ~0% for tech CVs (correct: no soft
  skills listed); meaningful for soft/manual CVs. ESCO gap is still the primary axis.
- Target job resolution: synonym map in `gap.py` (`_SYNONYMS`) + hybrid embedding fallback.
- LLM JSON output is unreliable → `llm.py` defensively coerces dict/list shapes to str.
- Server holds code in memory — RESTART uvicorn after editing `app/` to see changes.

## Token discipline
- Don't re-read DESIGN_NOTES.md each session (it's ~5k words of history). This file is enough.
- Print counts/summaries from commands, not full JSON/long lists. Trust edits without re-reading.

- Demand trends (scripts/compute_trends.py) are SHARE-based — postings volume swings with
  scraper activity (collapsed after Oct 2025), absolute counts lie. Pin TREND_ANCHOR_DATE.
- No literal `%` in sql/schema.sql comments — psycopg2 reads them as placeholders (init_db).
- Course catalog is a 42-row demo seed (data/courses_seed.csv); course<->skill match floor
  MIN_COURSE_SIM=0.55 in courses.py (real matches 0.74-0.90, noise <=0.53).

## Status: analyze-* + recommend-* endpoints working end-to-end. Benchmark = 306 categories. See README for the contract.
