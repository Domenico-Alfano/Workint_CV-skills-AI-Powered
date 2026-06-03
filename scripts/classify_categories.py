"""Stage B: classify each in_benchmark job_category -> ESCO occupation via embeddings.

This is the only non-deterministic step, so it's fully audited: we store the top-K
candidates with scores in job_occupation_map.candidates_considered and flag low-confidence
rows for human review. The LLM tiebreak (optional refinement) can run later over the
flagged rows; this pass is local-only (no external API).

Matching is a HYBRID of two signals against EVERY ESCO label (Italian preferred label +
all altLabels), then the best-matching label per occupation:
  - semantic: cosine similarity from a multilingual sentence-transformer
  - lexical:  rapidfuzz WRatio (catches shared stems like "Magazziniere"<->"magazzino"
              that the embedding model mis-ranks)
combined = ALPHA*semantic + (1-ALPHA)*lexical. ESCO leaf occupations are hyper-specific
(e.g. "commesso di libreria"); the generic terms a category uses live in altLabels, so
indexing all labels is essential for recall.
"""
import json
import os

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from db import ESCO_VERSION, local_engine

MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
ALPHA = float(os.getenv("HYBRID_ALPHA", "0.5"))  # weight on semantic vs lexical
TOP_K = 5
MIN_SCORE = 0.70    # below this combined top-1 score -> flag for review (heuristic)


def main() -> None:
    eng = local_engine()
    occ = pd.read_sql(
        text("SELECT occupation_uri, preferred_label_it, alt_labels_it FROM esco_occupation"), eng
    )
    cats = pd.read_sql(
        text(
            "SELECT category_id, job_category FROM job_category "
            "WHERE in_benchmark ORDER BY posting_count DESC"
        ),
        eng,
    )

    # Flatten to one row per (label, occupation): preferred label + all altLabels.
    label_texts: list[str] = []
    label_uri: list[str] = []
    label_pref: list[str] = []
    for uri, pref, alts in zip(occ.occupation_uri, occ.preferred_label_it, occ.alt_labels_it):
        forms = [pref]
        if isinstance(alts, str) and alts.strip():
            forms += [a.strip() for a in alts.split("\n") if a.strip()]
        for f in forms:
            label_texts.append(f)
            label_uri.append(uri)
            label_pref.append(pref)
    label_uri_arr = np.array(label_uri)
    print(
        f"Classifying {len(cats)} categories against {len(occ)} ESCO occupations "
        f"({len(label_texts)} labels incl. altLabels)\nmodel: {MODEL}"
    )

    cat_list = cats["job_category"].tolist()
    model = SentenceTransformer(MODEL)
    lab_emb = model.encode(
        label_texts, normalize_embeddings=True, batch_size=128, show_progress_bar=True
    )
    cat_emb = model.encode(
        cat_list, normalize_embeddings=True, batch_size=64, show_progress_bar=True
    )
    sem = cat_emb @ lab_emb.T  # (n_cat, n_labels) cosine in [-1,1]

    # Lexical similarity matrix (0..1), same shape, computed with rapidfuzz.
    print("computing lexical (rapidfuzz) scores...")
    lex = process.cdist(
        cat_list, label_texts, scorer=fuzz.WRatio, workers=-1, dtype=np.float32
    ) / 100.0

    combined = ALPHA * sem + (1.0 - ALPHA) * lex

    rows = []
    for i, (cid, cname) in enumerate(zip(cats["category_id"], cats["job_category"])):
        # Walk labels best-first, keep the best label per distinct occupation -> top-K occupations.
        order = np.argsort(-combined[i])
        cands = []
        seen: set[str] = set()
        for j in order:
            uri = str(label_uri_arr[j])
            if uri in seen:
                continue
            seen.add(uri)
            cands.append({
                "uri": uri,
                "label": str(label_pref[j]),
                "matched_label": str(label_texts[j]),
                "score": round(float(combined[i][j]), 4),
                "sem": round(float(sem[i][j]), 4),
                "lex": round(float(lex[i][j]), 4),
            })
            if len(cands) == TOP_K:
                break
        top1 = cands[0]
        needs = top1["score"] < MIN_SCORE
        rows.append({
            "category_id": int(cid),
            "job_category": cname,
            "occupation_uri": top1["uri"],
            "classification_method": "embedding",
            "confidence": top1["score"],
            "candidates_considered": json.dumps(cands, ensure_ascii=False),
            "esco_version": ESCO_VERSION,
            "needs_review": bool(needs),
        })

    with eng.begin() as conn:
        conn.execute(text("TRUNCATE job_occupation_map CASCADE"))
        conn.execute(
            text(
                "INSERT INTO job_occupation_map "
                "(category_id, job_category, occupation_uri, classification_method, confidence, "
                " candidates_considered, esco_version, needs_review) VALUES "
                "(:category_id, :job_category, :occupation_uri, :classification_method, :confidence, "
                " CAST(:candidates_considered AS jsonb), :esco_version, :needs_review)"
            ),
            rows,
        )

    n_rev = sum(r["needs_review"] for r in rows)
    print(f"Classified {len(rows)} categories; {n_rev} flagged needs_review (top score < {MIN_SCORE}).")


if __name__ == "__main__":
    main()
