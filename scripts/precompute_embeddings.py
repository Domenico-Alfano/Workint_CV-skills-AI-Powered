"""Offline: precompute embeddings for every DISTINCT benchmark label and cache them to
data/cache/label_emb_<model>.npz.

The API (app/gap._load_emb_store) loads this at startup, so requests are fast from the very
first one — even after an uvicorn restart — with no ~3s per-category re-encode. CP2021's 126
transversal labels are shared across categories, so deduping here stores ~6k vectors (~19 MB)
instead of the ~27k a naive per-category cache would hold.

Re-run after rebuilding the benchmark OR changing EMBEDDING_MODEL (the filename is model-keyed,
so a stale file is simply ignored rather than mis-loaded).

Run:  ./.venv/Scripts/python.exe scripts/precompute_embeddings.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sqlalchemy import text

from app.config import EMBEDDING_MODEL, engine, model
from app.gap import _CACHE_DIR, _EMB_FILE, _labels


def main() -> None:
    with engine().connect() as c:
        rows = c.execute(text(
            "SELECT essential_skills, optional_skills, cp2021_skills FROM job_benchmark"
        )).mappings().all()

    labels: set[str] = set()
    for r in rows:
        labels.update(_labels(r["essential_skills"]))
        labels.update(_labels(r["optional_skills"]))
        labels.update(_labels(r["cp2021_skills"]))
    labels = sorted(labels)
    print(f"encoding {len(labels)} distinct benchmark labels with {EMBEDDING_MODEL}")

    emb = np.asarray(
        model().encode(labels, normalize_embeddings=True, batch_size=128, show_progress_bar=True),
        dtype=np.float32,
    )
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(_EMB_FILE, labels=np.array(labels), embeddings=emb)
    print(f"saved {len(labels)} embeddings -> {_EMB_FILE.name}  ({emb.nbytes / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
