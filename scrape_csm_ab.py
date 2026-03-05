import argparse
import csv
import re
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://biosig.lab.uq.edu.au/csm_ab/prediction"


def find_pdb_files(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdb"])


def extract_metric(page_text: str, metric: str) -> str:
    patterns = {
        "kd": [
            r"K\s*d\s*[:=]\s*([^\n\r]+)",
            r"\bKd\b\s*([^\n\r]+)",
        ],
        "delg": [
            r"(?:Δ|Del\s*|Delta\s*)?G\s*[:=]\s*([^\n\r]+)",
            r"\bDel\s*G\b\s*([^\n\r]+)",
        ],
    }

    for pattern in patterns[metric]:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()

    return "NOT_FOUND"


def wait_for_results(driver: webdriver.Chrome, timeout: int = 60) -> None:
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: "result" in d.current_url.lower() or "prediction" in d.page_source.lower())
    wait.until(lambda d: re.search(r"\bKd\b", d.page_source, re.IGNORECASE) or re.search(r"Del\s*G|Delta\s*G|ΔG", d.page_source, re.IGNORECASE))


def locate_upload_input(driver: webdriver.Chrome) -> object:
    wait = WebDriverWait(driver, 30)
    candidates = [
        (By.CSS_SELECTOR, "input[type='file']"),
        (By.XPATH, "//input[contains(@name,'pdb') and @type='file']"),
        (By.XPATH, "//label[contains(.,'PDB File')]/following::input[@type='file'][1]"),
    ]
    for by, selector in candidates:
        try:
            return wait.until(EC.presence_of_element_located((by, selector)))
        except Exception:
            continue
    raise RuntimeError("Could not find PDB file upload input on the page.")


def locate_run_button(driver: webdriver.Chrome) -> object:
    wait = WebDriverWait(driver, 30)
    candidates = [
        (By.XPATH, "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN PREDICTION')]") ,
        (By.XPATH, "//input[@type='submit' and contains(translate(@value, 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN PREDICTION')]") ,
        (By.XPATH, "//*[self::button or self::a][contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN') and contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'PREDICTION')]")
    ]
    for by, selector in candidates:
        try:
            return wait.until(EC.element_to_be_clickable((by, selector)))
        except Exception:
            continue
    raise RuntimeError("Could not find RUN PREDICTION button on the page.")


def run_prediction(driver: webdriver.Chrome, pdb_file: Path) -> Tuple[str, str, str]:
    driver.get(URL)

    upload = locate_upload_input(driver)
    upload.send_keys(str(pdb_file.resolve()))

    run_btn = locate_run_button(driver)
    run_btn.click()

    wait_for_results(driver)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    kd = extract_metric(body_text, "kd")
    del_g = extract_metric(body_text, "delg")
    pdb_id = pdb_file.stem
    return pdb_id, kd, del_g


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload PDB file(s) to csm_ab and extract Kd and Del G values.")
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb file(s).")
    parser.add_argument("--output", default="prediction_output.csv", help="Output csv file path.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    args = parser.parse_args()

    folder = Path(args.pdb_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {folder}")

    pdb_files = find_pdb_files(folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {folder}")

    results = []
    driver = create_driver(headless=args.headless)
    try:
        for pdb_file in pdb_files:
            try:
                results.append(run_prediction(driver, pdb_file))
            except Exception as exc:
                results.append((pdb_file.stem, f"ERROR: {exc}", "ERROR"))
    finally:
        driver.quit()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdb_name", "Del G", "Kd"])
        for pdb_id, kd, del_g in results:
            writer.writerow([pdb_id, del_g, kd])

    print(f"Saved output to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
