"""Load the CP2021 classification into cp2021_profession + cp2021_label.

- cp2021_profession: the 813 unità professionali from CP2021.xlsx `quinto_digit`
  (cod_5 / nome_5 / descr_5). cod_5 doubles as the INAPP API `codice`.
- cp2021_label: match labels = each nome_5 + the 6th-digit "voci professionali" (specific
  job titles) from cp2021_classificazione.xlsx, used like ESCO altLabels for classification.
"""
import sys

import pandas as pd
from sqlalchemy import text

from db import ROOT, local_engine

CP_DIR = ROOT / "data" / "cp2021"
XLSX = CP_DIR / "CP2021.xlsx"
CLASSIF_XLSX = CP_DIR / "cp2021_classificazione.xlsx"
VOCI_SHEET = "sesto_digit-Voce prof.le"


def _load_voci() -> pd.DataFrame:
    """Return DataFrame[cod_5, label] from the 6th-digit voci professionali, if available."""
    if not CLASSIF_XLSX.exists():
        print(f"(note) {CLASSIF_XLSX.name} not found — loading nome_5 labels only.")
        return pd.DataFrame(columns=["cod_5", "label"])
    raw = pd.read_excel(CLASSIF_XLSX, sheet_name=VOCI_SHEET, header=1)
    raw = raw.iloc[:, :2]
    raw.columns = ["code6", "label"]
    raw = raw.dropna(subset=["code6", "label"])
    raw["code6"] = raw["code6"].astype(str).str.strip()
    # cod_5 = first 5 dotted segments of the 6-level voce code.
    raw["cod_5"] = raw["code6"].str.split(".").str[:5].str.join(".")
    return raw[["cod_5", "label"]]


def main() -> None:
    if not XLSX.exists():
        sys.exit(f"Missing {XLSX} — see README.md (Data acquisition)")
    df = pd.read_excel(XLSX, sheet_name="quinto_digit")[["cod_5", "nome_5", "descr_5"]]
    df = df.dropna(subset=["cod_5", "nome_5"])
    df["cod_5"] = df["cod_5"].astype(str).str.strip()
    valid = set(df["cod_5"])

    voci = _load_voci()
    voci = voci[voci["cod_5"].isin(valid)]

    labels = (
        [{"cod_5": r.cod_5, "label": r.nome_5, "source": "nome_5"} for r in df.itertuples(index=False)]
        + [{"cod_5": r.cod_5, "label": str(r.label).strip(), "source": "voce"}
           for r in voci.itertuples(index=False)]
    )

    eng = local_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE cp2021_profession CASCADE"))
        conn.execute(
            text("INSERT INTO cp2021_profession (cod_5, nome_5, descr_5) "
                 "VALUES (:cod_5, :nome_5, :descr_5)"),
            df.to_dict("records"),
        )
        conn.execute(
            text("INSERT INTO cp2021_label (cod_5, label, source) VALUES (:cod_5, :label, :source)"),
            labels,
        )
    print(f"Loaded {len(df)} CP2021 professions and {len(labels)} match labels "
          f"({len(voci)} voci professionali).")


if __name__ == "__main__":
    main()
