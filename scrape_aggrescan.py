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

URL = "http://andromeda.uab.cat/bioinf/aggrescan/"
RESULT_URL_MARKER = "aap_ov.pl"
OUTPUT_COLUMN = "Na4vSS"


def parse_fasta_file(fasta_path: Path) -> Dict[str, Tuple[str, str]]:
    """Return FASTA records keyed by the first four letters after each header's '>'."""
    records: Dict[str, Tuple[str, str]] = {}
    header: str | None = None
    chunks: List[str] = []

    with fasta_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    _store_record(records, header, chunks)
                header = line
                chunks = []
            else:
                chunks.append(re.sub(r"\s+", "", line))

    if header is not None:
        _store_record(records, header, chunks)

    if not records:
        raise ValueError(f"No FASTA records found in {fasta_path}")
    return records


def _store_record(records: Dict[str, Tuple[str, str]], header: str, chunks: List[str]) -> None:
    sequence = "".join(chunks).strip()
    if not sequence:
        return
    key = header[1:5].lower()
    if len(key) != 4:
        raise ValueError(f"FASTA header is too short to contain a four-letter PDB ID: {header}")
    records.setdefault(key, (header, sequence))


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def locate_sequence_box(driver: webdriver.Chrome, timeout: int = 30) -> WebElement:
    locators = [
        (By.CSS_SELECTOR, "textarea[name='sequence']"),
        (By.XPATH, "//textarea[@name='sequence' and @rows='20' and @cols='100']"),
        (By.XPATH, "//textarea[1]"),
    ]
    wait = WebDriverWait(driver, timeout)
    for locator in locators:
        try:
            return wait.until(EC.presence_of_element_located(locator))
        except Exception:
            continue
    raise RuntimeError("Could not locate AGGRESCAN sequence textarea")


def click_submit(driver: webdriver.Chrome, sequence_box: WebElement) -> None:
    submit_locators = [
        (By.CSS_SELECTOR, "input[type='submit']"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//input[contains(translate(@value,'SUBMIT','submit'),'submit')]"),
        (By.XPATH, "//button[contains(translate(.,'SUBMIT','submit'),'submit')]"),
    ]
    for locator in submit_locators:
        try:
            elem = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(locator))
            elem.click()
            return
        except Exception:
            continue

    form = driver.execute_script("return arguments[0].closest('form');", sequence_box)
    if form is not None:
        driver.execute_script("arguments[0].submit();", form)
        return
    raise RuntimeError("Could not submit AGGRESCAN form")


def wait_for_results(driver: webdriver.Chrome, timeout: int) -> None:
    def has_results(d: webdriver.Chrome) -> bool:
        body = d.find_element(By.TAG_NAME, "body").text
        return RESULT_URL_MARKER in d.current_url or "Normalized a4v Sequence Sum" in body

    WebDriverWait(driver, timeout).until(has_results)


def parse_na4vss(text: str, sequence_name: str | None = None) -> str:
    """Extract the Na4vSS score, preferring the rounded value in "Sorted by Na4vSS".

    AGGRESCAN pages include the full metric block and then a summary such as:
    "Sorted by Na4vSS" followed by "1g6v_K    -4.40". The user-requested
    CSV value is the number from that sorted summary line when it is available.
    """
    sorted_match = re.search(
        r"Sorted\s+by\s+Na4vSS(?P<table>.*?)(?:\n\s*#|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if sorted_match:
        table = sorted_match.group("table")
        escaped_name = re.escape(sequence_name.strip()) if sequence_name else r"\S+"
        summary_patterns = [
            rf"^\s*{escaped_name}\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$",
            r"^\s*\S+\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*$",
        ]
        for pattern in summary_patterns:
            for match in re.finditer(pattern, table, re.IGNORECASE | re.MULTILINE):
                return match.group(1).strip()

    patterns = [
        r"Normalized\s+a4v\s+Sequence\s+Sum\s+for\s+100\s+residues\s*\(\s*Na4vSS\s*\)\s*:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
        r"Na4vSS\s*\)?\s*:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "NOT_FOUND"


def run_prediction(driver: webdriver.Chrome, header: str, sequence: str, timeout: int, verbose: bool) -> str:
    driver.get(URL)
    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")

    sequence_box = locate_sequence_box(driver)
    sequence_box.clear()
    sequence_box.send_keys(f"{header}\n{sequence}")
    click_submit(driver, sequence_box)
    wait_for_results(driver, timeout)

    sequence_name = header.lstrip(">").split()[0]
    value = parse_na4vss(driver.find_element(By.TAG_NAME, "body").text, sequence_name)
    if verbose:
        print(f"[INFO] {header}: {OUTPUT_COLUMN}={value}")
    return value


def read_csv_rows(csv_path: Path) -> Tuple[List[str], List[dict]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {csv_path}")
        rows = list(reader)
        return list(reader.fieldnames), rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape AGGRESCAN Na4vSS values for PDB IDs in a CSV using sequences from a FASTA file."
    )
    parser.add_argument("--csv", required=True, help="Input CSV path; first column must contain PDB IDs")
    parser.add_argument("--fasta", required=True, help="Text/FASTA file containing FASTA records")
    parser.add_argument("--output", help="Output CSV path; defaults to overwriting --csv")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout for each result page in seconds")
    parser.add_argument("--verbose", action="store_true", help="Print progress logs")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    fasta_path = Path(args.fasta)
    output_path = Path(args.output) if args.output else csv_path

    fieldnames, rows = read_csv_rows(csv_path)
    pdb_column = fieldnames[0]
    if OUTPUT_COLUMN not in fieldnames:
        fieldnames.append(OUTPUT_COLUMN)

    fasta_records = parse_fasta_file(fasta_path)
    driver = create_driver(headless=args.headless)

    try:
        for row in rows:
            pdb_id = (row.get(pdb_column) or "").strip()[:4].lower()
            if not pdb_id:
                row[OUTPUT_COLUMN] = "ERROR: missing PDB ID"
                continue
            record = fasta_records.get(pdb_id)
            if record is None:
                row[OUTPUT_COLUMN] = "NOT_FOUND_IN_FASTA"
                if args.verbose:
                    print(f"[WARN] {pdb_id}: no matching FASTA header")
                continue
            try:
                row[OUTPUT_COLUMN] = run_prediction(driver, record[0], record[1], args.timeout, args.verbose)
            except (TimeoutException, WebDriverException, RuntimeError) as exc:
                row[OUTPUT_COLUMN] = f"ERROR: {type(exc).__name__}: {exc}"
                if args.verbose:
                    print(f"[ERROR] {pdb_id}: {row[OUTPUT_COLUMN]}")
    finally:
        driver.quit()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved output to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
