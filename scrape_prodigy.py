import argparse
import csv
import getpass
import re
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://wenmr.science.uu.nl/prodigy/"


def find_pdb_files(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdb"])


def extract_chain_ids(pdb_file: Path) -> Tuple[str, str]:
    chains: List[str] = []
    with pdb_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(("ATOM", "HETATM")) and len(line) >= 22:
                chain = line[21].strip()
                if chain and chain not in chains:
                    chains.append(chain)

    if len(chains) >= 2:
        return chains[0], chains[1]
    if len(chains) == 1:
        return chains[0], chains[0]
    raise ValueError(f"No chain IDs found in {pdb_file}")


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
    for by, selector in locators:
        try:
            return wait.until(EC.presence_of_element_located((by, selector)))
        except Exception:
            continue
    raise RuntimeError(f"Element not found for locators: {locators}")


def click_first(driver: webdriver.Chrome, locators: List[Tuple[str, str]], timeout: int = 30):
    wait = WebDriverWait(driver, timeout)
    for by, selector in locators:
        try:
            elem = wait.until(EC.element_to_be_clickable((by, selector)))
            elem.click()
            return
        except Exception:
            continue
    raise RuntimeError(f"Clickable element not found for locators: {locators}")


def login_if_needed(driver: webdriver.Chrome, email: str, password: str, verbose: bool) -> None:
    email_inputs = driver.find_elements(By.XPATH, "//input[@type='email' or contains(@name,'email')]")
    password_inputs = driver.find_elements(By.XPATH, "//input[@type='password' or contains(@name,'password')]")

    if not (email_inputs and password_inputs):
        if verbose:
            print("[INFO] Login form not detected; proceeding.")
        return

    if verbose:
        print("[INFO] Login form detected, signing in...")

    email_input = email_inputs[0]
    password_input = password_inputs[0]
    email_input.clear()
    email_input.send_keys(email)
    password_input.clear()
    password_input.send_keys(password)

    click_first(
        driver,
        [
            (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'LOGIN') or contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SIGN IN')]") ,
            (By.XPATH, "//input[@type='submit']"),
        ],
        timeout=30,
    )

    WebDriverWait(driver, 60).until(
        lambda d: not (
            d.find_elements(By.XPATH, "//input[@type='email' or contains(@name,'email')]")
            and d.find_elements(By.XPATH, "//input[@type='password' or contains(@name,'password')]")
        )
    )


def submit_job(driver: webdriver.Chrome, pdb_file: Path, chain1: str, chain2: str, verbose: bool) -> None:
    driver.get(URL)

    upload_input = find_first(
        driver,
        [
            (By.CSS_SELECTOR, "input[type='file']"),
            (By.XPATH, "//label[contains(.,'Structure')]/following::input[@type='file'][1]"),
        ],
    )
    upload_input.send_keys(str(pdb_file.resolve()))

    inter1 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Interactor 1')]/following::input[1]"),
            (By.XPATH, "//input[contains(@name,'interactor') and contains(@name,'1')]") ,
            (By.XPATH, "(//input[@type='text'])[1]"),
        ],
    )
    inter1.clear()
    inter1.send_keys(chain1)

    inter2 = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Interactor 2')]/following::input[1]"),
            (By.XPATH, "//input[contains(@name,'interactor') and contains(@name,'2')]") ,
            (By.XPATH, "(//input[@type='text'])[2]"),
        ],
    )
    inter2.clear()
    inter2.send_keys(chain2)

    temp = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Temperature')]/following::input[1]"),
            (By.XPATH, "//input[contains(@name,'temp') or contains(@id,'temp')]") ,
        ],
    )
    temp.clear()
    temp.send_keys("25")

    job_id = find_first(
        driver,
        [
            (By.XPATH, "//label[contains(.,'Job ID')]/following::input[1]"),
            (By.XPATH, "//input[contains(@name,'job') and contains(@name,'id')]") ,
        ],
    )
    job_id.clear()
    job_id.send_keys(pdb_file.stem)

    click_first(
        driver,
        [
            (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT PRODIGY')]") ,
            (By.XPATH, "//input[@type='submit']"),
        ],
        timeout=30,
    )

    if verbose:
        print(f"[INFO] Submitted job for {pdb_file.stem} (chains {chain1}/{chain2})")


def parse_results(driver: webdriver.Chrome, timeout: int = 180) -> Tuple[str, str]:
    wait = WebDriverWait(driver, timeout)
    wait.until(
        lambda d: "Binding affinity and Kd prediction" in d.page_source
        or "Del G" in d.page_source
        or "Kd" in d.page_source
    )

    # Prefer table immediately following heading "Binding affinity and Kd prediction"
    section_rows = driver.find_elements(
        By.XPATH,
        (
            "//*[contains(normalize-space(.), 'Binding affinity and Kd prediction')]"
            "/following::table[1]//tr[td]"
        ),
    )
    for row in section_rows:
        values = [c.text.strip() for c in row.find_elements(By.XPATH, "./td")]
        if len(values) >= 3:
            delg_candidate = values[1]
            kd_candidate = values[2]
            if "Del G" not in delg_candidate and "Kd" not in kd_candidate:
                return delg_candidate, kd_candidate

    # Fallback: any table with header row containing Del G and Kd, then pick next data row
    tables = driver.find_elements(By.XPATH, "//table")
    for table in tables:
        header_text = table.text
        if "Del G" not in header_text or "Kd" not in header_text:
            continue
        rows = table.find_elements(By.XPATH, ".//tr[td]")
        for row in rows:
            values = [c.text.strip() for c in row.find_elements(By.XPATH, "./td")]
            if len(values) >= 3:
                delg_candidate = values[1]
                kd_candidate = values[2]
                if "Del G" in delg_candidate or "Kd" in kd_candidate:
                    continue
                return delg_candidate, kd_candidate

    # Last fallback: regex for numeric values near Del G and Kd labels
    page_text = driver.find_element(By.TAG_NAME, "body").text
    delg_match = re.search(r"Del\s*G[^\n\r]*\n\s*([-+]?\d+(?:\.\d+)?)", page_text, re.IGNORECASE)
    kd_match = re.search(r"\bKd\b[^\n\r]*\n\s*([\d\.eE+-]+(?:\s*[a-zA-ZµμnmpfM]*)?)", page_text, re.IGNORECASE)

    delg = delg_match.group(1).strip() if delg_match else "NOT_FOUND"
    kd = kd_match.group(1).strip() if kd_match else "NOT_FOUND"
    return delg, kd


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape PRODIGY results for PDB files and output CSV.")
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb file(s).")
    parser.add_argument("--output", default="prodigy_output.csv", help="Output CSV file path.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs.")
    parser.add_argument("--timeout", type=int, default=180, help="Timeout for results page.")
    parser.add_argument("--email", help="Login email for PRODIGY. If omitted, prompt interactively.")
    parser.add_argument("--password", help="Login password for PRODIGY. If omitted, prompt interactively.")
    args = parser.parse_args()

    folder = Path(args.pdb_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {folder}")

    pdb_files = find_pdb_files(folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {folder}")

    email = args.email or input("Enter PRODIGY email: ").strip()
    password = args.password or getpass.getpass("Enter PRODIGY password: ")

    results = []
    driver = create_driver(headless=args.headless)
    try:
        driver.get(URL)
        login_if_needed(driver, email, password, args.verbose)

        for pdb_file in pdb_files:
            pdb_id = pdb_file.stem
            try:
                chain1, chain2 = extract_chain_ids(pdb_file)
                if args.verbose:
                    print(f"[INFO] {pdb_id}: chains detected -> {chain1}, {chain2}")
                submit_job(driver, pdb_file, chain1, chain2, args.verbose)
                delg, kd = parse_results(driver, timeout=args.timeout)
                if args.verbose:
                    print(f"[INFO] {pdb_id}: Del G={delg}, Kd={kd}")
                results.append((pdb_id, delg, kd))
            except Exception as exc:
                if args.verbose:
                    print(f"[ERROR] {pdb_id}: {type(exc).__name__}: {exc}")
                results.append((pdb_id, f"ERROR: {type(exc).__name__}", "ERROR"))
    finally:
        driver.quit()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdb_id", "Del G", "Kd"])
        writer.writerows(results)

    print(f"Saved output to: {out.resolve()}")


if __name__ == "__main__":
    main()
