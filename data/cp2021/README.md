# CP2021 (ISTAT) + INAPP competences — download guide

Goal: build the **second benchmark** (alongside ESCO) for each job title, based on the
Italian national system. Files are **gitignored**; download locally into `data/cp2021/`.

> **Read this first — the key caveat.** Unlike ESCO, CP2021 comes in **two separate parts**:
> 1. **CP2021 classification** (ISTAT) = profession **codes + labels + descriptions**. Easy
>    to download (direct Excel). **Contains NO skills.**
> 2. **Competences/knowledge/activities per profession** = the actual "skills", produced by
>    **INAPP** (Indagine Campionaria sulle Professioni / Sistema Informativo sulle
>    Professioni), keyed to CP2021. This is the part that makes a real benchmark.
>
> **Coverage warning:** the CP2021-updated INAPP survey is being released in *waves* — the
> first wave (2023) covered ~**250 of 813** professional units. So native CP2021 competence
> data may be **incomplete**. The complete legacy data is keyed to **CP2011**; if needed we
> bridge it with the CP2011→CP2021 crosswalk (file #3 below).
>
> **Design implication:** the CP2021 benchmark is only meaningfully *different* from the
> ESCO one if we use INAPP's **native** competences (file #2). If we instead just crosswalk
> CP→ESCO for skills, the two benchmarks collapse into one. So file #2 is the important one.

---

## Files to download into `data/cp2021/`

### 1. CP2021 classification structure (codes + labels) — REQUIRED, easy
The official nomenclature of the 9 → 40 → 130 → 510 → **813 unità professionali**.
- ISTAT landing page: https://www.istat.it/it/archivio/18132
  (EN: https://www.istat.it/en/classification/classification-of-occupations/)
- Interactive navigator (with *declaratorie* descriptions):
  https://professioni.istat.it/sistemainformativoprofessioni/cp/
- Direct Excel of the full nomenclature (official content, republished by INAIL):
  `https://www.inail.it/content/dam/inail-hub-site/documenti/modulistica-assicurazione/09/20241001-Classificazione%20e%20nomenclatura%20Professioni-ISTAT-CP2021.xlsx`
  → save as **`cp2021_classificazione.xlsx`**
- **Columns we need:** the 5-digit Unità Professionale **code** + **denominazione (label)**;
  ideally also the level-4 category and the *declaratoria* (description) text.

### 2. INAPP competences per profession — SOLVED VIA API (no bulk download needed)
The competence data (conoscenze / skill / attività, O*NET-style with importance scores) is
served by the **INAPP API**: `https://api.inapp.org/professioni/survey.php` — public, JSON,
no auth, CORS-open. Per profession code we call:
```
GET https://api.inapp.org/professioni/survey.php?codice=<CP_code>&idDataset=<N>
```
where `<CP_code>` is the dotted 5-digit code (e.g. `2.1.1.1.1`, matches CP2021.xlsx cod_5).
Datasets (idDataset): 1=Compiti(tasks), 2=Conoscenze(knowledge, +complessità),
4 & 5=Skill (+complessità), 6=Attività di lavoro, 8=Stili/attitudini, 22=RIASEC type;
15–21 are aggregated/macro versions. Response: `{ "<dimCode>": {"importanza","complessita",
"label":[{"descDimensione","longDescDimensione"}]}, ... }`.
- We pull only the codes our categories map to (≤ a few hundred) → store top skills by
  `importanza` into `cp2021_profession_skill`.
- The data appears O*NET-derived (legacy ICP survey); confirm CP2021 coverage per code as we
  go (some codes may be sparse — bridge via file #3 if needed).
- Search endpoint also available: `https://api.inapp.org/professioni/search.php` (by name,
  task, skill, code; various `flag` values).

### 3. CP2011 → CP2021 crosswalk (raccordo) — recommended (bridge for #2)
- Direct Excel: `https://www.istat.it/wp-content/uploads/2011/03/raccordoCp2011_III-Cp2021_V.xlsx`
  → save as **`cp2011_cp2021_raccordo.xlsx`**
- **Columns we need:** CP2011 code ↔ CP2021 code (6-digit).

### 4. (Optional) CP2021 ↔ ESCO/ISCO crosswalk — for cross-referencing the two benchmarks
The new INAPP LMI integrates ESCO; a CP↔ESCO (or via ISCO-08) mapping should be available
on the INAPP/ISTAT portals. Lets the report link "CP2021 profession X ≈ ESCO occupation Y".
ESCO occupations already carry their ISCO group in our `esco_occupation.isco_code`, and
CP2021 is ISCO-08-aligned, so **ISCO-08 is a fallback bridge** if no direct file exists.

---

## Notes
- Most ISTAT/INAPP downloads are **direct files or portal navigation** (no email gate like
  ESCO). The INAPP portal blocks automated fetching, so grab files via a browser.
- After download, tell me the exact filenames + sheet/column names and I'll write the loader
  (`scripts/load_cp2021.py`) to populate `cp2021_profession`, `cp2021_skill`,
  `cp2021_profession_skill`, mirroring the ESCO tables.
