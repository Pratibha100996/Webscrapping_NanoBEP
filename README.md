## csm_ab Selenium scraper

This script uploads `.pdb` file(s) from a folder to:

`https://biosig.lab.uq.edu.au/csm_ab/prediction`

Then it clicks **RUN PREDICTION**, extracts **Kd** and **Del G** from the results page, and saves them to a `.txt` file with the PDB ID.

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python scrape_csm_ab.py --pdb-folder /path/to/pdb_files --output output.txt --headless
```

### Output format

```text
PDB_ID: example
Kd: ...
Del G: ...
----------------------------------------
```
