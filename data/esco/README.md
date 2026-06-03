## Steps

1. Go to **https://esco.ec.europa.eu/en/use-esco/download**
2. Select:
   - **Version:** `v1.2.0`  (must match `ESCO_VERSION` in `.env`)
   - **Language:** `Italian (it)`
   - **Format:** `CSV`
   - Content: the full **classification** bundle
3. Accept the privacy statement, enter your email, and use the emailed link to download
   the `.zip`.
4. Extract it and copy these three files into **this folder** (`data/esco/`):
   - `occupations_it.csv`
   - `skills_it.csv`
   - `occupationSkillRelations.csv`

> The first two carry the Italian labels/descriptions; `occupationSkillRelations.csv` is
> language-independent and holds the `essential` / `optional` occupation↔skill links — the
> heart of the benchmark.

## Then load it

```bash
python scripts/load_esco.py
```

The loader prints the detected column names. If ESCO ever renames a column, that output
tells us immediately and the loader's tolerant column lookup can be adjusted.

## Upgrading ESCO later

Bump `ESCO_VERSION` in `.env`, drop the new CSVs here, re-run the loader. Old reports stay
reproducible because every row stores the version it came from.
