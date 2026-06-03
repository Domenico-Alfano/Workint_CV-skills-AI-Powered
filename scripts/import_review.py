"""Apply human review decisions from data/review/job_occupation_review.csv.

For each row:
  - `correct_uri` set            -> override occupation to that URI (method='manual')
  - `pick` in 2..5               -> override to that candidate's URI (method='manual')
  - `pick` == 1                  -> accept current pick (mark reviewed)
  - `pick` blank (and no uri)    -> untouched; left as-is, still needs_review
Touched rows get reviewed=true and needs_review=false.
"""
import csv
import json

from sqlalchemy import text

from db import ROOT, local_engine

CSV_PATH = ROOT / "data" / "review" / "job_occupation_review.csv"


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"No review file at {CSV_PATH}. Run scripts/export_review.py first.")

    eng = local_engine()
    # Preload candidate lists to resolve `pick` -> URI, and valid URIs to validate correct_uri.
    with eng.connect() as c:
        cand_by_cat = {
            row[0]: (row[1] if isinstance(row[1], list) else (json.loads(row[1]) if row[1] else []))
            for row in c.execute(text("SELECT category_id, candidates_considered FROM job_occupation_map"))
        }
        valid_uris = {row[0] for row in c.execute(text("SELECT occupation_uri FROM esco_occupation"))}

    updates, accepted_cids, errors, total = [], [], [], 0
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            total += 1
            cid = int(r["category_id"])
            correct_uri = (r.get("correct_uri") or "").strip()
            pick = (r.get("pick") or "").strip()

            if correct_uri:
                if correct_uri not in valid_uris:
                    errors.append(f"cat {cid}: correct_uri not in ESCO ({correct_uri})")
                    continue
                updates.append({"cid": cid, "uri": correct_uri, "method": "manual"})
            elif pick in {"2", "3", "4", "5"}:
                cands = cand_by_cat.get(cid, [])
                idx = int(pick) - 1
                if idx >= len(cands):
                    errors.append(f"cat {cid}: pick {pick} has no candidate")
                    continue
                updates.append({"cid": cid, "uri": cands[idx]["uri"], "method": "manual"})
            elif pick == "1":
                accepted_cids.append(cid)
            # blank pick & no correct_uri -> untouched, leave needs_review as-is

    with eng.begin() as conn:
        for u in updates:
            conn.execute(
                text(
                    "UPDATE job_occupation_map SET occupation_uri=:uri, classification_method=:method, "
                    "confidence=1.0, reviewed=true, needs_review=false WHERE category_id=:cid"
                ),
                u,
            )
        if accepted_cids:
            conn.execute(
                text(
                    "UPDATE job_occupation_map SET reviewed=true, needs_review=false "
                    "WHERE category_id = ANY(:cids)"
                ),
                {"cids": accepted_cids},
            )

    print(f"Applied {len(updates)} overrides; {len(accepted_cids)} accepted as-is; "
          f"{total - len(updates) - len(accepted_cids)} left untouched.")
    if errors:
        print("Skipped rows:")
        for e in errors:
            print("  -", e)


if __name__ == "__main__":
    main()
