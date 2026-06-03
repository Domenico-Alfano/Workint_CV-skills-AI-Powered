# CV-skills-AI-Powered

Skills-benchmark module for the **Workint** platform. Builds a **deterministic** per-job
benchmark (required skills for each occupation) from the version-pinned **ESCO** taxonomy,
then compares worker CVs against it to produce gap + training reports.

> Design rationale and roadmap live in [DESIGN_NOTES.md](DESIGN_NOTES.md). This README is
> the run guide. We are at **Stage A: the deterministic foundation** (load ESCO + mirror
> jobs). Classification (job → ESCO) and the benchmark materialization are Stage B/C.

## Prerequisites

- Docker (for local Postgres)
- Python 3.12 (`py -3.12` on Windows)

## Setup

```bash
# 1. Local Postgres
docker compose up -d

# 2. Python env + deps
py -3.12 -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 3. Config
copy .env.example .env            # then edit .env with your external DB credentials

# 4. Create the schema locally
python scripts/init_db.py
```

## Load data

```bash
# ESCO — do the one-time manual download first (see data/esco/README.md), then:
python scripts/load_esco.py

# Snapshot distinct offerte_lavoro.job_category (+ counts) within the date window
# into local Postgres. Window/threshold are set in .env (DATE_FROM, MIN_POSTINGS, ...):
python scripts/mirror_categories.py
```

## Classify categories -> ESCO, then review (Stage B)

```bash
# Hybrid match (mpnet embeddings + rapidfuzz lexical) each in_benchmark category to an
# ESCO occupation; stores top-5 candidates + a needs_review flag in job_occupation_map:
python scripts/classify_categories.py

# Export the mappings to data/review/job_occupation_review.csv (flagged rows first):
python scripts/export_review.py
#   -> open the CSV, set `pick` (1-5) or `correct_uri` per row to correct mappings

# Persist your review decisions back into job_occupation_map:
python scripts/import_review.py
```

## Materialize the benchmark (Stage C)

```bash
# Stage C1: ESCO-core benchmark — one row per category with essential/optional ESCO skills.
# Re-run after each review pass. (Postings demand overlay = Stage C2, not yet built.)
python scripts/materialize_benchmark.py
```

## Verify

```bash
docker exec -it workint_skills_pg psql -U workint -d skills_benchmark -c \
  "SELECT (SELECT count(*) FROM job_category) AS categories,
          (SELECT count(*) FROM job_category WHERE in_benchmark) AS to_benchmark,
          (SELECT count(*) FROM esco_occupation) AS occupations,
          (SELECT count(*) FROM esco_skill) AS skills,
          (SELECT count(*) FROM esco_occupation_skill) AS relations;"
```

## Tables (see [sql/schema.sql](sql/schema.sql))

| Table | Role |
|---|---|
| `job_category` | distinct `offerte_lavoro.job_category` in the snapshot window (+ counts, `in_benchmark` flag) |
| `esco_occupation`, `esco_skill`, `esco_occupation_skill` | version-pinned ESCO snapshot |
| `job_occupation_map` | category → ESCO occupation (the only non-deterministic step; audited) |
| `job_benchmark` | **one row per category**: ESCO essential/optional skills + postings demand overlay (the output) |

## Teardown

```bash
docker compose down -v   # removes the local DB volume
```
