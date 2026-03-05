import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
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
            if not line.startswith("ATOM") or len(line) < 27:
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

    chain_fastas: List[Tuple[str, str]] = []
    for chain_id in sorted(chains.keys())[:2]:
        seq: List[str] = []
        seen_res = set()
        for residue_key, aa in chains[chain_id]:
            if residue_key in seen_res:
                continue
            seen_res.add(residue_key)
            seq.append(aa)
        if not seq:
            raise ValueError(f"Chain {chain_id} has empty sequence in {pdb_file.name}")
        chain_fastas.append((f">{pdb_file.stem}_{chain_id}", "".join(seq)))

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


def click_or_submit(driver: webdriver.Chrome) -> None:
    # Try explicit submit controls first
    candidates = [
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]"),
    ]
    for by, sel in candidates:
        try:
            elem = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((by, sel)))
            elem.click()
            return
        except Exception:
            continue

    # Fallback: submit nearest form using JS
    driver.execute_script(
        """
        const t1 = document.querySelectorAll('textarea');
        if (t1.length) {
          const form = t1[0].closest('form');
          if (form) { form.submit(); return true; }
        }
        return false;
        """
    )


def parse_output_text(text: str) -> Tuple[str, str]:
    dg_patterns = [
        r"Predicted\s+value\s+of\s+Delta\s*G\s*\(binding\s+free\s+energy\)\s*is\s*([-+]?\d+(?:\.\d+)?)",
        r"Delta\s*G[^\n\r]*?is\s*([-+]?\d+(?:\.\d+)?)",
    ]
    kd_patterns = [
        r"Predicted\s+value\s+of\s+K\s*d\s*\(dissociation\s+constant\)\s*is\s*([\d.eE+-]+)",
        r"\bK\s*d\b[^\n\r]*?is\s*([\d.eE+-]+)",
    ]

    del_g = "NOT_FOUND"
    kd = "NOT_FOUND"

    for p in dg_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            del_g = m.group(1).strip()
            break

    for p in kd_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            kd = m.group(1).strip()
            break

    return del_g, kd


def wait_for_result_page(driver: webdriver.Chrome, timeout: int) -> None:
    wait = WebDriverWait(driver, timeout)

    def has_output(d: webdriver.Chrome) -> bool:
        text = d.find_element(By.TAG_NAME, "body").text
        return bool(
            re.search(r"Predicted\s+value\s+of\s+Delta\s*G", text, re.IGNORECASE)
            or re.search(r"dissociation\s+constant", text, re.IGNORECASE)
            or re.search(r"\bOutput\b", text, re.IGNORECASE)
        )

    wait.until(has_output)


def save_debug_artifacts(driver: webdriver.Chrome, pdb_id: str, debug_dir: Path) -> Tuple[Path, Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    html_path = debug_dir / f"{pdb_id}_ppapred2_debug.html"
    png_path = debug_dir / f"{pdb_id}_ppapred2_debug.png"
    html_path.write_text(driver.page_source, encoding="utf-8")
    driver.save_screenshot(str(png_path))
    return html_path, png_path


def run_prediction(
    driver: webdriver.Chrome,
    pdb_file: Path,
    timeout: int,
    verbose: bool,
) -> Tuple[str, str, str]:
    (h1, seq1), (h2, seq2) = extract_two_chain_fastas(pdb_file)
    pdb_id = pdb_file.stem

    if verbose:
        print(f"[INFO] {pdb_id}: using FASTA headers {h1} and {h2}")

    driver.get(URL)

    protein1 = find_first(driver, [(By.XPATH, "(//textarea)[1]")])
    protein2 = find_first(driver, [(By.XPATH, "(//textarea)[2]")])

    protein1.clear()
    protein1.send_keys(f"{h1}\n{seq1}")
    protein2.clear()
    protein2.send_keys(f"{h2}\n{seq2}")

    click_or_submit(driver)
    wait_for_result_page(driver, timeout)

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
    parser.add_argument("--timeout", type=int, default=240, help="Timeout for results (seconds)")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs")
    parser.add_argument("--debug-dir", default="debug_artifacts", help="Directory for HTML/screenshot on errors")
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
    debug_dir = Path(args.debug_dir)
    try:
        for pdb_file in pdb_files:
            try:
                rows.append(run_prediction(driver, pdb_file, args.timeout, args.verbose))
            except Exception as exc:
                pdb_id = pdb_file.stem
                html_path, png_path = save_debug_artifacts(driver, pdb_id, debug_dir)
                msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if args.verbose:
                    print(f"[ERROR] {pdb_id}: {msg}")
                    print(f"[ERROR] URL at failure: {driver.current_url}")
                    if isinstance(exc, TimeoutException):
                        print("[HINT] Result text did not appear before timeout. Try --timeout 420 and inspect debug artifacts.")
                    print(f"[DEBUG] Saved HTML: {html_path}")
                    print(f"[DEBUG] Saved screenshot: {png_path}")
                rows.append((pdb_id, f"ERROR: {msg}", "ERROR"))
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
