import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://proteiniq.io/app/ramachandran-plot"
OUTPUT_COLUMNS = ["Favored", "Allowed", "Outlier"]


def find_pdb_files(folder: Path) -> Dict[str, Path]:
    """Return .pdb files keyed by the first four characters of the file stem."""
    pdb_files: Dict[str, Path] = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() == ".pdb":
            key = path.stem[:4].lower()
            if len(key) == 4:
                pdb_files.setdefault(key, path)
    return pdb_files


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def wait_for_app(driver: webdriver.Chrome, timeout: int = 30) -> None:
    WebDriverWait(driver, timeout).until(lambda d: d.execute_script("return document.readyState") == "complete")
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Ramachandran plot')]"))
    )


def find_upload_input(driver: webdriver.Chrome, timeout: int = 30) -> WebElement:
    locators = [
        (By.CSS_SELECTOR, "input[type='file']"),
        (
            By.XPATH,
            "//*[contains(normalize-space(.), 'Protein Structure') or contains(normalize-space(.), 'Upload files')]/following::input[@type='file'][1]",
        ),
    ]
    wait = WebDriverWait(driver, timeout)
    for locator in locators:
        try:
            return wait.until(EC.presence_of_element_located(locator))
        except Exception:
            continue
    raise RuntimeError("Could not locate ProteinIQ upload input")


def click_generate(driver: webdriver.Chrome, timeout: int = 30) -> None:
    locators = [
        (By.XPATH, "//button[normalize-space()='Generate']"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'generate')]"),
        (By.XPATH, "//input[@type='submit' and contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'generate')]"),
    ]
    wait = WebDriverWait(driver, timeout)
    for locator in locators:
        try:
            button = wait.until(EC.element_to_be_clickable(locator))
            button.click()
            return
        except Exception:
            continue
    raise RuntimeError("Could not locate Generate button")


def normalize_label(text: str) -> str:
    return re.sub(r"[^a-z]+", "", text.lower())


def extract_numeric_value(text: str) -> str | None:
    percent = re.search(r"([-+]?\d+(?:\.\d+)?\s*%)", text)
    if percent:
        return percent.group(1).strip()
    number = re.search(r"([-+]?\d+(?:\.\d+)?)", text)
    if number:
        return number.group(1).strip()
    return None


def parse_quality_values(page_text: str) -> Tuple[str, str, str]:
    """Extract Structure Quality values for Favored, Allowed, and Outlier from visible page text."""
    values = {column: "NOT_FOUND" for column in OUTPUT_COLUMNS}
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        label = normalize_label(line)
        for column in OUTPUT_COLUMNS:
            if normalize_label(column) not in label or values[column] != "NOT_FOUND":
                continue

            inline_text = re.sub(rf".*?{re.escape(column)}(?:\s+residues?)?\s*[:\-]?", "", line, flags=re.IGNORECASE)
            inline = extract_numeric_value(inline_text)
            if inline is not None:
                values[column] = inline
                continue

            for next_line in lines[i + 1 : i + 4]:
                value = extract_numeric_value(next_line)
                if value is not None:
                    values[column] = value
                    break

    return values["Favored"], values["Allowed"], values["Outlier"]


def wait_for_quality_results(driver: webdriver.Chrome, timeout: int) -> Tuple[str, str, str]:
    def has_quality_values(d: webdriver.Chrome):
        text = d.find_element(By.TAG_NAME, "body").text
        lowered = text.lower()
        if "structure quality" not in lowered:
            return False
        favored, allowed, outlier = parse_quality_values(text)
        if any(value != "NOT_FOUND" for value in (favored, allowed, outlier)):
            return favored, allowed, outlier
        return False

    return WebDriverWait(driver, timeout).until(has_quality_values)


def run_prediction(driver: webdriver.Chrome, pdb_file: Path, timeout: int, verbose: bool) -> Tuple[str, str, str]:
    driver.get(URL)
    wait_for_app(driver)

    upload_input = find_upload_input(driver)
    upload_input.send_keys(str(pdb_file.resolve()))
    click_generate(driver)

    values = wait_for_quality_results(driver, timeout)
    if verbose:
        print(f"[INFO] {pdb_file.name}: Favored={values[0]}, Allowed={values[1]}, Outlier={values[2]}")
    return values


def read_csv_rows(csv_path: Path) -> Tuple[List[str], List[dict]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {csv_path}")
        rows = list(reader)
        return list(reader.fieldnames), rows


def write_csv_rows(csv_path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape ProteinIQ Ramachandran Structure Quality values for PDB files listed in a CSV."
    )
    parser.add_argument("--csv", required=True, help="Input CSV path; first column must contain PDB IDs")
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb structure files")
    parser.add_argument("--output", help="Output CSV path; defaults to overwriting --csv")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout for each ProteinIQ result in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print progress logs")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    pdb_folder = Path(args.pdb_folder)
    output_path = Path(args.output) if args.output else csv_path

    if not pdb_folder.exists() or not pdb_folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {pdb_folder}")

    fieldnames, rows = read_csv_rows(csv_path)
    pdb_column = fieldnames[0]
    for column in OUTPUT_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    pdb_files = find_pdb_files(pdb_folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {pdb_folder}")

    driver = create_driver(headless=args.headless)
    try:
        for row in rows:
            pdb_id = (row.get(pdb_column) or "").strip()
            key = pdb_id[:4].lower()
            if len(key) != 4:
                for column in OUTPUT_COLUMNS:
                    row[column] = "ERROR: missing PDB ID"
                continue

            pdb_file = pdb_files.get(key)
            if pdb_file is None:
                for column in OUTPUT_COLUMNS:
                    row[column] = "NOT_FOUND_IN_PDB_FOLDER"
                if args.verbose:
                    print(f"[WARN] {pdb_id}: no .pdb file with first four letters '{key}'")
                continue

            try:
                favored, allowed, outlier = run_prediction(driver, pdb_file, args.timeout, args.verbose)
                row["Favored"] = favored
                row["Allowed"] = allowed
                row["Outlier"] = outlier
            except (TimeoutException, WebDriverException, RuntimeError) as exc:
                message = f"ERROR: {type(exc).__name__}: {exc}"
                for column in OUTPUT_COLUMNS:
                    row[column] = message
                if args.verbose:
                    print(f"[ERROR] {pdb_id}: {message}")
    finally:
        driver.quit()

    write_csv_rows(output_path, fieldnames, rows)
    print(f"Saved output to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
