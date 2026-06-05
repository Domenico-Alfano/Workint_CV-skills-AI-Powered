"""Input adapters: turn each flow's source into a common WorkerProfile.

Flow 1 (analyze-cv): we accept the external CV extractor's JSON output and map it. The
mapper is intentionally tolerant (keys vary), so it adapts when the real shape arrives —
adjust the key lists below once the extractor contract is known.

Flow 2 (analyze-worker): reads the external `workers` table. The column mapping is isolated
in `_WORKER_COLS` (env-overridable) and clearly provisional pending the real schema.
"""
import os
import re

import requests
from sqlalchemy import text

from .config import (
    EXTRACTOR_PASSWORD,
    EXTRACTOR_URL,
    EXTRACTOR_VERIFY,
    WORKERS_TABLE,
    external_engine,
)
from .models import WorkerProfile

# ---- Flow 1: extractor output -> WorkerProfile -----------------------------------------

# Keys cover the real Workint extractor output (competenze_tecniche/_soft) plus fallbacks.
_SKILL_KEYS = ("competenze_tecniche", "competenze_soft", "skills", "competenze", "skill",
               "hard_skills", "soft_skills", "abilita")
_ROLE_KEYS = ("role", "ruolo", "professione", "job_title", "current_role", "qualifica")


def _as_skill_list(v) -> list[str]:
    out: list[str] = []
    if isinstance(v, list):
        for it in v:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                out.append(it.get("name") or it.get("label") or it.get("skill")
                           or it.get("descrizione") or it.get("nome") or "")
    elif isinstance(v, str):
        out = re.split(r"[;\n]", v)  # the extractor uses one bullet per line
    cleaned = []
    for s in out:
        if not isinstance(s, str):
            continue
        s = re.sub(r"^\s*(?:[-*•·]|\d+[.)])\s+", "", s)   # strip bullet/number markers
        s = re.sub(r"\*\*|__|`|#", "", s).strip()         # strip markdown emphasis/headings
        if s:
            cleaned.append(s)
    return cleaned


def _first(data: dict, keys) -> object:
    for k in keys:
        if k in data and data[k]:
            return data[k]
    return None


def profile_from_extracted(data: dict) -> WorkerProfile:
    """Map the extractor's JSON output to a WorkerProfile (competenze_tecniche/_soft -> skills)."""
    if isinstance(data.get("data"), dict):   # some extractors nest under "data"
        data = data["data"]
    skills: list[str] = []
    for k in _SKILL_KEYS:
        if k in data:
            skills += _as_skill_list(data[k])
    role = _first(data, _ROLE_KEYS)
    return WorkerProfile(skills=list(dict.fromkeys(skills)), role=str(role) if role else None)


class ExtractorError(Exception):
    pass


def call_extractor(file_bytes: bytes, filename: str = "cv.pdf"):
    """POST a PDF to the external extractor; return its parsed output (a dict of CV fields,
    or a markdown string for older variants).

    Sends the x-access-password header only if EXTRACTOR_PASSWORD is set."""
    headers = {"x-access-password": EXTRACTOR_PASSWORD} if EXTRACTOR_PASSWORD else {}
    try:
        resp = requests.post(
            EXTRACTOR_URL,
            headers=headers,
            files={"file": (filename, file_bytes, "application/pdf")},
            timeout=120,
            verify=EXTRACTOR_VERIFY,
        )
    except requests.RequestException as e:
        raise ExtractorError(f"Extractor call failed: {e}") from e
    if resp.status_code != 200:
        raise ExtractorError(f"Extractor returned {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()          # dict of CV fields
    except ValueError as e:
        raise ExtractorError("Extractor did not return JSON.") from e


# ---- Flow 2: workers table -> WorkerProfile --------------------------------------------
# Mapped to the real `workers` schema in workint-clone (override via env if it changes).
# PII columns (worker_name/surname/email/phone) are intentionally never read.
_WORKER_COLS = {
    "id": os.getenv("WORKERS_COL_ID", "worker_id"),
    "skills": os.getenv("WORKERS_COL_SKILLS", "worker_personal_skills"),
    "role": os.getenv("WORKERS_COL_ROLE", "worker_preferred_jobs"),
    "target_job": os.getenv("WORKERS_COL_TARGET_JOB", "worker_preferred_jobs"),
}


class WorkerNotFound(Exception):
    pass


class WorkersSchemaUnknown(Exception):
    """Raised until the `workers` schema/column mapping is confirmed."""


def load_worker(worker_id: int) -> tuple[WorkerProfile, str | None]:
    """Read a stored worker's pre-extracted profile + target job from the external DB.

    Returns (profile, target_job_text). Raises WorkersSchemaUnknown if the configured
    columns aren't present (i.e. mapping not yet adapted to the real schema).
    """
    eng = external_engine()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
        ), {"t": WORKERS_TABLE})}
        if not cols:
            raise WorkersSchemaUnknown(f"Table '{WORKERS_TABLE}' not found in external DB.")
        missing = [v for v in (_WORKER_COLS["id"], _WORKER_COLS["skills"]) if v not in cols]
        if missing:
            raise WorkersSchemaUnknown(
                f"`workers` columns {missing} not found (have {sorted(cols)}). "
                "Set WORKERS_COL_* env vars to map the real schema."
            )
        sel = [_WORKER_COLS["id"], _WORKER_COLS["skills"]]
        sel += [_WORKER_COLS[k] for k in ("role", "target_job") if _WORKER_COLS[k] in cols]
        row = c.execute(
            text(f"SELECT {', '.join(sel)} FROM {WORKERS_TABLE} WHERE {_WORKER_COLS['id']} = :id"),
            {"id": worker_id},
        ).mappings().first()
    if not row:
        raise WorkerNotFound(f"No worker {worker_id} in '{WORKERS_TABLE}'.")

    profile = WorkerProfile(
        skills=_as_skill_list(row.get(_WORKER_COLS["skills"])),
        role=(str(row[_WORKER_COLS["role"]]) if row.get(_WORKER_COLS["role"]) else None),
    )
    target = row.get(_WORKER_COLS["target_job"])
    return profile, (str(target) if target else (profile.role or None))
