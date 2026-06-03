# CV-skills-AI-Powered — Design Notes

> Status: **Stage A (deterministic foundation) built & verified.** This file is the
> session handoff so work can resume later. Last updated: 2026-05-29.
>
> NOTE: this file was once lost because it was untracked in git — **keep it committed.**

## 1. Project goal

Analyze CV entries stored in a remote PostgreSQL database. For each worker:

1. Extract their **job/role** and their **skills**.
2. Compare those skills against a **sector benchmark** (what the role should require).
3. Produce a **report**: strengths, missing skills, and recommended training
   (*formazione*) to bring the worker to benchmark level.

An LLM is used in the workflow for extraction, classification, and report writing.
A degree of **autonomy** is wanted (discovering new/emerging skills and jobs) — but
relocated to a safe place in the design (see §5).

**Two entry paths.** The system must serve both:
- **Batch / scheduled:** processes CV rows from the existing Postgres database (structured columns).
- **On-demand HTTP endpoint:** accepts a single ad-hoc CV *not yet in the DB* and returns the same analysis. *Implications in §6, open forks in §7.*

**Integration context.** This project is a **module inside the Workint platform**
(Angular FE + FastAPI BE + Milvus-based semantic matching + AI agents) — *not* a
standalone app. Workint already has CV upload + AI extraction (§5.1), worker registry
(§5.2), CV↔job semantic matching (§5.3), job-offer management (§5.5), RAL estimation
(§5.6), and **sector-trend analysis with upskilling/reskilling plans (§5.7) — which
overlaps directly with this project's mission and needs an explicit relationship
decision** (see §10).

## 2. Decisions locked so far

| Question | Decision |
|---|---|
| CV data format in Postgres | **Structured columns** (already split into fields) |
| Source **jobs** table (schema received) | Columns: `id` (int PK), `id_macrocategory` (int), `name` (IT title), `macro` (category label), `synonyms` (`text[]`), `description` (IT free text). **No taxonomy codes.** It is a **controlled vocabulary of occupation types** (e.g. Agronomo, Cassiere/a), *not* job postings → small, bounded, **one-time reviewable** mapping. Determinism is highly achievable. |
| Benchmark source | **ESCO, pinned to v1.2.0**, Italian. CSV bundle is download-gated (email) → one-time manual download into `data/esco/`, then offline + reproducible loader. INAPP Atlante = later enrichment; ISTAT CP = code bridge only. |
| Report audience | **Employment/staffing agency** (internal HR/recruiters: placement + upskilling) |
| Language & scale | **Italian, thousands+** of CVs (jobs vocabulary itself is small/bounded) |
| Runs inside Workint | **Yes** — stack inherited (see §10.1); reuses CV extraction (§5.1), worker registry (§5.2), matching infra (§5.3), and Workint's job orders as the demand-overlay source (§5.5) |

Implications:
- Structured columns → lighter parsing; LLM normalizes/enriches existing fields rather
  than reading raw PDFs.
- Staffing-agency audience → report is a recruiter decision tool ("is this candidate
  placeable in sector X, and what short upskilling closes the gap?"), not generic
  self-help.
- Italian + thousands → ESCO's native Italian helps; cost/throughput matter (batch
  processing, prompt caching, maximize deterministic steps).

## 3. Two key reframes

**Reframe A — the benchmark must be an authoritative taxonomy, not scraped pages.**
A gap claim ("you lack skill X") must be *defensible and reproducible*. That rules out
LinkedIn scraping as the core. The EU already publishes the benchmark:
- **ESCO** — EU occupations↔skills taxonomy. ~3,000 occupations, ~13,000 skills, with
  explicit occupation→(essential + optional) skill mappings. **Multilingual incl. Italian**,
  free, downloadable + REST API. This is effectively a pre-built per-occupation benchmark.
- **ISCO** — international occupation codes ESCO maps onto.
- **INAPP Atlante del Lavoro e delle Qualificazioni** + **ISTAT CP2021** — Italian
  national equivalents (occupation→activity→competence).

**Reframe B — LLM as extractor + explainer, not source of truth.**

| Stage | Who | Why |
|---|---|---|
| Parse CV → structured skills/role | LLM | Good at messy text |
| Map role → ESCO occupation code | LLM proposes + embedding match | Judgment + grounding |
| "What should this role know?" | Taxonomy (deterministic) | Must be defensible |
| Match worker-skills ↔ benchmark-skills | Embeddings + rules | Reproducible gap list |
| Write report / training plan | LLM | Good at explanation |

The LLM never *invents* the benchmark; it reads the CV and explains the gap against a
real standard.

## 4. Proposed benchmark model

Two layers, **no LinkedIn scraping in the core**:

1. **Stable spine — ESCO.** Classify the worker (and each source job) into an ESCO
   occupation; ESCO gives the authoritative essential + optional skill set (in Italian).
   Makes gap claims hold up.
2. **Demand overlay — Workint's own job orders (§5.5).** As a staffing agency, every job
   order from a client is a labeled, demand-side statement of "this sector needs these
   skills, now, in our market." Better than LinkedIn (it's the actual market), current,
   and owned (no legal/ToS risk). Use it to weight/extend the ESCO skill set and surface
   emerging skills.

External scraping (LinkedIn) stays **off the critical path**; at most a future optional
enrichment via a *legitimate* labor-market API (e.g. Lightcast/EMSI), never live per-CV.

Comparison of the three candidate sources:

| | A. Authoritative taxonomy | B. Live web scraping | C. Own job-order data |
|---|---|---|---|
| Legal | Clean (open license) | **Risky** (LinkedIn ToS, EU strict) | Clean (owned) |
| Reproducible | Yes (versioned) | No | Yes |
| Freshness | Lags emerging tech | Very current | Very current |
| Cost | Free | Scraping war / paid API | Free |

→ Recommendation: **C + A as core, B only later and only legitimately.**

## 5. Reframing the "independent / autonomous LLM"

Don't crawl LinkedIn live per report (non-reproducible, risky, slow, expensive at
thousands of CVs). Instead, a **scheduled enrichment agent** (weekly/monthly) that:
- ingests new job orders,
- proposes skills not yet in ESCO ("emerging"),
- flags them for human approval,
- updates the demand-overlay table.

→ Autonomy/freshness in the background; each individual report stays stable, fast, and
defensible.

## 6. Pipeline (high level)

1. **Ingress — two paths, converging into a common CV-record shape:**
   - **A. DB batch** — read structured CV rows from Postgres.
   - **B. HTTP endpoint** (e.g. `POST /analyze-cv`) — accept an ad-hoc CV upload (PDF / DOCX / raw text), extract text (with OCR fallback if scanned PDF), normalize into the same record shape as path A.
2. **Normalize** — clean & validate the common record shape; pseudonymize before LLM calls (see §8).
3. **Extract (LLM)** — structured JSON: role(s), years experience, skills *with evidence*,
   education, certifications.
4. **Classify occupation** — map to ESCO/ISCO code + confidence.
5. **Benchmark lookup** — required + optional skills for that occupation (+ demand overlay).
6. **Gap analysis** — matched / missing / extra skills (semantic matching via embeddings).
7. **Report (LLM)** — strengths, prioritized gaps, recommended *formazione*.
8. **Persist** — write results back with traceability.

## 7. Open items / immediate next steps

1. **(DONE)** Confirm benchmark direction → ESCO core + Workint job-order overlay.
2. **(DONE)** Source jobs schema received (see §2). It is a controlled vocabulary.
3. **Next — Stage B: classification** (job → ESCO occupation). Decide approach: embeddings
   (sentence-transformers + Milvus, reuse Workint model) → LLM tiebreak among top-K →
   human review of low-confidence/flagged rows. No taxonomy codes in source, so exact-code
   match is unavailable; rich signal (name + synonyms + description + macro) aids matching.
4. **Then — Stage C:** materialize `job_benchmark` (one row per job).
5. **On-demand endpoint — open forks** (decide before building that piece):
   - **Accepted input formats:** PDF only, PDF + DOCX, also raw text / JSON?
   - **Response mode:** synchronous vs asynchronous (`job_id` + poll/webhook).
   - **Persistence:** store ad-hoc CVs+analyses, or keep transient? (GDPR-relevant.)
   - **Caller:** internal-only vs external (auth, rate limiting, consent capture).
6. **Workint integration — open forks** (detail in §10.4):
   - Relationship to **§5.7** (sector trend & upskilling plan): replace, evolve, or parallel?
   - **Embedding-model alignment** with Workint's existing sentence-transformers setup.
   - **Reuse Workint's existing CV-extraction AI agents** (§5.1) vs build a new LLM extractor.

## 8. Cross-cutting concerns to keep in mind

- **GDPR / privacy.** CVs are personal data; EU + Italian Garante. Sending CV text to an
  LLM API triggers data-processing/retention/minimization duties. Likely **pseudonymize**
  (strip name/contacts) before LLM calls.
- **Skill entity resolution.** "Python programming" vs ESCO "Python (computer programming)"
  → needs semantic matching (embeddings), not string equality.
- **Evaluation / ground truth.** Hand-label a small set to measure gap-analysis quality;
  otherwise reports are unfalsifiable.
- **Human-in-the-loop.** Early on, a reviewer confirms occupation classification before a
  report ships. (Cheap here — the jobs vocabulary is bounded.)
- **Scale/cost (thousands, Italian).** Anthropic Message Batches API (cheaper, async),
  prompt caching for the ESCO/system context, embed the ~13k ESCO skills once, and push
  as much logic as possible to deterministic code to limit LLM calls per CV.
- **Consent at submission (endpoint path).** Ad-hoc CVs via the on-demand endpoint need a
  clear legal basis (consent / legitimate-interest). Require a caller attestation field;
  log submission/consent metadata.

## 9. Stack additions on top of Workint

The base stack is **inherited from Workint** (Python 3.13 / FastAPI / Pydantic / Postgres /
SQLAlchemy / Milvus / sentence-transformers / Angular) — see §10.1. Items still to decide
*on top* of that base:

- **LLM provider for extraction + report writing.** If a specific LLM is already wired into
  Workint's §5.1 / §5.6 / §5.7, **reuse it**. Otherwise propose **Claude (Anthropic API)**
  with prompt caching + Message Batches for the batch path.
- **ESCO data delivery.** Local versioned snapshot (downloaded ESCO release, loaded into
  Postgres now; Milvus later for skill embeddings) — preferred over live API.
- **Async job execution** (only if §7.5 picks async response mode). Propose **Redis + RQ**
  or **Arq** (light) vs **Celery** (heavier).

> Local-testing note: dev box has Python 3.12 + 3.14 (no 3.13). Stage A uses a **3.12
> venv** (no ML deps). When embeddings/torch arrive (Stage B), move to a **Docker container
> pinned to Python 3.13** to match Workint and guarantee torch wheels.

## 10. Integration with Workint (host application)

This project is a **module inside the Workint platform**, not standalone.

### 10.1 Inherited stack (mandatory, for consistency with Workint)

- **Backend:** Python 3.13, **FastAPI** + Uvicorn, **Pydantic**, **PostgreSQL**,
  **SQLAlchemy**, **Pandas / Polars**.
- **AI / matching layer:** **sentence-transformers** embeddings, **Milvus** (pymilvus)
  vector DB, Hugging Face NLP tokenization, **NumPy**.
- **Frontend:** **Angular v21.0.5** + Angular Material / Bootstrap / ngx-bootstrap,
  **ngx-translate**, **echarts / ngx-echarts**, **leaflet**, **ngx-toastr**.

→ ESCO skill embeddings will live in **Milvus** alongside Workint's existing CV/job-offer
  vectors (not a separate pgvector store).

### 10.2 Relationship to existing Workint features

| Workint feature | How this project interacts |
|---|---|
| **§5.1** CV acquisition (PDF/ZIP upload, AI extraction, human review) | **Reuse** the existing extraction pipeline; on-demand endpoint (§6 path B) plugs into it. |
| **§5.2** Worker visualization & profile | Batch path reads the same registry; reports surface in the profile UI. |
| **§5.3** Semantic CV↔job matching (embeddings + Milvus) | Shares embedding infra; extended with **ESCO occupation/skill** embeddings. |
| **§5.5** Job-offer management & search | **The demand-overlay source** (§4). Workint already owns it. |
| **§5.6** RAL calculation | Adjacent CV-driven feature; may share the extracted-profile output. |
| **§5.7** Sector trend + upskilling/reskilling plan | **Direct overlap — decision needed (§10.4).** |

### 10.3 Where the new module plugs in

- **Backend** — a new FastAPI router (e.g. `/skills-gap`):
  - `POST /skills-gap/analyze-cv` — on-demand path (CV file or JSON → report).
  - `POST /skills-gap/analyze-worker/{id}` — batch / registry path.
  - `GET  /skills-gap/report/{id}` — fetch a stored report.
- **Vector store** — new Milvus collections: `esco_skills`, `esco_occupations`.
- **Relational tables** — `job_benchmark`, `job_occupation_map`, `esco_*` (built in Stage A).
  Plus future `skills_gap_report` / `skills_gap_finding` for per-CV results.
- **Frontend** — a new Angular component on the worker profile: gap-report visualization
  (echarts radar/bar for matched vs missing, table of recommended *formazione*),
  translated via ngx-translate.

### 10.4 Integration-specific open questions

- **Relationship to §5.7 — replace, evolve, or parallel?** Options: (a) replace §5.7;
  (b) keep §5.7 (macro/3-year projection) + add this as a separate per-skill *Skill gap vs
  benchmark* module; (c) merge. Recommendation: **(b) or (c)** — complementary, not redundant.
- **Embedding model alignment.** Reuse Workint's sentence-transformers model unless ESCO
  matching eval shows a clear gain. IT candidates: `paraphrase-multilingual-mpnet-base-v2`,
  `efederici/sentence-bert-base` (IT), or a domain-tuned variant.
- **AI-agent reuse for CV extraction.** Use Workint's existing §5.1 extraction agents
  rather than a new LLM extractor; confirm/extend their output schema (role, skills *with
  evidence*, education, certs).

## 11. Build log / current status

**Stage A — deterministic foundation: DONE & verified (2026-05-29).**

Created and committed-worthy files:
- `docker-compose.yml` — local Postgres 16 on host port **5433** (disposable).
- `sql/schema.sql` — 6 tables: `jobs` (local mirror), `esco_occupation`, `esco_skill`,
  `esco_occupation_skill`, `job_occupation_map` (the only soft step, audited),
  `job_benchmark` (one row per job — the output). All ESCO rows version-pinned.
- `scripts/db.py` — env + SQLAlchemy engines (local + external read-only).
- `scripts/init_db.py` — applies schema (idempotent).
- `scripts/load_esco.py` — loads pinned ESCO Italian CSVs → `esco_*` (truncate+reload,
  tolerant column lookup, prints detected columns).
- `scripts/mirror_jobs.py` — reads external jobs table → local `jobs`.
- `data/esco/README.md` — one-time ESCO download steps.
- `.env.example`, `requirements.txt` (no ML deps yet), `.gitignore`, `README.md` (run guide).

Verified: Docker Postgres up, 3.12 venv with deps installed, `init_db.py` created all 6
tables (confirmed via `\dt`; all empty pending data load).

**Blocked on two user actions before Stage B:**
1. **ESCO download** — follow `data/esco/README.md` (v1.2.0, Italian, CSV → 3 files into
   `data/esco/`), then `python scripts/load_esco.py`.
2. **External DB credentials** — fill `EXTERNAL_JOBS_DB_URL` + `EXTERNAL_JOBS_TABLE` in
   `.env`, then `python scripts/mirror_jobs.py`.

**Next: Stage B (classification)** — see §7 item 3, but read §12 first (direction changed).

## 12. PIVOT (2026-05-29): benchmark unit = `offerte_lavoro.job_category`

The earlier plan assumed the benchmark unit was the clean `ai_category` vocabulary
(~hundreds of rows). **Superseded.** User chose to build over the real job-postings table.

**Source tables (external DB `workint-clone`, schema `public`; also a `backup` schema):**
- `ai_category` — clean controlled vocabulary (id, id_macrocategory, name, macro, synonyms,
  description). *No longer the benchmark unit, but still useful for label/synonym enrichment.*
- `ai_macrocategory` — macrocategory lookup.
- **`offerte_lavoro` — ~2.56M real job postings.** Columns: job_title, job_company_name,
  job_location, job_via, job_description, job_highlights, job_related_links, job_thumbnail,
  job_extensions, job_detected_extensions, job_id (text), job_lat, job_lon, job_address,
  mapping_timestamp (ingestion ts), fonte_dato, job_category, embeddings_computed,
  job_category2, company_id.

**Decisions (this session):**
- **Benchmark unit = one row per distinct `job_category`.** 20,897 distinct values, but a
  power-law: **≥50 postings → 2,031 categories cover 96.2%** of postings; ≥100 → 1,335
  (94.3%). `job_category` is clean (0 null/empty, only 20 "Altro" rows). job_category2 is
  messy (Unknown/Altro) — ignore. **Recommended threshold: ≥50 postings** (build benchmarks
  for those; optionally store all). PENDING user confirm of threshold.
- **Requirements source = BOTH:** ESCO core (deterministic spine) + postings overlay (demand).
- **Date filter = PENDING.** User checking in DBeaver which column to use. Candidates:
  - `mapping_timestamp` (ingestion): range 2025-03-04 → **2026-02-06**. 2025-04-01→now =
    ~2.35M rows; **2026-04-01→now = 0 rows**.
  - `job_extensions`: appears to hold the real **publication date** (ISO ts like
    `2025-09-12T06:02:55Z`) — needs parsing/validation across all rows.
  - NOTE: neither reaches "today" (2026-05-29); newest ingestion is 2026-02-06.

**Scale implication for the postings overlay (~2.35M postings — cannot LLM-extract each):**
proposed deterministic overlay = for each posting, detect which **ESCO skills** appear in
its text via embeddings (reuse Workint sentence-transformers + Milvus), then aggregate per
`job_category` → frequency of each ESCO skill. Keeps both layers in **ESCO skill space**
(core + overlay directly comparable), reproducible. Emerging/non-ESCO skills are handled by
the scheduled enrichment agent (§5), not per-report. Sampling (e.g. ≤N postings/category)
can cap cost if needed.

**Revised pipeline for this direction:**
1. Read distinct `job_category` (+ posting counts) from `offerte_lavoro` within the chosen
   date window; keep those ≥ threshold.
2. Mirror that category list locally (replaces the `ai_category`-based `jobs` mirror).
3. Classify each `job_category` → ESCO occupation (embeddings → LLM tiebreak → review).
4. ESCO core skills via occupation→skill lookup.
5. Postings overlay: aggregate ESCO-skill frequencies from the category's postings.
6. Materialize `job_benchmark`: one row per category = ESCO essential/optional + demand
   weights from the overlay.

**Schema impact (TODO, blocked on date decision):** the local `jobs` table (modeled on
`ai_category`: id/name/macro/synonyms/description) must be replaced by a category-keyed
table, e.g. `job_category(category_id serial PK, job_category text UNIQUE, posting_count,
date_window)`. `job_occupation_map` / `job_benchmark` re-key from `job_id INT` to
`category_id`. **Do not rebuild schema until the date column is confirmed** (it determines
the category set + counts).

**Resolved (2026-06-02/03):**
- Date filter = **`mapping_timestamp` >= 2026-04-01** to present. DB is **live/volatile**:
  re-querying now gives max ts 2026-06-02 and ~97–100k postings in window (earlier snapshot
  showed different numbers). We pin the window + record `date_to` per snapshot.
- Threshold = **MIN_POSTINGS=10** (user said "any"; chosen for 99.6% coverage).
- ESCO download **done** (files in `data/esco/`, relations file is `_it`-suffixed).

**Stage A.2 — data layer: DONE & verified (this session).** Local DB now holds:
- ESCO: 3,039 occupations / 13,939 skills / 129,004 relations (v1.2.0).
- `job_category`: **485 categories** snapshotted (window 2026-04-01..2026-06-02 on
  mapping_timestamp; 97,111 postings); **306 flagged `in_benchmark`** (>=10 postings).
- Schema re-keyed from `jobs(id)` to `job_category(category_id)`; `job_benchmark` gained a
  `demand_skills` JSONB column for the postings overlay.
- New script `scripts/mirror_categories.py` (replaces `mirror_jobs.py`); config vars added
  to `db.py`/`.env.example`: POSTINGS_TABLE, DATE_COLUMN, DATE_FROM, DATE_TO, MIN_POSTINGS.

**Next — Stage B: classify the 306 in_benchmark categories → ESCO occupation.** Approach:
embeddings (sentence-transformers, IT model; reuse Workint's) over the category name vs
ESCO occupation labels → top-K → LLM tiebreak → human review of low-confidence. Then ESCO
core skill lookup, then the postings overlay, then materialize `job_benchmark`.
Decision pending for Stage B: which embedding model + whether to bring in Milvus now or do
a local cosine pass first (306 categories × 3,039 occupations is tiny — local is fine).
