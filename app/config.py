"""API config + shared engine and embedding model (loaded once)."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)
# A worker skill "covers" a benchmark skill when cosine similarity >= this.
COVER_THRESHOLD = float(os.getenv("GAP_COVER_THRESHOLD", "0.62"))

# CORS origins for the Angular frontend (comma-separated; "*" allows all for dev).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Flow 2: stored CVs live in the external `workers` table (schema TBD — see app/sources.py).
WORKERS_TABLE = os.getenv("WORKERS_TABLE", "workers")

# Flow 1: external CV extractor (PDF -> markdown). Protected by an access password.
EXTRACTOR_URL = os.getenv(
    "EXTRACTOR_URL", "https://ai-services.workint.expleoitalia.it/extract-cv-info"
)
EXTRACTOR_PASSWORD = os.getenv("EXTRACTOR_PASSWORD")  # set in .env (header x-access-password)
# The extractor host uses a self-signed cert; set EXTRACTOR_VERIFY_SSL=false to skip
# verification (internal trusted service) or point EXTRACTOR_CA_BUNDLE at its CA cert.
_verify = os.getenv("EXTRACTOR_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
EXTRACTOR_VERIFY = os.getenv("EXTRACTOR_CA_BUNDLE") or _verify


@lru_cache(maxsize=1)
def engine() -> Engine:
    """Local DB (benchmark)."""
    return create_engine(os.environ["LOCAL_DB_URL"], future=True)


@lru_cache(maxsize=1)
def external_engine() -> Engine:
    """External read-only DB (workint-clone) holding the `workers` table for Flow 2."""
    return create_engine(os.environ["EXTERNAL_JOBS_DB_URL"], future=True)


@lru_cache(maxsize=1)
def model():
    # Imported lazily so importing config (e.g. in tests) doesn't load torch.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)
