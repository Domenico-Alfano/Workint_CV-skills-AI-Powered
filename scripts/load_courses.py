"""Load a course catalog (CSV ;-separated) into the local `course` table.

Multi-source: each run replaces ONLY the rows of its --source, so catalogs from
different origins (internal/Forma.Temp, regional GOL exports, MOOC dumps) coexist and
refresh on independent cadences. Matching to skills is semantic (done by the API at
request time), so no ESCO mapping column is needed — title+description free text is fine.

CSV columns: title;provider;url;description;hours  (+ optional region;external_id)
The shipped data/courses_seed.csv is DEMO content (source 'seed'): drop it once a real
catalog is in (python scripts/load_courses.py --delete-source seed).

Examples:
  python scripts/load_courses.py                                   # seed (demo)
  python scripts/load_courses.py catalogo_ft.csv --source formatemp
  python scripts/load_courses.py gol_lazio.csv --source gol_lazio --region Lazio
  python scripts/load_courses.py --delete-source seed

After loading, refresh the running API:  POST /skills-gap/reload-courses  (no restart).
"""
import argparse
import csv
from pathlib import Path

from sqlalchemy import text

from db import ROOT, local_engine

DEFAULT_CSV = ROOT / "data" / "courses_seed.csv"


def read_catalog(src: Path, region: str | None) -> list[dict]:
    with src.open(encoding="utf-8-sig", newline="") as f:
        return [
            {
                "title": (r.get("title") or "").strip(),
                "provider": (r.get("provider") or "").strip() or None,
                "url": (r.get("url") or "").strip() or None,
                "description": (r.get("description") or "").strip() or None,
                "hours": int(r["hours"]) if (r.get("hours") or "").strip().isdigit() else None,
                "region": (r.get("region") or "").strip() or region,
                "external_id": (r.get("external_id") or "").strip() or None,
            }
            for r in csv.DictReader(f, delimiter=";")
            if (r.get("title") or "").strip()
        ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path", nargs="?", default=str(DEFAULT_CSV))
    ap.add_argument("--source", default="seed", help="catalog origin tag (replaced per run)")
    ap.add_argument("--region", default=None, help="default region for rows without one")
    ap.add_argument("--delete-source", default=None, metavar="SOURCE",
                    help="just delete this source's rows and exit")
    args = ap.parse_args()

    eng = local_engine()
    if args.delete_source:
        with eng.begin() as conn:
            n = conn.execute(text("DELETE FROM course WHERE source = :s"),
                             {"s": args.delete_source}).rowcount
        print(f"Deleted {n} courses of source '{args.delete_source}'.")
        return

    rows = read_catalog(Path(args.csv_path), args.region)
    if not rows:
        raise SystemExit(f"No courses found in {args.csv_path}")
    for r in rows:
        r["source"] = args.source

    with eng.begin() as conn:
        deleted = conn.execute(text("DELETE FROM course WHERE source = :s"),
                               {"s": args.source}).rowcount
        conn.execute(
            text(
                "INSERT INTO course (title, provider, url, description, hours, source, region, external_id) "
                "VALUES (:title, :provider, :url, :description, :hours, :source, :region, :external_id)"
            ),
            rows,
        )
        total = conn.execute(text("SELECT count(*) FROM course")).scalar()
    print(f"Source '{args.source}': {deleted} replaced by {len(rows)} courses "
          f"(catalog total: {total}). Now POST /skills-gap/reload-courses (or restart).")


if __name__ == "__main__":
    main()
