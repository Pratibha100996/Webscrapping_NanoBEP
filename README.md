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

For each `.pdb` in a folder, it:
- reads two chain sequences from the PDB,
- creates FASTA entries `>pdbid_chain` for each chain,
- pastes chain 1 FASTA in **Protein1** and chain 2 FASTA in **Protein 2**,
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
  --pdb-folder /path/to/pdbs \
  --output /path/to/output.csv \
  --headless \
  --verbose
```

Optional login flags for PRODIGY:

```bash
python scrape_prodigy.py --pdb-folder /path/to/pdbs --output out.csv --email you@example.com --password 'secret'
```
