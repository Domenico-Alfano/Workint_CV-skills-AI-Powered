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
-- The table the rest of the product reads from. Two layers of requirements:
--   essential_skills / optional_skills  -> ESCO core (deterministic)
--   demand_skills                       -> postings overlay [{uri,label,freq}]
CREATE TABLE IF NOT EXISTS job_benchmark (
    category_id         INTEGER PRIMARY KEY REFERENCES job_category(category_id),
    job_category        TEXT NOT NULL,
    occupation_uri      TEXT NOT NULL,
    occupation_label_it TEXT NOT NULL,
    isco_code           TEXT,
    essential_skills    JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ESCO core [{uri,label,type}]
    optional_skills     JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ESCO core
    demand_skills       JSONB NOT NULL DEFAULT '[]'::jsonb,  -- postings overlay [{uri,label,freq}]
    n_essential         INTEGER NOT NULL DEFAULT 0,
    n_optional          INTEGER NOT NULL DEFAULT 0,
    n_demand            INTEGER NOT NULL DEFAULT 0,
    esco_version        TEXT NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
