import argparse
import csv
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://affinity.cuhk.edu.cn/"


def find_pdb_files(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdb"])


def extract_partner_chains(pdb_file: Path) -> Tuple[str, str]:
    chains: List[str] = []
    with pdb_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and len(line) >= 22:
                chain_id = line[21].strip()
                if chain_id and chain_id not in chains:
                    chains.append(chain_id)

    if len(chains) < 2:
        raise ValueError(f"Need at least 2 chains in {pdb_file.name}; found {len(chains)}")

    return chains[0], chains[1]


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
    raise RuntimeError(f"Could not find element: {locators}")


def click_first(driver: webdriver.Chrome, locators: List[Tuple[str, str]], timeout: int = 30) -> None:
    wait = WebDriverWait(driver, timeout)
    for by, sel in locators:
        try:
            wait.until(EC.element_to_be_clickable((by, sel))).click()
            return
        except Exception:
            continue
    raise RuntimeError(f"Could not click element: {locators}")


def parse_results(driver: webdriver.Chrome, timeout: int = 180) -> Tuple[str, str]:
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: "Predicted binding affinity" in d.page_source and "Predicted binding energy" in d.page_source)

    rows = driver.find_elements(By.XPATH, "//table//tr[td]")
    for row in rows:
        cells = [c.text.strip() for c in row.find_elements(By.XPATH, "./td")]
        if len(cells) >= 3 and "mixed model" in cells[0].lower():
            return cells[1], cells[2]

    # fallback first data row with >=3 columns
    for row in rows:
        cells = [c.text.strip() for c in row.find_elements(By.XPATH, "./td")]
        if len(cells) >= 3:
            return cells[1], cells[2]

    return "NOT_FOUND", "NOT_FOUND"


def run_one(driver: webdriver.Chrome, pdb_file: Path, timeout: int, verbose: bool) -> Tuple[str, str, str]:
    pdb_id = pdb_file.stem
    c1, c2 = extract_partner_chains(pdb_file)

    if verbose:
        print(f"[INFO] {pdb_id}: chains {c1}/{c2}")

    driver.get(URL)

    upload = find_first(
        driver,
        [
            (By.CSS_SELECTOR, "input[type='file']"),
            (By.XPATH, "//input[@type='file']"),
        ],
    )
    upload.send_keys(str(pdb_file.resolve()))

    p1 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Chain IDs of binding partner 1')]/following::input[1]"),
            (By.XPATH, "(//input[@type='text'])[1]"),
        ],
    )
    p2 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Chain IDs of binding partner 2')]/following::input[1]"),
            (By.XPATH, "(//input[@type='text'])[2]"),
        ],
    )
    p1.clear()
    p1.send_keys(c1)
    p2.clear()
    p2.send_keys(c2)

    click_first(
        driver,
        [
            (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN')]"),
            (By.XPATH, "//input[@type='submit']"),
        ],
    )

    affinity_logk, energy_kcal = parse_results(driver, timeout=timeout)
    if verbose:
        print(f"[INFO] {pdb_id}: log(K)={affinity_logk}, energy={energy_kcal}")

    return pdb_id, affinity_logk, energy_kcal


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Area Affinity predictions from affinity.cuhk.edu.cn")
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb files")
    parser.add_argument("--output", default="area_affinity_output.csv", help="Output CSV file path")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout", type=int, default=180, help="Result wait timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs")
    args = parser.parse_args()

    folder = Path(args.pdb_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {folder}")

    pdb_files = find_pdb_files(folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {folder}")

    rows: List[Tuple[str, str, str]] = []
    driver = create_driver(headless=args.headless)
    try:
        for pdb_file in pdb_files:
            try:
                rows.append(run_one(driver, pdb_file, args.timeout, args.verbose))
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
        writer.writerow([
            "pdb_id",
            "Predicted binding affinity (log(K))",
            "Predicted binding energy (kcal/mol)",
        ])
        writer.writerows(rows)

    print(f"Saved output to: {out.resolve()}")


if __name__ == "__main__":
    main()
