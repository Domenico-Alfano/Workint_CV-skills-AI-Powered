"""Shared DB helpers: env loading + SQLAlchemy engines for local and external Postgres."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ESCO_VERSION = os.getenv("ESCO_VERSION", "v1.2.0")
ESCO_DATA_DIR = ROOT / os.getenv("ESCO_DATA_DIR", "data/esco")

# --- Postings source (offerte_lavoro) + snapshot window ---
POSTINGS_TABLE = os.getenv("POSTINGS_TABLE", "offerte_lavoro")
DATE_COLUMN = os.getenv("DATE_COLUMN", "mapping_timestamp")
DATE_FROM = os.getenv("DATE_FROM", "2026-04-01")
DATE_TO = os.getenv("DATE_TO") or None   # None = up to the newest available
MIN_POSTINGS = int(os.getenv("MIN_POSTINGS", "10"))


def safe_identifier(name: str) -> str:
    """Guard table/column names interpolated into SQL (they come from .env, not users)."""
    import re

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def local_engine() -> Engine:
    """Engine for the local (docker-compose) Postgres."""
    return create_engine(os.environ["LOCAL_DB_URL"], future=True)


def external_engine() -> Engine:
    """Engine for the external read-only jobs DB."""
    return create_engine(os.environ["EXTERNAL_JOBS_DB_URL"], future=True)
