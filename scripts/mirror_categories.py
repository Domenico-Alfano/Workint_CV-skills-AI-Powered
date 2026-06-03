"""Snapshot distinct `offerte_lavoro.job_category` (+ posting counts) within the date
window into the local `job_category` table.

The benchmark unit is the distinct job_category. `in_benchmark` is set when a category has
>= MIN_POSTINGS postings (we build benchmarks for those). The window + recorded date range
keep the selection reproducible even though the source table is volatile.
"""
import pandas as pd
from sqlalchemy import text

from db import (
    DATE_COLUMN,
    DATE_FROM,
    DATE_TO,
    MIN_POSTINGS,
    POSTINGS_TABLE,
    external_engine,
    local_engine,
    safe_identifier,
)


def main() -> None:
    tbl = safe_identifier(POSTINGS_TABLE)
    col = safe_identifier(DATE_COLUMN)

    where = f"{col} >= :date_from"
    params = {"date_from": DATE_FROM}
    if DATE_TO:
        where += f" AND {col} <= :date_to"
        params["date_to"] = DATE_TO

    ext = external_engine()
    with ext.connect() as c:
        max_dt = c.execute(text(f"SELECT max({col}) FROM {tbl} WHERE {where}"), params).scalar()
        df = pd.read_sql(
            text(
                f"SELECT job_category, count(*) AS n FROM {tbl} "
                f"WHERE {where} AND job_category IS NOT NULL AND btrim(job_category) <> '' "
                "GROUP BY job_category ORDER BY n DESC"
            ),
            c,
            params=params,
        )

    date_to_eff = DATE_TO or (max_dt.date().isoformat() if max_dt else None)
    df["in_benchmark"] = df["n"] >= MIN_POSTINGS
    total_postings = int(df["n"].sum())
    n_bench = int(df["in_benchmark"].sum())
    covered = int(df.loc[df["in_benchmark"], "n"].sum())
    cov = 100.0 * covered / max(total_postings, 1)
    print(
        f"Window {DATE_FROM}..{date_to_eff} on {col}: {total_postings} postings, "
        f"{len(df)} categories; {n_bench} have >= {MIN_POSTINGS} postings ({cov:.1f}% coverage)."
    )

    rows = [
        {
            "job_category": r.job_category,
            "posting_count": int(r.n),
            "date_column": col,
            "date_from": DATE_FROM,
            "date_to": date_to_eff,
            "in_benchmark": bool(r.in_benchmark),
        }
        for r in df.itertuples(index=False)
    ]
    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE job_category RESTART IDENTITY CASCADE"))
        if rows:
            conn.execute(
                text(
                    "INSERT INTO job_category "
                    "(job_category, posting_count, date_column, date_from, date_to, in_benchmark) "
                    "VALUES (:job_category, :posting_count, :date_column, :date_from, :date_to, :in_benchmark)"
                ),
                rows,
            )
    print(f"Loaded {len(rows)} categories into local job_category ({n_bench} flagged in_benchmark).")


if __name__ == "__main__":
    main()
