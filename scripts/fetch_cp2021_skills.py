"""Fetch CP2021 competence data from the INAPP API into cp2021_profession_skill.

For each distinct CP2021 code mapped in job_cp2021_map, call
  https://api.inapp.org/professioni/survey.php?codice=<cod_5>&idDataset=<N>
for the requested datasets and store each dimension (label + importanza + complessita).

Datasets (idDataset): 1=Compiti, 2=Conoscenze, 4 & 5=Skill, 6=Attività, 8=Stili.
Config: CP_DATASETS (csv, default "1,2,4,5,6"), CP_FETCH_LIMIT (test on N codes).
Coverage is partial for some codes (INAPP survey waves) — empty responses are skipped.
"""
import json
import os
import time
import urllib.parse
import urllib.request

from sqlalchemy import text

from db import local_engine

API = "https://api.inapp.org/professioni/survey.php"
SECTIONS = {1: "compiti", 2: "conoscenze", 4: "skill", 5: "skill", 6: "attività", 8: "stili"}
DATASETS = [int(x) for x in os.getenv("CP_DATASETS", "1,2,4,5,6").split(",")]
LIMIT = int(os.getenv("CP_FETCH_LIMIT", "0"))  # 0 = all mapped codes


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get(codice: str, ds: int):
    url = f"{API}?codice={urllib.parse.quote(codice)}&idDataset={ds}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace").strip()
    if not raw or raw in ("[]", "{}", "null"):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _iter_dims(data):
    """Yield (dim_code, label, importanza, complessita) across the API's two shapes."""
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), {})
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        if "desc_compito" in v:  # tasks (idDataset 1)
            label, comp = v.get("desc_compito"), None
        else:
            lab = v.get("label")
            label = lab[0].get("descDimensione") if isinstance(lab, list) and lab else None
            comp = v.get("complessita")
        if label and str(label).strip():
            yield str(k), str(label).strip(), _f(v.get("importanza")), _f(comp)


def main() -> None:
    eng = local_engine()
    codes = [r[0] for r in eng.connect().execute(
        text("SELECT DISTINCT cod_5 FROM job_cp2021_map WHERE cod_5 IS NOT NULL ORDER BY cod_5")
    )]
    if LIMIT:
        codes = codes[:LIMIT]
    print(f"Fetching datasets {DATASETS} for {len(codes)} CP2021 codes from INAPP API...")

    rows, empty_codes = [], 0
    for n, code in enumerate(codes, 1):
        got_any = False
        for ds in DATASETS:
            try:
                data = _get(code, ds)
            except Exception as e:
                print(f"  ! {code} ds{ds}: {str(e)[:60]}")
                continue
            if not data:
                continue
            for dim_code, label, imp, comp in _iter_dims(data):
                rows.append({
                    "cod_5": code, "dataset_id": ds, "section": SECTIONS.get(ds, str(ds)),
                    "dim_code": dim_code, "label": label, "importanza": imp, "complessita": comp,
                })
                got_any = True
            time.sleep(0.05)
        if not got_any:
            empty_codes += 1
        if n % 25 == 0:
            print(f"  {n}/{len(codes)} codes, {len(rows)} dims so far")

    with eng.begin() as conn:
        conn.execute(text("TRUNCATE cp2021_profession_skill"))
        if rows:
            conn.execute(
                text("INSERT INTO cp2021_profession_skill "
                     "(cod_5, dataset_id, section, dim_code, label, importanza, complessita) VALUES "
                     "(:cod_5, :dataset_id, :section, :dim_code, :label, :importanza, :complessita) "
                     "ON CONFLICT (cod_5, dataset_id, dim_code) DO NOTHING"),
                rows,
            )
    print(f"Stored {len(rows)} competence rows for {len(codes)-empty_codes}/{len(codes)} codes "
          f"({empty_codes} had no data).")


if __name__ == "__main__":
    main()
