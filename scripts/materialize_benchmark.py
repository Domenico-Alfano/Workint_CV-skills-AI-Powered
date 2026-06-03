"""Stage C: materialize the benchmark — one row per benchmarked job_category, with BOTH:
  - ESCO section: the mapped ESCO occupation's essential / optional skills.
  - CP2021 section: the mapped CP2021 profession's top competences (skill + conoscenze)
    by INAPP importance score.

Deterministic lookups over the version-pinned ESCO snapshot + the CP2021/INAPP data.
Reflects current mappings, so re-run after each review pass (import_review.py) or refetch.
The postings demand overlay (demand_skills) needs the LLM and is left empty here.
"""
import os

from sqlalchemy import text

from db import ESCO_VERSION, local_engine

# Aggregate an occupation's skills of a given relation type into a JSON array.
_SKILLS_SUBQUERY = """
    SELECT os.occupation_uri,
           jsonb_agg(jsonb_build_object('uri', s.skill_uri, 'label', s.preferred_label_it,
                                        'type', s.skill_type) ORDER BY s.preferred_label_it) AS skills,
           count(*) AS n
    FROM esco_occupation_skill os
    JOIN esco_skill s ON s.skill_uri = os.skill_uri
    WHERE os.relation_type = :rel
    GROUP BY os.occupation_uri
"""

INSERT_SQL = f"""
INSERT INTO job_benchmark
    (category_id, job_category, occupation_uri, occupation_label_it, isco_code,
     essential_skills, optional_skills, demand_skills,
     n_essential, n_optional, n_demand, esco_version, generated_at)
SELECT m.category_id, m.job_category, m.occupation_uri, o.preferred_label_it, o.isco_code,
       COALESCE(ess.skills, '[]'::jsonb), COALESCE(opt.skills, '[]'::jsonb), '[]'::jsonb,
       COALESCE(ess.n, 0), COALESCE(opt.n, 0), 0, :ver, now()
FROM job_occupation_map m
JOIN job_category c   ON c.category_id = m.category_id AND c.in_benchmark
JOIN esco_occupation o ON o.occupation_uri = m.occupation_uri
LEFT JOIN ({_SKILLS_SUBQUERY.replace(':rel', "'essential'")}) ess ON ess.occupation_uri = m.occupation_uri
LEFT JOIN ({_SKILLS_SUBQUERY.replace(':rel', "'optional'")})  opt ON opt.occupation_uri = m.occupation_uri
"""

# CP2021 section: top-N competences (skill + conoscenze) per profession by importance.
CP2021_UPDATE_SQL = """
WITH ranked AS (
    SELECT s.cod_5, s.section, s.label, s.importanza,
           row_number() OVER (PARTITION BY s.cod_5 ORDER BY s.importanza DESC NULLS LAST) AS rn
    FROM cp2021_profession_skill s
    WHERE s.section IN ('skill', 'conoscenze')
), top AS (
    SELECT cod_5,
           jsonb_agg(jsonb_build_object('section', section, 'label', label,
                                        'importanza', importanza) ORDER BY importanza DESC NULLS LAST) AS skills,
           count(*) AS n
    FROM ranked WHERE rn <= :topn GROUP BY cod_5
)
UPDATE job_benchmark b
SET cp2021_cod_5 = m.cod_5,
    cp2021_label = p.nome_5,
    cp2021_skills = COALESCE(t.skills, '[]'::jsonb),
    n_cp2021 = COALESCE(t.n, 0)
FROM job_cp2021_map m
JOIN cp2021_profession p ON p.cod_5 = m.cod_5
LEFT JOIN top t ON t.cod_5 = m.cod_5
WHERE b.category_id = m.category_id
"""


def main() -> None:
    cp_topn = int(os.getenv("CP2021_TOPN", "30"))
    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE job_benchmark"))
        conn.execute(text(INSERT_SQL), {"ver": ESCO_VERSION})       # ESCO section
        conn.execute(text(CP2021_UPDATE_SQL), {"topn": cp_topn})    # CP2021 section
        n, ess, opt, cp, cp_filled = conn.execute(
            text(
                "SELECT count(*), COALESCE(avg(n_essential),0), COALESCE(avg(n_optional),0), "
                "COALESCE(avg(n_cp2021),0), COALESCE(sum((n_cp2021>0)::int),0) FROM job_benchmark"
            )
        ).fetchone()
    print(
        f"Materialized {n} benchmark rows.\n"
        f"  ESCO   : avg essential={ess:.1f}, avg optional={opt:.1f}\n"
        f"  CP2021 : avg competences={cp:.1f}, {cp_filled}/{n} rows with CP2021 skills"
    )


if __name__ == "__main__":
    main()
