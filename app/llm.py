"""LLM narrative report generator — provider-agnostic (Groq now, OpenAI later).

Switch provider by changing LLM_PROVIDER / LLM_API_KEY / LLM_MODEL in .env.
Returns None if LLM_API_KEY is not set.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import GapResult, Report

_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": None,
}


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI
    from .config import LLM_API_KEY, LLM_PROVIDER
    return OpenAI(api_key=LLM_API_KEY, base_url=_BASE_URLS.get(LLM_PROVIDER))


def _fmt(skills: list, n: int = 8) -> str:
    return ", ".join(f'"{s}"' for s in skills[:n]) + ("…" if len(skills) > n else "")


def generate_report(result: "GapResult") -> "Report | None":
    from .config import LLM_ENABLED, LLM_MODEL
    from .models import Report
    if not LLM_ENABLED:
        return None

    esco = result.esco
    missing = esco.missing[:12]
    covered = [c.skill for c in esco.covered[:8]]

    prompt = f"""Sei un consulente del lavoro italiano. Analizza il gap di competenze e rispondi SOLO con un oggetto JSON valido (nessun testo fuori dal JSON).

Dati:
- Ruolo target: {result.job_category} (ESCO: {esco.occupation_label})
- Competenze presenti: {_fmt(covered)}
- Competenze mancanti: {_fmt(missing)}
- Copertura benchmark: {esco.coverage_pct}% ({esco.n_covered}/{esco.n_total})

Formato richiesto (JSON, in italiano, tono professionale):
{{
  "strengths": "<un paragrafo sui punti di forza del candidato>",
  "gaps": "<un paragrafo sulle lacune principali da colmare>",
  "formation": [
    "<suggerimento formativo concreto 1>",
    "<suggerimento formativo concreto 2>",
    "<suggerimento formativo concreto 3>"
  ]
}}"""

    resp = _client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    # Strip markdown fences if the model wraps the JSON anyway.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)
    return Report(
        strengths=data.get("strengths", ""),
        gaps=data.get("gaps", ""),
        formation=data.get("formation", []),
    )
