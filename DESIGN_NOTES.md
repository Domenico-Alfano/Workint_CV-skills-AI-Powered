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

## 13. Stage B — classification (category → ESCO): DONE (retrieval), review pending

**Built `scripts/classify_categories.py`** — hybrid match of each in_benchmark category to
an ESCO occupation:
- Index EVERY ESCO label (preferred + altLabels) → occupation; 16,546 labels. Essential:
  ESCO leaves are hyper-specific, the generic terms categories use live in altLabels.
- **Hybrid score** = ALPHA·semantic + (1-ALPHA)·lexical (ALPHA=0.5):
  - semantic = `paraphrase-multilingual-mpnet-base-v2` cosine.
  - lexical = `rapidfuzz` WRatio (catches stems like Magazziniere↔magazzino).
- Best label per occupation → top-5 candidates stored in
  `job_occupation_map.candidates_considered`; `needs_review = top1 < 0.70`.

**Why hybrid + mpnet (evidence):** the light MiniLM model was erratic on short Italian
occupational terms (rated "Magazziniere"↔"smaltatore" 0.88 vs correct 0.52; "Contabile"→
park keeper) and the correct occupation was often absent from top-5 → no LLM could fix it.
mpnet + lexical fixed the common cases (Magazziniere, Contabile, Cameriere, Cuoco, Logistica
all correct). User decisions: stronger model + lexical hybrid; **LLM tiebreak deferred** —
review by hand first.

**Result:** 306 categories classified, **41 flagged needs_review**. A tail of errors remains
(e.g. Impiegato Commerciale→modello, Store Manager→responsabile acquisti, Cameriera ai
Piani→stage machinery) — handled by human review.

**Human-review loop (built):**
- `scripts/export_review.py` → `data/review/job_occupation_review.csv` (flagged + high-volume
  first; columns c1..c5 + `pick`/`correct_uri`/`notes`).
- `scripts/import_review.py` → applies decisions (pick 2-5 or correct_uri → override
  method='manual'; pick=1 → accept; blank → untouched). Sets reviewed/needs_review.

**Observations / open for later:**
- Some `job_category` values are broad sector buckets (Alberghi/Ristoranti/Bar,
  Pubblicità/Marketing/PR), not single occupations → hard to map to one ESCO leaf; consider
  special handling or excluding.
- Granularity: generic title → ESCO leaf is lossy (a title maps to a family / ISCO group).
  Possible refinement: benchmark at ISCO-group level for generic titles.
- LLM tiebreak still available as a future precision step over top-K once retrieval is trusted.

**Next — Stage C:** after review, ESCO-core skill lookup (occupation→essential/optional) +
postings demand overlay (ESCO-skill frequency across the category's postings) → materialize
`job_benchmark` (one row per category). Tooling: deps now include sentence-transformers +
rapidfuzz; model `mpnet` cached locally.

## 14. DUAL BENCHMARK decision (2026-06): ESCO + CP2021 side by side

User decision: the report shows **two benchmarks per job title** — one **CP2021 (Italian)**
section and one **ESCO** section. Not either/or.

**Critical data fact:** CP2021 (ISTAT) is a *classification only — no skills*. The Italian
skills come from **INAPP** (Indagine Campionaria sulle Professioni / Sistema Informativo
sulle Professioni), keyed to CP2021 (sections: conoscenze, competenze/skill, attività, …,
O*NET-style with importance/level scores). So **CP2021 benchmark = ISTAT CP2021 codes/labels
+ INAPP competences**.

**Caveats (see `data/cp2021/README.md`):**
- INAPP CP2021 survey released in waves — 1st wave (2023) ~250/813 UP → native CP2021
  competence data may be **partial**. Complete legacy data is CP2011 → bridge via
  CP2011→CP2021 raccordo.
- The CP benchmark is only *distinct* from ESCO if we use INAPP **native** competences; just
  crosswalking CP→ESCO for skills would collapse the two into one.
- CP2021 units are coarser (~813) and Italian-native → likely **better matching** for the
  generic `job_category` strings than ESCO's 3,000 hyper-specific leaves.

**Sources (researched):** ISTAT CP2021 classification (direct xlsx via INAIL mirror) +
navigator at professioni.istat.it; INAPP Sistema Informativo (LOD/RDF/CSV) at
inapp.gov.it/professioni; CP2011↔CP2021 raccordo (ISTAT xlsx); CP↔ESCO via INAPP LMI or
ISCO-08 bridge. Full guide + URLs + needed columns in `data/cp2021/README.md`.

**Planned build (mirrors ESCO side):** tables `cp2021_profession`, `cp2021_skill`,
`cp2021_profession_skill`; `scripts/load_cp2021.py`; a second mapping `job_category →
CP2021 profession` (reuse the hybrid matcher); `job_benchmark` carries BOTH skill sets
(esco_* + cp2021_*).

**DATA IN HAND + API DISCOVERY (2026-06-03):**
- Downloaded to `data/cp2021/`: `CP2021.xlsx` (sheets primo..quinto_digit; **quinto_digit =
  813 unità professionali** with `cod_5` dotted `1.1.1.1.1`, `nome_5`, `descr_5`),
  `cp2021_classificazione.xlsx` (richer: +6th digit voci, affini), `cp2011_cp2021_raccordo.xlsx`
  (sheet 'raccordo III-V', real header on row 1: cod_3/nome_3 → cod_5/nome_5).
- **INAPP API solves the competence sourcing** — `https://api.inapp.org/professioni/survey.php
  ?codice=<cod_5>&idDataset=<N>`, public JSON, no auth. `codice` format == CP2021.xlsx
  `cod_5`. Datasets: 1=Compiti, 2=Conoscenze(+complessità), 4&5=Skill, 6=Attività,
  8=Stili, 22=RIASEC, 15–21 aggregated. Payload per dimension: importanza, complessita,
  label[{descDimensione,longDescDimensione}]. Also `search.php` (by name/task/skill/code).
  → No bulk competence file needed; fetch per mapped code (≤ few hundred calls).

**Concrete CP2021 build plan (ready to start):**
1. `load_cp2021.py` — load quinto_digit (813) → `cp2021_profession(cod_5, nome_5, descr_5)`;
   optionally load raccordo + 6th-digit voci/affini as extra match labels.
2. Extend the hybrid matcher to also map `job_category → cod_5` (against nome_5 + affini/voci)
   → `job_cp2021_map` (parallel to `job_occupation_map`); same review CSV approach.
3. `fetch_cp2021_skills.py` — for each mapped cod_5, call survey.php (datasets 1,2,4,5,6),
   keep top dimensions by `importanza` → `cp2021_profession_skill(cod_5, dim_code, type,
   label, importanza, complessita)`.
4. Stage C: `job_benchmark` carries both ESCO and CP2021 skill sets per category.

## 15. Stage C1 — ESCO-core benchmark: DONE (2026-06-03)

`scripts/materialize_benchmark.py` — single SQL INSERT...SELECT from `job_occupation_map` +
`esco_occupation_skill` → `job_benchmark`. Truncate+rebuild; re-run after each review pass.
Result: **306 rows, avg 24 essential + 33 optional ESCO skills, 0 empty.** Spot-checked
Magazziniere / Cuoco — sensible. `demand_skills` left empty (Stage C2).
NOTE: reflects current (mostly un-reviewed) mappings — re-run after import_review.py.

## 16. Stage C2 — postings demand overlay: DESIGN PENDING (user to choose method)

Goal: per category, which ESCO skills the real postings demand, with weights. Open forks:
- **Posting text source:** mirror job_description/job_highlights locally vs query external
  on demand vs sample N postings/category (~97k postings in window).
- **Skill-detection method:** (a) lexical/FTS match of ESCO skill labels+altLabels in text —
  deterministic, explainable ("in X% of postings"), but LOW recall (ESCO skills are long verb
  phrases rarely appearing verbatim); (b) embedding match (mpnet, posting/sentence → ESCO
  skills) — better recall, fuzzy, more compute, threshold-sensitive; (c) LLM extraction —
  best, but user deferred LLM.
- **Weight:** posting frequency (% of postings) vs summed similarity.
Keep both layers in ESCO-skill space so core + overlay are comparable. Emerging/non-ESCO
skills → future enrichment agent, not here.

**Tested (2026-06-03) — embedding overlay does NOT work well; built `overlay_demand.py` but
results are noisy:**
- Doc-level (whole posting → nearest ESCO skills): captures the posting's *theme*, not its
  requirements. Cuoco's top "demand" skills were tourism/hotel (area/offerta turistica,
  valutare destinazioni turistiche, gestire gruppi di turisti), not cooking.
- Sentence-level (split posting → nearest skill per sentence, thresh 0.55): worse — job-ad
  boilerplate (benefits, company blurb, contract) matches spurious abstract ESCO skills
  (rivedere bozze ×40, considerare i fusi orari, fare viaggi internazionali, processo
  creativo come artista).
- Root cause: ESCO skill labels are abstract verb-phrases; nearest-neighbour of noisy ad
  text is plausible-but-wrong. Real skill extraction from postings needs the **LLM**.
- **Decision/recommendation:** ship ESCO-core only; do the overlay with the LLM later (read
  postings, extract→map to ESCO). `overlay_demand.py` kept but parked; test data cleared
  (job_benchmark = core only, demand_skills=[]). Skill embeddings cached in data/cache/.

## 17. CP2021 track — BUILT (2026-06-03)

Data in `data/cp2021/`: CP2021.xlsx, cp2021_classificazione.xlsx, cp2011_cp2021_raccordo.xlsx.
New schema: `cp2021_profession`, `cp2021_label`, `cp2021_profession_skill`, `job_cp2021_map`;
`job_benchmark` gained `cp2021_cod_5, cp2021_label, cp2021_skills, n_cp2021`.

- **`load_cp2021.py`** — 813 professions (quinto_digit) + **7,626 match labels** (nome_5 +
  6,813 voci professionali from the 6th-digit sheet, used like ESCO altLabels).
- **`classify_cp2021.py`** — hybrid match job_category→cod_5 over all labels (best per
  profession). With voci: **59 flagged** (vs 157 with nome_5 only). Quality comparable to
  ESCO: Contabile→Contabili (0.92), Sistemista→Amministratori di sistemi (0.94),
  Cuoco→Cuochi in alberghi e ristoranti, Promoter→Tecnici della pubblicità. Some still off
  (Magazziniere→wholesale, Operaio→manager) → human review.
- **`fetch_cp2021_skills.py`** — pulls per mapped cod_5 from INAPP API survey.php (datasets
  1=compiti,2=conoscenze,4/5=skill,6=attività). Rich weighted data: ~33 conoscenze, ~93
  skill, 57 attività per profession, importanza 0–100. Handles both JSON shapes; ON CONFLICT
  dedup; skips empty codes. Tested 5 codes = 971 rows, all populated.
- **`materialize_benchmark.py`** — now fills BOTH sections: ESCO essential/optional +
  CP2021 top-30 (skill+conoscenze) by importanza (`CP2021_TOPN` env).

Two benchmarks per job_category now flow into one `job_benchmark` row → the report's two
sections. Review tooling (export/import_review) currently targets ESCO's job_occupation_map;
extend to job_cp2021_map when reviewing CP2021 mappings.

**DONE:** full INAPP fetch = 202/202 mapped codes had data, **39,274 competence rows**.
Materialize → **306 rows with BOTH sections**: ESCO (avg 24 essential / 33 optional) +
CP2021 (avg 30 competences, 306/306 filled). Observation: ESCO gives task-specific skills,
CP2021/INAPP gives transversal O*NET-style competences (comm/listening rate high) +
conoscenze — genuinely complementary, which is the point of showing both.

## 18. STATUS SUMMARY (end of 2026-06-03 session)

**Working end to end (local):** ESCO + CP2021 dual benchmark in `job_benchmark`, 306
categories. Pipelines: mirror_categories → classify (esco+cp2021) → load (esco+cp2021) →
fetch_cp2021_skills → materialize. Review tooling for ESCO mappings (export/import_review).

**Known TODO / next:**
- Human review of mappings (ESCO: 41 flagged; CP2021: 59 flagged). import_review currently
  ESCO-only → extend to job_cp2021_map.
- LLM phase (deferred): (a) demand overlay extraction from postings, (b) classification
  tiebreak precision for both taxonomies.
- CP2021 benchmark currently uses skill+conoscenze top-30; consider adding compiti/attività.
- Wire into Workint (FastAPI router, Milvus, Angular) — see §10. CV-side gap analysis +
  report generation still to come (this session built the benchmark side).
- Lots of uncommitted work as of this point — COMMIT recommended.

## 19. CV-side scope (confirmed 2026-06-03) — NOT yet built

Two frontend-facing flows, converging on a common worker profile → gap vs target job:
- **Flow 1 (ad-hoc CV):** frontend → **existing external CV extractor** (endpoint TBD, built
  by someone else) → structured profile (professional experience, education, skills,
  languages, …).
- **Flow 2 (stored CV):** frontend passes a worker id → read pre-extracted rich info from
  the **`workers` table in `workint-clone`** (same external DB as offerte_lavoro). No
  extraction step.
- **Common path:** compare profile to the **target job = worker's preferred or current
  role** → return structured gap (present vs missing) against **BOTH ESCO and CP2021**.
- **Stretch (later):** gap-closing suggestions (courses, books, …) — likely needs external
  data + LLM.

Deliverable = backend **FastAPI** endpoints for the frontend (both flows). Gap analysis is
**deterministic** (embedding match of worker skills vs benchmark skills); narrative report +
suggestions are the LLM phase.

**To resolve when schemas arrive:**
- How `workers`' "preferred/current job" links to a `job_benchmark` row (matchable code/
  category → direct join; else run through the hybrid matcher).
- `workers` skill format (rich, exact shape TBD) — drives the matching.
- **Scoping caveat:** benchmark is skill-centric (ESCO/CP2021 skills). Skills gap is solid;
  education/experience/languages have no benchmark field yet → lighter/heuristic unless we
  add reference data.

## 20. API backend — BUILT (2026-06-03)

`app/` package (FastAPI). Frontend = production Angular (by frontendist); our test frontend =
FastAPI Swagger at `/docs`. Run: `python -m uvicorn app.main:app --reload --port 8077`.
- `app/config.py` — engine + lazy mpnet model (lru_cache); GAP_COVER_THRESHOLD (0.62).
- `app/models.py` — WorkerProfile, AnalyzeProfileRequest, GapResult/BenchmarkGap/SkillMatch (the contract).
- `app/gap.py` — deterministic engine: worker skills vs job_benchmark row; embed both, per
  benchmark skill take best worker match, covered if cosine ≥ threshold else missing; ESCO +
  CP2021 sections, coverage %.
- `app/main.py` — `POST /skills-gap/analyze-profile` (WORKING), `analyze-cv` (Flow1 STUB 501),
  `analyze-worker/{id}` (Flow2 STUB 501), `/health`.

Verified: analyze-profile against Cuoco returns ESCO 54% coverage (sensible matched/missing),
clean UTF-8. **Finding:** CP2021 gap coverage ~0% — CP2021 competences are abstract/transversal
(Comunicare, Destrezza…) and don't embedding-match concrete CV skill phrases. → ESCO gap is the
meaningful one; CP2021 needs different presentation (competence profile) or LLM, later.

**Stubs to wire when inputs arrive:** Flow1 = call external extractor → WorkerProfile; Flow2 =
read `workers` row + resolve target job → WorkerProfile; both then call analyze().
Not yet: auth, CORS for the Angular origin, async, persistence of results.

## 21. Both flows wired + target resolution (2026-06-03)

`app/sources.py` — input adapters:
- **Flow 1** `profile_from_extracted(data)` — tolerant mapper for the extractor's JSON
  (handles nested `data`, Italian keys ruolo/competenze/lingue, skills as str | list[str] |
  list[dict]). `analyze-cv` now FUNCTIONAL: post the extractor output + target → gap.
  (Server-side call to the extractor URL still TODO pending its endpoint.)
- **Flow 2** `load_worker(id)` — reads the REAL `workers` schema (inspected; 85 rows):
  worker_id / worker_personal_skills / worker_preferred_jobs / worker_languages
  (+ professional_exp/education available). PII cols never read. `analyze-worker/{id}`
  FUNCTIONAL. Columns env-overridable (WORKERS_COL_*).

Skills in `workers` are free text (newline/comma) → split into skill phrases; data quality
varies (some junk/empty). `worker_preferred_jobs` often empty → 422 "no target"; when present
it's a title like "Cuoca".

`app/gap.py` — added **target resolution**: a free-text job ("Cuoca") → nearest benchmark
category via embeddings (cached `_category_index`, RESOLVE_MIN_SCORE=0.55). `_load_benchmark`
now: category_id → exact; job_category → exact then nearest-match fallback. Verified worker 5
'Cuoca' → 'Cuoco' (0.83). CORS middleware added (CORS_ORIGINS).

**Backend status: both flows functional locally.** Remaining: server-side extractor call
(Flow 1, pending endpoint), auth, result persistence, narrative report + gap-closing
suggestions (LLM phase). CP2021 gap still ~0% for concrete skills (see §20).

## 22. CV extractor wired (2026-06-03)

Extractor endpoint received: **`POST http://10.20.2.6:32504/extract-cv-info`** — protected
(header `x-access-password`), `multipart/form-data` field `file` = PDF, **returns a JSON
string of MARKDOWN** ("informazioni del CV formattate in markdown per ogni categoria"). So
Flow 1 input is a PDF and the extractor output is markdown, NOT structured JSON.

Wired in `app/`:
- `config.py`: EXTRACTOR_URL (default the above), EXTRACTOR_PASSWORD (env; not yet provided).
- `sources.py`: `call_extractor(pdf_bytes)` (POST multipart + x-access-password → markdown);
  `profile_from_markdown(md)` — tolerant section parser (splits on #/##/**bold** headings,
  fuzzy-maps headings to skills/languages/experience/education/role via keyword groups,
  bullets or comma/newline items).
- `main.py`: `POST /skills-gap/analyze-cv` now takes a **PDF upload** → call_extractor →
  parse → gap. Added `POST /skills-gap/analyze-cv-markdown` (paste markdown; test path, no
  password) — verified: synthetic IT CV → 4 skills parsed → Cuoco ESCO 58%.

**NEED from user:** (1) the **x-access-password** (→ EXTRACTOR_PASSWORD in .env) to call the
real extractor; (2) a **sample of the real markdown** to confirm the actual section headings
match the parser's keyword groups (it's tolerant but tuned to guessed headings).
