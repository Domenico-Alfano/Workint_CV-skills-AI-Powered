"""Compute a demand trend per benchmark category from posting counts.

Counts postings per job_category in two adjacent windows of TREND_WINDOW_DAYS ending at
the anchor date (newest posting, or TREND_ANCHOR_DATE to pin it):

    previous = (anchor - 2w, anchor - w]      recent = (anchor - w, anchor]

growth_pct compares the category's SHARE of postings in each window, not absolute
counts — the source table's total volume swings with scraper activity (e.g. 568k in
Aug 2025 vs 15 in Feb 2026), so absolute growth would measure the scraper, not the
market. Share growth cancels that out: +20% means "this job takes 20% more of the
market than before".

Categories with fewer than TREND_MIN_POSTINGS postings across both windows get
growth_pct NULL (too noisy). Results land in local `category_trend`, keyed to
job_category rows by exact label; the recommend endpoints read it (and degrade to
neutral if empty).

Run after mirror_categories.py (needs the local job_category snapshot). If the source
went quiet recently, pin TREND_ANCHOR_DATE to the last healthy date — the script warns
when the recent window looks starved.
"""
import os
from datetime import timedelta

from sqlalchemy import text

from db import (
    DATE_COLUMN,
    POSTINGS_TABLE,
    TREND_MIN_POSTINGS,
    TREND_WINDOW_DAYS,
    external_engine,
    local_engine,
    safe_identifier,
)

TREND_ANCHOR_DATE = os.getenv("TREND_ANCHOR_DATE") or None  # e.g. 2025-10-31


def main() -> None:
    tbl = safe_identifier(POSTINGS_TABLE)
    col = safe_identifier(DATE_COLUMN)

    ext = external_engine()
    with ext.connect() as c:
        anchor = (
            c.execute(text("SELECT CAST(:d AS timestamp)"), {"d": TREND_ANCHOR_DATE}).scalar()
            if TREND_ANCHOR_DATE
            else c.execute(text(f"SELECT max({col}) FROM {tbl}")).scalar()
        )
        if anchor is None:
            raise SystemExit(f"No postings in {tbl}; nothing to compute.")
        recent_from = anchor - timedelta(days=TREND_WINDOW_DAYS)
        prev_from = anchor - timedelta(days=2 * TREND_WINDOW_DAYS)
        rows = c.execute(
            text(
                f"SELECT job_category, "
                f"  count(*) FILTER (WHERE {col} >  :recent_from) AS recent, "
                f"  count(*) FILTER (WHERE {col} <= :recent_from) AS previous "
                f"FROM {tbl} "
                f"WHERE {col} > :prev_from AND {col} <= :anchor "
                f"  AND job_category IS NOT NULL AND btrim(job_category) <> '' "
                f"GROUP BY job_category"
            ),
            {"anchor": anchor, "recent_from": recent_from, "prev_from": prev_from},
        ).all()

    counts = {r[0]: (int(r[1]), int(r[2])) for r in rows}
    total_recent = sum(r for r, _ in counts.values())
    total_prev = sum(p for _, p in counts.values())
    anchor_date = anchor.date() if hasattr(anchor, "date") else anchor
    if total_prev and total_recent < 0.05 * total_prev:
        print(
            f"WARNING: recent window holds only {total_recent} postings vs {total_prev} "
            f"in the previous one — the source likely went quiet. Consider pinning "
            f"TREND_ANCHOR_DATE to the last healthy date."
        )

    def share_growth(recent: int, previous: int) -> float | None:
        """% change of the category's share of total postings between the two windows."""
        if recent + previous < TREND_MIN_POSTINGS or not total_recent or not total_prev:
            return None
        share_r = recent / total_recent
        share_p = previous / total_prev
        if share_p == 0:
            return 100.0   # appeared from nothing within the window: cap
        return round(min(100.0 * (share_r - share_p) / share_p, 999.0), 1)

    eng = local_engine()
    with eng.begin() as conn:
        cats = conn.execute(
            text("SELECT category_id, job_category FROM job_category")
        ).all()
        out = []
        for cid, label in cats:
            recent, previous = counts.get(label, (0, 0))
            out.append(
                {"cid": cid, "label": label, "recent": recent, "previous": previous,
                 "growth": share_growth(recent, previous), "win": TREND_WINDOW_DAYS,
                 "anchor": anchor_date}
            )
        conn.execute(text("TRUNCATE category_trend"))
        conn.execute(
            text(
                "INSERT INTO category_trend (category_id, job_category, recent_count, "
                "previous_count, growth_pct, window_days, anchor_date) "
                "VALUES (:cid, :label, :recent, :previous, :growth, :win, :anchor)"
            ),
            out,
        )

    with_trend = [o for o in out if o["growth"] is not None]
    growing = sum(1 for o in with_trend if o["growth"] > 0)
    print(
        f"Trend windows: 2x{TREND_WINDOW_DAYS}d ending {anchor_date} on {col} "
        f"({total_recent} vs {total_prev} postings). {len(out)} categories stored; "
        f"{len(with_trend)} have a share trend ({growing} growing, "
        f"{len(with_trend) - growing} flat/declining); "
        f"{len(out) - len(with_trend)} below {TREND_MIN_POSTINGS} postings (NULL)."
    )


if __name__ == "__main__":
    main()
