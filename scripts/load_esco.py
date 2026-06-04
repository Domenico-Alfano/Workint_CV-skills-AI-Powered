"""Load a pinned ESCO CSV bundle (Italian) into the esco_* tables.

Expects these files in ESCO_DATA_DIR (see README.md "Data acquisition" for download steps):
    occupations_it.csv
    skills_it.csv
    occupationSkillRelations.csv

Idempotent: truncates and reloads. Every row is tagged with ESCO_VERSION so the
benchmark stays reproducible across ESCO releases.
"""
import sys

import pandas as pd
from sqlalchemy import text

from db import ESCO_DATA_DIR, ESCO_VERSION, local_engine


def _require(*candidates: str):
    """Return the first existing file among candidate names (ESCO bundles vary the suffix)."""
    for fname in candidates:
        p = ESCO_DATA_DIR / fname
        if p.exists():
            return p
    sys.exit(
        f"Missing ESCO file (looked for {', '.join(candidates)}) in {ESCO_DATA_DIR}\n"
        "See README.md (Data acquisition) for download steps."
    )


def _col(df: pd.DataFrame, *names: str) -> pd.Series:
    """Return the first present column among `names`, else an all-None series."""
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series([None] * len(df))


def main() -> None:
    occ = pd.read_csv(_require("occupations_it.csv"))
    skills = pd.read_csv(_require("skills_it.csv"))
    rels = pd.read_csv(_require("occupationSkillRelations.csv", "occupationSkillRelations_it.csv"))

    print(f"occupations: {len(occ):>6} rows | columns: {list(occ.columns)}")
    print(f"skills:      {len(skills):>6} rows | columns: {list(skills.columns)}")
    print(f"relations:   {len(rels):>6} rows | columns: {list(rels.columns)}")

    occ_out = pd.DataFrame({
        "occupation_uri": _col(occ, "conceptUri"),
        "isco_code": _col(occ, "iscoGroup", "code"),
        "preferred_label_it": _col(occ, "preferredLabel"),
        "alt_labels_it": _col(occ, "altLabels"),
        "description_it": _col(occ, "description", "definition"),
        "esco_version": ESCO_VERSION,
    }).dropna(subset=["occupation_uri", "preferred_label_it"])

    skill_out = pd.DataFrame({
        "skill_uri": _col(skills, "conceptUri"),
        "preferred_label_it": _col(skills, "preferredLabel"),
        "alt_labels_it": _col(skills, "altLabels"),
        "skill_type": _col(skills, "skillType"),
        "reuse_level": _col(skills, "reuseLevel"),
        "description_it": _col(skills, "description", "definition"),
        "esco_version": ESCO_VERSION,
    }).dropna(subset=["skill_uri", "preferred_label_it"])

    rel_out = pd.DataFrame({
        "occupation_uri": _col(rels, "occupationUri"),
        "skill_uri": _col(rels, "skillUri"),
        "relation_type": _col(rels, "relationType"),
    }).dropna()

    # Defensive: keep only relations whose endpoints actually loaded.
    valid_occ = set(occ_out["occupation_uri"])
    valid_skill = set(skill_out["skill_uri"])
    rel_out = rel_out[
        rel_out["occupation_uri"].isin(valid_occ) & rel_out["skill_uri"].isin(valid_skill)
    ].drop_duplicates(subset=["occupation_uri", "skill_uri", "relation_type"])

    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE esco_occupation_skill, esco_skill, esco_occupation CASCADE"))
    occ_out.to_sql("esco_occupation", eng, if_exists="append", index=False)
    skill_out.to_sql("esco_skill", eng, if_exists="append", index=False)
    rel_out.to_sql("esco_occupation_skill", eng, if_exists="append", index=False)

    print(
        f"Loaded {len(occ_out)} occupations, {len(skill_out)} skills, "
        f"{len(rel_out)} relations (ESCO {ESCO_VERSION})."
    )


if __name__ == "__main__":
    main()
