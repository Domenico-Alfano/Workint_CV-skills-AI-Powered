-- =============================================================
-- Workint Skills Benchmark — local schema (testing)
--
-- Design intent: the benchmark is DETERMINISTIC. All "what skills
-- does occupation X require" content comes from a version-pinned
-- ESCO snapshot (esco_* tables). The only non-deterministic step
-- is mapping a free-text job -> an ESCO occupation, which is
-- isolated in job_occupation_map with a full audit trail.
-- =============================================================

-- ---------- Benchmark unit: distinct job_category from offerte_lavoro ----------
-- One row per distinct `offerte_lavoro.job_category` observed within a snapshot
-- date window. `in_benchmark` flags those meeting the min-postings threshold
-- (the ones we actually build benchmarks for). The window + snapshot make the
-- selection reproducible even though the source table is volatile.
CREATE TABLE IF NOT EXISTS job_category (
    category_id     SERIAL PRIMARY KEY,
    job_category    TEXT NOT NULL UNIQUE,
    posting_count   INTEGER NOT NULL,
    date_column     TEXT NOT NULL,             -- which source column the window used
    date_from       DATE,
    date_to         DATE,
    in_benchmark    BOOLEAN NOT NULL DEFAULT false,
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- ESCO snapshot (treat as read-only after load) ----------
CREATE TABLE IF NOT EXISTS esco_occupation (
    occupation_uri      TEXT PRIMARY KEY,
    isco_code           TEXT,
    preferred_label_it  TEXT NOT NULL,
    alt_labels_it       TEXT,
    description_it      TEXT,
    esco_version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS esco_skill (
    skill_uri           TEXT PRIMARY KEY,
    preferred_label_it  TEXT NOT NULL,
    alt_labels_it       TEXT,
    skill_type          TEXT,         -- knowledge | skill/competence
    reuse_level         TEXT,         -- transversal | cross-sector | sector-specific | occupation-specific
    description_it      TEXT,
    esco_version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS esco_occupation_skill (
    occupation_uri      TEXT NOT NULL REFERENCES esco_occupation(occupation_uri),
    skill_uri           TEXT NOT NULL REFERENCES esco_skill(skill_uri),
    relation_type       TEXT NOT NULL,    -- essential | optional
    PRIMARY KEY (occupation_uri, skill_uri, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_occ_skill_occ ON esco_occupation_skill(occupation_uri);

-- ---------- Mapping job_category -> ESCO occupation (the ONLY soft step) ----------
CREATE TABLE IF NOT EXISTS job_occupation_map (
    category_id            INTEGER PRIMARY KEY REFERENCES job_category(category_id),
    job_category           TEXT,
    occupation_uri         TEXT REFERENCES esco_occupation(occupation_uri),
    classification_method  TEXT,        -- exact_code | embedding | llm | manual
    confidence             REAL,
    candidates_considered  JSONB,       -- top-K {uri,label,score} for audit
    esco_version           TEXT NOT NULL,
    needs_review           BOOLEAN NOT NULL DEFAULT false,
    reviewed               BOOLEAN NOT NULL DEFAULT false,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Materialized benchmark: ONE ROW PER job_category ----------
-- The table the API reads from. ESCO essential/optional skills + (later, via §10) the
-- CP2021 columns added below.
CREATE TABLE IF NOT EXISTS job_benchmark (
    category_id         INTEGER PRIMARY KEY REFERENCES job_category(category_id),
    job_category        TEXT NOT NULL,
    occupation_uri      TEXT NOT NULL,
    occupation_label_it TEXT NOT NULL,
    isco_code           TEXT,
    essential_skills    JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ESCO core [{uri,label,type}]
    optional_skills     JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ESCO core
    n_essential         INTEGER NOT NULL DEFAULT 0,
    n_optional          INTEGER NOT NULL DEFAULT 0,
    esco_version        TEXT NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- CP2021 (ISTAT) track — second benchmark. Professions from the
-- CP2021 classification; skills from the INAPP API (survey.php).
-- ============================================================

-- The 813 unità professionali (quinto_digit). cod_5 == INAPP API `codice`.
CREATE TABLE IF NOT EXISTS cp2021_profession (
    cod_5       TEXT PRIMARY KEY,         -- dotted 5-level code, e.g. 2.1.1.1.1
    nome_5      TEXT NOT NULL,
    descr_5     TEXT
);

-- All match labels for a profession: its nome_5 + the 6th-digit "voci professionali"
-- (specific job titles). Used like ESCO altLabels to boost classification recall.
CREATE TABLE IF NOT EXISTS cp2021_label (
    cod_5   TEXT NOT NULL REFERENCES cp2021_profession(cod_5),
    label   TEXT NOT NULL,
    source  TEXT NOT NULL          -- 'nome_5' | 'voce'
);
CREATE INDEX IF NOT EXISTS idx_cp_label_cod ON cp2021_label(cod_5);

-- INAPP survey dimensions per profession (knowledge/skill/activity/task/style + scores).
CREATE TABLE IF NOT EXISTS cp2021_profession_skill (
    cod_5         TEXT NOT NULL REFERENCES cp2021_profession(cod_5),
    dataset_id    INTEGER NOT NULL,       -- INAPP idDataset (1 compiti,2 conoscenze,4/5 skill,6 attività,8 stili)
    section       TEXT NOT NULL,          -- our label for the dataset
    dim_code      TEXT NOT NULL,          -- JSON key within the dataset (e.g. B15, or task number)
    label         TEXT NOT NULL,
    importanza    REAL,
    complessita   REAL,
    PRIMARY KEY (cod_5, dataset_id, dim_code)
);
CREATE INDEX IF NOT EXISTS idx_cp_skill_cod ON cp2021_profession_skill(cod_5);

-- Mapping job_category -> CP2021 profession (parallel to job_occupation_map).
CREATE TABLE IF NOT EXISTS job_cp2021_map (
    category_id            INTEGER PRIMARY KEY REFERENCES job_category(category_id),
    job_category           TEXT,
    cod_5                  TEXT REFERENCES cp2021_profession(cod_5),
    classification_method  TEXT,
    confidence             REAL,
    candidates_considered  JSONB,
    needs_review           BOOLEAN NOT NULL DEFAULT false,
    reviewed               BOOLEAN NOT NULL DEFAULT false,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Demand trend per category (scripts/compute_trends.py) ----------
-- Posting counts in two adjacent windows of `window_days` ending at `anchor_date`.
-- growth_pct = percent change of the category's SHARE of postings between windows
-- (robust to scraper-volume swings), the "is this job growing?" signal consumed by
-- the /skills-gap/recommend-* endpoints. NOTE: keep literal percent signs out of this
-- file — psycopg2 treats them as placeholders in exec_driver_sql (init_db.py).
CREATE TABLE IF NOT EXISTS category_trend (
    category_id     INTEGER PRIMARY KEY REFERENCES job_category(category_id),
    job_category    TEXT NOT NULL,
    recent_count    INTEGER NOT NULL,
    previous_count  INTEGER NOT NULL,
    growth_pct      REAL,                -- NULL = not enough data to call a trend
    window_days     INTEGER NOT NULL,
    anchor_date     DATE,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Course catalog (scripts/load_courses.py) ----------
-- Courses are matched to MISSING skills semantically (mpnet over title+description),
-- so the catalog can be free text — no manual ESCO mapping needed. The shipped seed
-- (data/courses_seed.csv) is demo content: replace with the real catalog (GOL/regional).
CREATE TABLE IF NOT EXISTS course (
    course_id   SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    provider    TEXT,
    url         TEXT,
    description TEXT,
    hours       INTEGER,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Multi-source catalog: each load replaces only its own `source` (seed | formatemp |
-- gol_<regione> | udemy | ...), so sources can be refreshed on independent cadences.
ALTER TABLE course ADD COLUMN IF NOT EXISTS source      TEXT NOT NULL DEFAULT 'seed';
ALTER TABLE course ADD COLUMN IF NOT EXISTS region      TEXT;
ALTER TABLE course ADD COLUMN IF NOT EXISTS external_id TEXT;
CREATE INDEX IF NOT EXISTS idx_course_source ON course(source);

-- CP2021 columns on the materialized benchmark (the second report section).
ALTER TABLE job_benchmark ADD COLUMN IF NOT EXISTS cp2021_cod_5  TEXT;
ALTER TABLE job_benchmark ADD COLUMN IF NOT EXISTS cp2021_label  TEXT;
ALTER TABLE job_benchmark ADD COLUMN IF NOT EXISTS cp2021_skills JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE job_benchmark ADD COLUMN IF NOT EXISTS n_cp2021      INTEGER NOT NULL DEFAULT 0;
