## Selenium scrapers in this repository

### 1) csm_ab scraper

Script: `scrape_csm_ab.py`

Uploads `.pdb` files to:
`https://biosig.lab.uq.edu.au/csm_ab/prediction`

Extracts `Predicted binding affinity (∆G)` and writes CSV.

---

### 2) PRODIGY scraper

Script: `scrape_prodigy.py`

Targets:
`https://wenmr.science.uu.nl/prodigy/`

For each `.pdb` in a folder, it:
- uploads the structure,
- detects chain IDs from the PDB file and fills **Interactor 1** and **Interactor 2**,
- sets **Temperature** to `25`,
- sets **Job ID** to the PDB file name,
- clicks **Submit PRODIGY**,
- reads the results table under **Binding affinity and Kd prediction** and captures values from the first **data row** (not the header), with symbol-agnostic header handling (e.g., ΔG / K with subscript d),
- writes CSV columns in this order: `pdb_id,Del G,Kd`.

The script supports login with email/password (prompted if not passed through args).

---

### 3) PPA_Pred2 scraper

Script: `scrape_ppapred2.py`

Targets:
`https://www.iitm.ac.in/bioinfo/PPA_Pred/prediction.html`

For each FASTA file in a folder, it:
- reads FASTA input as either the first two FASTA entries, or one entry with `chain1:chain2` split by `:`,
- selects **Antigen-Antibody** from the input-page dropdown,
- generates headers as `>pdbid_A` and `>pdbid_B`, then pastes chain 1 in **Protein1** and chain 2 in **Protein 2**,
- clicks **Submit**,
- captures from results text:
  - `Predicted value of Delta G (binding free energy) is ... kcal/mol`
  - `Predicted value of Kd (dissociation constant) is ... M`
- writes CSV columns in this order: `pdb_id,Del G,Kd`.

## Install

```bash
pip install -r requirements.txt
```

## Run PRODIGY scraper

```bash
python scrape_prodigy.py \
  --pdb-folder /path/to/pdbs \
  --output /path/to/output.csv \
  --headless \
  --verbose
```

## Run PPA_Pred2 scraper

```bash
python scrape_ppapred2.py \
  --fasta-folder /path/to/fasta_files \
  --output /path/to/output.csv \
  --headless \
  --verbose \
  --timeout 240 \
  --debug-dir debug_artifacts
```

Optional login flags for PRODIGY:

```bash
python scrape_prodigy.py --pdb-folder /path/to/pdbs --output out.csv --email you@example.com --password 'secret'
```

---

### 4) Area Affinity scraper

Script: `scrape_area_affinity.py`

Targets:
`https://affinity.cuhk.edu.cn/`

For each `.pdb` in a folder, it:
- uploads the PDB file,
- detects two chain IDs from the structure and fills:
  - **Chain IDs of binding partner 1**
  - **Chain IDs of binding partner 2**
- clicks **RUN**,
- reads result row values for:
  - `Predicted binding affinity (log(K))`
  - `Predicted binding energy (kcal/mol)`
- writes CSV columns in this order:
  1. `pdb_id`
  2. `Predicted binding affinity (log(K))`
  3. `Predicted binding energy (kcal/mol)`

## Run Area Affinity scraper

```bash
python scrape_area_affinity.py \
  --pdb-folder /path/to/pdbs \
  --output /path/to/output.csv \
  --headless \
  --verbose
```

---

## Get UniProt IDs for proteins in a PDB complex

Yes — for a given **PDB ID**, you can retrieve UniProt IDs mapped to each chain:

```bash
python get_uniprot_from_pdb.py --pdb-id 1BRS
```

What it prints:
- chain-level mapping: `Chain -> UniProt`
- a quick summary for the first two detected chains (potential partner 1 / partner 2)

If a chain has no UniProt cross-reference in RCSB, it will print `NOT_MAPPED`.
