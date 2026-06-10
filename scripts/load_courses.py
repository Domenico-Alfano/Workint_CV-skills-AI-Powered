"""Load the course catalog (CSV ;-separated) into the local `course` table.

Default source is data/courses_seed.csv — DEMO content broad enough to exercise the
matching; replace with the real catalog (GOL / regional / internal) keeping the same
columns: title;provider;url;description;hours. Matching to skills is semantic (done by
the API at request time), so no ESCO mapping column is needed here.

Run:  python scripts/load_courses.py [path/to/catalog.csv]
"""
import csv
import sys
from pathlib import Path

from sqlalchemy import text

from db import ROOT, local_engine

DEFAULT_CSV = ROOT / "data" / "courses_seed.csv"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    with src.open(encoding="utf-8-sig", newline="") as f:
        rows = [
            {
                "title": (r.get("title") or "").strip(),
                "provider": (r.get("provider") or "").strip() or None,
                "url": (r.get("url") or "").strip() or None,
                "description": (r.get("description") or "").strip() or None,
                "hours": int(r["hours"]) if (r.get("hours") or "").strip().isdigit() else None,
            }
            for r in csv.DictReader(f, delimiter=";")
            if (r.get("title") or "").strip()
        ]
    if not rows:
        raise SystemExit(f"No courses found in {src}")

    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE course RESTART IDENTITY"))
        conn.execute(
            text(
                "INSERT INTO course (title, provider, url, description, hours) "
                "VALUES (:title, :provider, :url, :description, :hours)"
            ),
            rows,
        )
    print(f"Loaded {len(rows)} courses from {src.name} into `course`.")


if __name__ == "__main__":
    main()
