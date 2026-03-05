import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://www.iitm.ac.in/bioinfo/PPA_Pred/prediction.html"

AA3_TO_1: Dict[str, str] = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O",
}


def find_pdb_files(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdb"])


def extract_two_chain_fastas(pdb_file: Path) -> Tuple[Tuple[str, str], Tuple[str, str]]:
    chains: Dict[str, List[Tuple[Tuple[str, str, str], str]]] = {}

    with pdb_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            if len(line) < 27:
                continue

            resname = line[17:20].strip().upper()
            chain_id = line[21].strip()
            resseq = line[22:26].strip()
            icode = line[26].strip()

            if not chain_id:
                continue

            aa = AA3_TO_1.get(resname, "X")
            residue_key = (chain_id, resseq, icode)
            chains.setdefault(chain_id, []).append((residue_key, aa))

    if len(chains) < 2:
        raise ValueError(f"Need at least 2 chains in {pdb_file.name}; found {len(chains)}")

    chain_ids = sorted(chains.keys())[:2]
    chain_fastas: List[Tuple[str, str]] = []

    for chain_id in chain_ids:
        seq: List[str] = []
        seen_res = set()
        for residue_key, aa in chains[chain_id]:
            if residue_key in seen_res:
                continue
            seen_res.add(residue_key)
            seq.append(aa)
        sequence = "".join(seq)
        if not sequence:
            raise ValueError(f"Chain {chain_id} has empty sequence in {pdb_file.name}")
        header = f">{pdb_file.stem}_{chain_id}"
        chain_fastas.append((header, sequence))

    return chain_fastas[0], chain_fastas[1]


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def find_first(driver: webdriver.Chrome, locators: List[Tuple[str, str]], timeout: int = 30):
    wait = WebDriverWait(driver, timeout)
    for by, sel in locators:
        try:
            return wait.until(EC.presence_of_element_located((by, sel)))
        except Exception:
            continue
    raise RuntimeError(f"Could not find element with locators: {locators}")


def click_first(driver: webdriver.Chrome, locators: List[Tuple[str, str]], timeout: int = 30) -> None:
    wait = WebDriverWait(driver, timeout)
    for by, sel in locators:
        try:
            elem = wait.until(EC.element_to_be_clickable((by, sel)))
            elem.click()
            return
        except Exception:
            continue
    raise RuntimeError(f"Could not click element with locators: {locators}")


def parse_output_text(text: str) -> Tuple[str, str]:
    dg_match = re.search(
        r"Predicted\s+value\s+of\s+Delta\s*G\s*\(binding\s+free\s+energy\)\s+is\s+([-+]?\d+(?:\.\d+)?)\s*kcal/mol",
        text,
        re.IGNORECASE,
    )
    kd_match = re.search(
        r"Predicted\s+value\s+of\s+Kd\s*\(dissociation\s+constant\)\s+is\s+([\d.eE+-]+)\s*M",
        text,
        re.IGNORECASE,
    )

    del_g = dg_match.group(1).strip() if dg_match else "NOT_FOUND"
    kd = kd_match.group(1).strip() if kd_match else "NOT_FOUND"
    return del_g, kd


def run_prediction(driver: webdriver.Chrome, pdb_file: Path, timeout: int, verbose: bool) -> Tuple[str, str, str]:
    (h1, seq1), (h2, seq2) = extract_two_chain_fastas(pdb_file)
    pdb_id = pdb_file.stem

    if verbose:
        print(f"[INFO] {pdb_id}: using FASTA headers {h1} and {h2}")

    driver.get(URL)

    protein1 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Protein1')]/following::textarea[1]"),
            (By.XPATH, "(//textarea)[1]"),
        ],
    )
    protein2 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Protein 2') or contains(.,'Protein2')]/following::textarea[1]"),
            (By.XPATH, "(//textarea)[2]"),
        ],
    )

    protein1.clear()
    protein1.send_keys(f"{h1}\n{seq1}")
    protein2.clear()
    protein2.send_keys(f"{h2}\n{seq2}")

    click_first(
        driver,
        [
            (By.XPATH, "//input[@type='submit']"),
            (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]")
        ],
    )

    WebDriverWait(driver, timeout).until(
        lambda d: "Predicted value of Delta G" in d.page_source
        or "Output" in d.page_source
    )

    text = driver.find_element(By.TAG_NAME, "body").text
    del_g, kd = parse_output_text(text)

    if verbose:
        print(f"[INFO] {pdb_id}: Del G={del_g}, Kd={kd}")

    return pdb_id, del_g, kd


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape PPA_Pred2 predictions for PDB files.")
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb files")
    parser.add_argument("--output", default="ppapred2_output.csv", help="Output CSV path")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout for results (seconds)")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs")
    args = parser.parse_args()

    folder = Path(args.pdb_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {folder}")

    pdb_files = find_pdb_files(folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {folder}")

    if args.verbose:
        print(f"[INFO] Found {len(pdb_files)} PDB file(s) in {folder}")

    rows: List[Tuple[str, str, str]] = []
    driver = create_driver(headless=args.headless)
    try:
        for pdb_file in pdb_files:
            try:
                rows.append(run_prediction(driver, pdb_file, args.timeout, args.verbose))
            except Exception as exc:
                if args.verbose:
                    print(f"[ERROR] {pdb_file.stem}: {type(exc).__name__}: {exc}")
                rows.append((pdb_file.stem, f"ERROR: {type(exc).__name__}", "ERROR"))
    finally:
        driver.quit()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdb_id", "Del G", "Kd"])
        writer.writerows(rows)

    print(f"Saved output to: {out.resolve()}")


if __name__ == "__main__":
    main()
