"""Stage C2: postings demand overlay for the ESCO benchmark.

For each benchmarked job_category we sample up to N real postings (within the date window),
embed each posting's text, find the nearest ESCO skills (cosine >= MIN_SIM, top-K per
posting), and aggregate into a per-category frequency. The result is written to
job_benchmark.demand_skills as [{uri, label, count, freq}] (freq = share of sampled
postings hitting that skill). Both layers thus live in ESCO-skill space.

Reuses the mpnet model; ESCO skill embeddings are cached to data/cache/.
Config via env: OVERLAY_SAMPLE_N, OVERLAY_MIN_SIM, OVERLAY_TOPK_PER_POSTING,
OVERLAY_MAX_DEMAND, OVERLAY_ONLY_CATEGORIES (comma list, for testing).
"""
import hashlib
import json
import os
from collections import Counter

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from db import (
    DATE_COLUMN, DATE_FROM, DATE_TO, ESCO_VERSION, POSTINGS_TABLE, ROOT,
    external_engine, local_engine, safe_identifier,
)

MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
SAMPLE_N = int(os.getenv("OVERLAY_SAMPLE_N", "100"))
MIN_SIM = float(os.getenv("OVERLAY_MIN_SIM", "0.45"))
TOPK = int(os.getenv("OVERLAY_TOPK_PER_POSTING", "15"))
MAX_DEMAND = int(os.getenv("OVERLAY_MAX_DEMAND", "25"))
ONLY = os.getenv("OVERLAY_ONLY_CATEGORIES")


def _posting_text(r) -> str:
    parts = [r.job_title or "", r.job_highlights or "", r.job_description or ""]
    return " ".join(p for p in parts if p)[:2000]


def _skill_embeddings(model, skills: pd.DataFrame) -> np.ndarray:
    cache_dir = ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{MODEL}|{ESCO_VERSION}|{len(skills)}".encode()).hexdigest()[:12]
    cache = cache_dir / f"skill_emb_{key}.npy"
    if cache.exists():
        return np.load(cache)
    emb = model.encode(
        skills["preferred_label_it"].tolist(), normalize_embeddings=True,
        batch_size=128, show_progress_bar=True,
    )
    np.save(cache, emb)
    return emb


def main() -> None:
    leng = local_engine()
    ext = external_engine()

    skills = pd.read_sql(
        text("SELECT skill_uri, preferred_label_it FROM esco_skill ORDER BY skill_uri"), leng
    )
    cats = pd.read_sql(
        text("SELECT category_id, job_category FROM job_category WHERE in_benchmark "
             "ORDER BY posting_count DESC"),
        leng,
    )
    if ONLY:
        wanted = {s.strip() for s in ONLY.split(",")}
        cats = cats[cats["job_category"].isin(wanted)]

    print(f"model: {MODEL}\noverlay: N={SAMPLE_N}, min_sim={MIN_SIM}, topk/posting={TOPK}, "
          f"categories={len(cats)}")
    model = SentenceTransformer(MODEL)
    skill_emb = _skill_embeddings(model, skills)
    skill_uri = skills["skill_uri"].to_numpy()
    skill_lbl = skills["preferred_label_it"].to_numpy()

    tbl, col = safe_identifier(POSTINGS_TABLE), safe_identifier(DATE_COLUMN)
    where = f"{col} >= :dfrom" + (f" AND {col} <= :dto" if DATE_TO else "")
    sample_q = text(
        f"SELECT job_title, job_description, job_highlights FROM {tbl} "
        f"WHERE job_category = :cat AND {where} ORDER BY job_id LIMIT :n"
    )

    updates = []
    for row in cats.itertuples(index=False):
        params = {"cat": row.job_category, "dfrom": DATE_FROM, "n": SAMPLE_N}
        if DATE_TO:
            params["dto"] = DATE_TO
        posts = pd.read_sql(sample_q, ext, params=params)
        if posts.empty:
            updates.append((row.category_id, "[]", 0))
            continue
        texts = [_posting_text(r) for r in posts.itertuples(index=False)]
        pemb = model.encode(texts, normalize_embeddings=True, batch_size=64)
        sims = pemb @ skill_emb.T
        cnt: Counter = Counter()
        for i in range(len(texts)):
            for j in np.argsort(-sims[i])[:TOPK]:
                if sims[i][j] >= MIN_SIM:
                    cnt[int(j)] += 1
        n = len(texts)
        demand = [
            {"uri": str(skill_uri[j]), "label": str(skill_lbl[j]), "count": c,
             "freq": round(c / n, 3)}
            for j, c in cnt.most_common(MAX_DEMAND)
        ]
        updates.append((row.category_id, json.dumps(demand, ensure_ascii=False), len(demand)))
        print(f"  {row.job_category[:32]:32} n={n:>3} demand={len(demand)}")

    with leng.begin() as conn:
        for cid, demand_json, nd in updates:
            conn.execute(
                text("UPDATE job_benchmark SET demand_skills = CAST(:d AS jsonb), n_demand = :nd "
                     "WHERE category_id = :cid"),
                {"d": demand_json, "nd": nd, "cid": cid},
            )
    print(f"Updated demand overlay for {len(updates)} categories.")


if __name__ == "__main__":
    main()
