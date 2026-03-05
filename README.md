## csm_ab Selenium scraper

This script uploads `.pdb` file(s) from a folder to:

`https://biosig.lab.uq.edu.au/csm_ab/prediction`

Then it clicks **RUN PREDICTION**, extracts **Kd** and **Del G** from the results page, and saves them to a `.csv` file.

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python scrape_csm_ab.py --pdb-folder /path/to/pdb_files --output output.csv --headless
```

### CSV output format

Columns are written in this exact order:
1. `pdb_name`
2. `Del G`
3. `Kd`

Example:

```csv
pdb_name,Del G,Kd
example,-10.2,1.2e-8
```
