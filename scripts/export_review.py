"""Export the category -> ESCO mappings to a CSV for human review.

One row per benchmarked category: the top-5 candidate ESCO occupations (c1 is the current
pick), confidence, and the review flag. Sorted so flagged + high-volume categories come
first.

To review: in the `pick` column put the number (1-5) of the correct candidate. Leave it
blank or 1 to accept the current pick. If the right occupation isn't among the 5, paste its
ESCO URI into `correct_uri`. Then run scripts/import_review.py to persist decisions.
"""
import csv
import json

import pandas as pd
from sqlalchemy import text

from db import ROOT, local_engine

OUT = ROOT / "data" / "review" / "job_occupation_review.csv"


def main() -> None:
    eng = local_engine()
    df = pd.read_sql(
        text(
            "SELECT m.category_id, m.job_category, c.posting_count, m.needs_review, "
            "       m.confidence, m.candidates_considered "
            "FROM job_occupation_map m "
            "JOIN job_category c ON c.category_id = m.category_id "
            "ORDER BY m.needs_review DESC, c.posting_count DESC"
        ),
        eng,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "category_id", "job_category", "posting_count", "needs_review", "confidence",
            "c1_current", "c2", "c3", "c4", "c5", "pick", "correct_uri", "notes",
        ])
        for r in df.itertuples(index=False):
            cc = r.candidates_considered
            cands = cc if isinstance(cc, list) else (json.loads(cc) if cc else [])
            labels = [c["label"] for c in cands[:5]] + [""] * 5
            w.writerow([
                r.category_id, r.job_category, r.posting_count, r.needs_review,
                round(float(r.confidence), 3),
                labels[0], labels[1], labels[2], labels[3], labels[4],
                "", "", "",
            ])

    print(f"Wrote {len(df)} rows to {OUT}")
    print(f"  flagged needs_review: {int(df['needs_review'].sum())}")
    print("Review: set `pick` (1-5) to choose the correct candidate, or `correct_uri` for "
          "one outside the top-5. Then run scripts/import_review.py.")


if __name__ == "__main__":
    main()
