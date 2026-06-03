"""Classify each in_benchmark job_category -> CP2021 profession (cod_5) via hybrid match.

Parallel to classify_categories.py (ESCO), but targets the CP2021 professions. Same hybrid
score = ALPHA*semantic(mpnet) + (1-ALPHA)*lexical(rapidfuzz), matched against the Italian
nome_5 labels. Writes job_cp2021_map with top-5 candidates + a needs_review flag, reusable
by the same export_review / import_review flow (extended for CP2021 later if needed).
"""
import json
import os

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from db import local_engine

MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
ALPHA = float(os.getenv("HYBRID_ALPHA", "0.5"))
TOP_K = 5
MIN_SCORE = 0.70


def main() -> None:
    eng = local_engine()
    # All labels (nome_5 + voci professionali), with the profession's nome_5 for display.
    lab = pd.read_sql(
        text("SELECT l.cod_5, l.label, p.nome_5 FROM cp2021_label l "
             "JOIN cp2021_profession p ON p.cod_5 = l.cod_5 ORDER BY l.cod_5"),
        eng,
    )
    cats = pd.read_sql(
        text("SELECT category_id, job_category FROM job_category WHERE in_benchmark "
             "ORDER BY posting_count DESC"),
        eng,
    )
    print(f"Classifying {len(cats)} categories against {lab['cod_5'].nunique()} CP2021 "
          f"professions ({len(lab)} labels incl. voci)\nmodel: {MODEL}")

    cat_list = cats["job_category"].tolist()
    labels = lab["label"].tolist()
    lab_cod = lab["cod_5"].to_numpy()
    lab_nome = lab["nome_5"].to_numpy()

    model = SentenceTransformer(MODEL)
    lab_emb = model.encode(labels, normalize_embeddings=True, batch_size=128, show_progress_bar=True)
    cat_emb = model.encode(cat_list, normalize_embeddings=True, batch_size=64, show_progress_bar=True)
    sem = cat_emb @ lab_emb.T
    lex = process.cdist(cat_list, labels, scorer=fuzz.WRatio, workers=-1, dtype=np.float32) / 100.0
    combined = ALPHA * sem + (1.0 - ALPHA) * lex

    rows = []
    for i, (cid, cname) in enumerate(zip(cats["category_id"], cats["job_category"])):
        # Best label per distinct profession -> top-K professions.
        order = np.argsort(-combined[i])
        cands, seen = [], set()
        for j in order:
            code = str(lab_cod[j])
            if code in seen:
                continue
            seen.add(code)
            cands.append({
                "cod_5": code, "label": str(lab_nome[j]), "matched_label": str(labels[j]),
                "score": round(float(combined[i][j]), 4),
                "sem": round(float(sem[i][j]), 4), "lex": round(float(lex[i][j]), 4),
            })
            if len(cands) == TOP_K:
                break
        rows.append({
            "category_id": int(cid),
            "job_category": cname,
            "cod_5": cands[0]["cod_5"],
            "classification_method": "embedding",
            "confidence": cands[0]["score"],
            "candidates_considered": json.dumps(cands, ensure_ascii=False),
            "needs_review": bool(cands[0]["score"] < MIN_SCORE),
        })

    with eng.begin() as conn:
        conn.execute(text("TRUNCATE job_cp2021_map CASCADE"))
        conn.execute(
            text("INSERT INTO job_cp2021_map "
                 "(category_id, job_category, cod_5, classification_method, confidence, "
                 " candidates_considered, needs_review) VALUES "
                 "(:category_id, :job_category, :cod_5, :classification_method, :confidence, "
                 " CAST(:candidates_considered AS jsonb), :needs_review)"),
            rows,
        )
    n_rev = sum(r["needs_review"] for r in rows)
    print(f"Classified {len(rows)} categories; {n_rev} flagged needs_review (top < {MIN_SCORE}).")


if __name__ == "__main__":
    main()
