## csm_ab Selenium scraper

This script uploads `.pdb` file(s) from a folder to:

`https://biosig.lab.uq.edu.au/csm_ab/prediction`

Then it clicks **RUN PREDICTION**, extracts **only Del G** from:

`Predicted binding affinity (∆G):`

and saves results to a `.csv` file.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python scrape_csm_ab.py --pdb-folder /path/to/pdb_files --output output.csv --headless --verbose
```

## CSV output format

Columns are written in this order:
1. `pdb_name`
2. `Del G`

Example:

```csv
pdb_name,Del G
example,-10.2 kcal/mol
```
