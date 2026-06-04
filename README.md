# CV-skills-AI-Powered

Skills-gap module for the **Workint** staffing platform. It builds a **deterministic
per-job skills benchmark** from authoritative taxonomies (EU **ESCO** + Italian **CP2021 /
INAPP**), then compares a worker's CV against the benchmark for their target job and returns
a structured gap + an LLM-written report (strengths, gaps, recommended *formazione*).

> **Architecture note:** this is a backend module. The production UI is Workint's Angular
> app, which calls the two REST endpoints below. FastAPI's Swagger UI at `/docs` is the test
> frontend. Design history & rationale live in [DESIGN_NOTES.md](DESIGN_NOTES.md).

---

## How it works

Two phases:

**A. Build the benchmark (offline, periodic).** Reproducible, no LLM:
```
offerte_lavoro postings ──► distinct job_category (snapshot window)
                                   │
              ┌────────────────────┴─────────────────────┐
        ESCO (EU)                                   CP2021 (ISTAT)
   classify → occupation                       classify → profession
   essential/optional skills                   INAPP API competences
              └────────────────────┬─────────────────────┘
                              job_benchmark   (one row per job_category)
```

**B. Analyze a worker (online, per request).** Deterministic gap + LLM report:
```
CV (PDF) ─► extractor ─┐
                       ├─► worker skills ─► embed & match vs job_benchmark ─► gap + report
worker_id ─► workers ──┘                    (target job fuzzy-resolved)
```

The **gap** (covered / missing skills, coverage %) is deterministic (sentence-transformer
cosine match). Only the **narrative report** uses an LLM.

---

## Tech stack

Python 3.12 · FastAPI · PostgreSQL (SQLAlchemy) · sentence-transformers (`mpnet`
multilingual) + rapidfuzz · OpenAI-compatible LLM (Groq / OpenAI). Aligns with Workint's
backend stack. See [requirements.txt](requirements.txt).

---

## Prerequisites

- **Docker** (local Postgres for the benchmark DB)
- **Python 3.12** (`py -3.12` on Windows)
- Network access to: the external Postgres (`workint-clone`), the CV extractor
  (`ai-services.workint.expleoitalia.it`), and the LLM provider (Groq/OpenAI).

## Setup

```bash
docker compose up -d                       # local Postgres on :5433

py -3.12 -m venv .venv
.venv\Scripts\activate                     # Windows
pip install -r requirements.txt

copy .env.example .env                      # then fill in real values (see Configuration)
python scripts/init_db.py                   # create the schema
```

## Data acquisition (one-time, manual downloads)

Both taxonomies are downloaded once and version-pinned; the files are **gitignored**.

**ESCO** → into `data/esco/` (from <https://esco.ec.europa.eu/en/use-esco/download>):
select **v1.2.0**, language **Italian (it)**, format **CSV**, accept terms, then copy these
3 files: `occupations_it.csv`, `skills_it.csv`, `occupationSkillRelations_it.csv`.

**CP2021** → into `data/cp2021/` (from <https://www.istat.it/it/archivio/18132>):
`CP2021.xlsx` (the classification with the `quinto_digit` sheet). CP2021 *skills* are not in
the file — they come live from the INAPP API (`/extract` of competences) during the build.

## Build the benchmark

Run once (and whenever you refresh the data / re-snapshot postings):

```bash
python scripts/load_esco.py            # ESCO occupations + skills + relations
python scripts/load_cp2021.py          # 813 CP2021 professions + voci (match labels)
python scripts/mirror_categories.py    # snapshot distinct offerte_lavoro.job_category
python scripts/classify_categories.py  # job_category -> ESCO occupation  (hybrid match)
python scripts/classify_cp2021.py      # job_category -> CP2021 profession (hybrid match)
python scripts/fetch_cp2021_skills.py  # INAPP API -> CP2021 competences per profession
python scripts/materialize_benchmark.py  # -> job_benchmark (one row per category)
```

Optional human review of the classification (low-confidence rows are flagged):
```bash
python scripts/export_review.py   # -> data/review/job_occupation_review.csv (edit it)
python scripts/import_review.py   # apply your corrections, then re-run materialize
```

## Run the API

```bash
python -m uvicorn app.main:app --reload --port 8077
# open http://127.0.0.1:8077/docs   (Swagger UI = test frontend)
```

---

## API reference (frontend contract)

Base path `/skills-gap`. Both endpoints return the same `GapResult` JSON.

| Method & path | Input | Purpose |
|---|---|---|
| `POST /skills-gap/analyze-cv` | `multipart/form-data` `file=<PDF>`; query `target_category_id` *or* `target_job_category` | Ad-hoc CV: PDF → extractor → gap |
| `POST /skills-gap/analyze-worker/{worker_id}` | path `worker_id` (int) | Stored worker (reads `workers` table) → gap |
| `GET /health` | – | Liveness |

**`GapResult` response shape:**
```jsonc
{
  "category_id": 14,
  "job_category": "Cuoco",          // benchmark matched
  "target_confidence": null,         // null = exact match; e.g. 0.64 = fuzzy (warn user)
  "n_worker_skills": 8,
  "esco": {                          // primary, meaningful gap
    "source": "esco",
    "occupation_label": "cuoco/cuoca",
    "n_total": 50, "n_covered": 31, "coverage_pct": 62.0,
    "covered": [ { "skill": "...", "matched_with": "<worker skill>", "score": 0.92 } ],
    "missing": [ "pianificare i menu", "nutrizione", ... ]
  },
  "cp2021": { ...same shape... },    // Italian competences (transversal; see Limitations)
  "report": {                        // null if LLM_API_KEY not set
    "strengths": "Il candidato ...",
    "gaps": "Le lacune principali ...",
    "formation": [ "Corso HACCP ...", "Certificazione ...", "Corso ..." ]
  }
}
```

Error codes: `404` target/worker not found · `422` no skills parsed / no target job ·
`502` extractor failed · `501` workers schema mismatch.

## For the frontend developer

You only need the API base URL + the contract above. Suggested Angular rendering:

- `esco.coverage_pct` → progress bar; `esco.n_covered`/`esco.n_total` → caption.
- `esco.covered` → list of matched skills (each shows `matched_with` + `score`).
- `esco.missing` → chips/tags of skills to acquire.
- `report.strengths` / `report.gaps` → paragraphs; `report.formation` → `*ngFor` bullet list.
- `report` may be `null` → guard with `*ngIf="result.report"`.
- `target_confidence != null` → show a "we guessed the target job — confirm?" notice.
- The two endpoints map to your two flows (PDF upload / pick existing worker).

Set `CORS_ORIGINS` to the Angular origin(s).

## Deployment

- Serve with `uvicorn app.main:app` (prod: add `--workers N` or run under gunicorn with
  uvicorn workers) behind the existing reverse proxy / TLS.
- The benchmark **must be built first** (the scripts above) into the Postgres the API reads
  (`LOCAL_DB_URL`). For prod, point `LOCAL_DB_URL` at a persistent Postgres and run the build
  pipeline there — the local Docker DB is for dev only.
- First request loads the `mpnet` model (~1 GB, cached after). Pre-warm by hitting `/health`
  then one analyze call, or bake the model into the image.
- Outbound access required: extractor host (self-signed cert → `EXTRACTOR_VERIFY_SSL=false`
  or provide `EXTRACTOR_CA_BUNDLE`), external `workers` DB, LLM provider.
- No Milvus needed — matching is in-process (the dataset is small).

## Configuration (`.env`)

| Var | Purpose |
|---|---|
| `LOCAL_DB_URL` | Postgres holding the benchmark (read by the API) |
| `EXTERNAL_JOBS_DB_URL` | Read-only external DB (`offerte_lavoro`, `workers`) |
| `POSTINGS_TABLE`, `DATE_COLUMN`, `DATE_FROM`, `MIN_POSTINGS` | Postings snapshot window |
| `ESCO_VERSION`, `ESCO_DATA_DIR` | ESCO pin + data dir |
| `EXTRACTOR_URL`, `EXTRACTOR_PASSWORD`, `EXTRACTOR_VERIFY_SSL` | CV extractor (Flow 1) |
| `WORKERS_TABLE`, `WORKERS_COL_*` | Stored-CV mapping (Flow 2) |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | Report LLM (`groq`→`openai`, no code change) |
| `CORS_ORIGINS` | Angular origin(s) |

## Project structure

```
app/            FastAPI service
  main.py         endpoints (analyze-cv, analyze-worker, health)
  gap.py          deterministic gap engine + target resolution
  sources.py      input adapters (extractor JSON / workers table)
  llm.py          narrative report (Groq/OpenAI)
  models.py       request/response schemas (the contract)
  config.py       env + cached engine/model
scripts/        offline benchmark-build pipeline (run in the order above)
sql/schema.sql  database schema
data/           ESCO + CP2021 downloads (gitignored)
```

## Known limitations

- **CP2021 gap ≈ 0%** for concrete CV skills — its competences are transversal
  (communication, dexterity…) and don't embedding-match task-level skills. Treat the CP2021
  section as a *competence profile*, not a covered/missing checklist (or improve via LLM).
- **Target resolution** is hybrid embedding+lexical but can miss Italian synonyms absent
  from the benchmark (e.g. "Sviluppatore" when only "Software Developer" exists) →
  `target_confidence` surfaces low-confidence matches for the UI to confirm.
- Stored `workers` skill quality varies (some rows hold sparse/free-text skills).
