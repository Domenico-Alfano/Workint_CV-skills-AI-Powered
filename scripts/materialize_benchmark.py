"""Stage C1: materialize the ESCO-core benchmark — one row per benchmarked job_category.

For each in_benchmark category we take its mapped ESCO occupation (job_occupation_map) and
pull that occupation's essential / optional skills from ESCO. Deterministic: pure lookup
over the version-pinned ESCO snapshot. Reflects whatever mappings are currently in
job_occupation_map, so re-run after each review pass (import_review.py).

The postings demand overlay (demand_skills) is Stage C2 and is left empty here.
"""
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


def main() -> None:
    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE job_benchmark"))
        conn.execute(text(INSERT_SQL), {"ver": ESCO_VERSION})
        n, ess, opt, empty = conn.execute(
            text(
                "SELECT count(*), COALESCE(avg(n_essential),0), COALESCE(avg(n_optional),0), "
                "COALESCE(sum((n_essential=0)::int),0) FROM job_benchmark"
            )
        ).fetchone()
    print(
        f"Materialized {n} benchmark rows (ESCO core). "
        f"avg essential={ess:.1f}, avg optional={opt:.1f}, {empty} rows with 0 essential skills."
    )


if __name__ == "__main__":
    main()
