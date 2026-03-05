import argparse
import csv
import re
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

URL = "https://biosig.lab.uq.edu.au/csm_ab/prediction"


def find_pdb_files(folder: Path) -> List[Path]:
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".pdb"])


def extract_delg(page_text: str) -> str:
    # Expected label on result page: Predicted binding affinity (∆G):
    patterns = [
        r"Predicted\s+binding\s+affinity\s*\(\s*[∆Δ]\s*G\s*\)\s*:\s*([^\n\r]+)",
        r"Predicted\s+binding\s+affinity\s*\(\s*&Delta;\s*G\s*\)\s*:\s*([^\n\r]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return "NOT_FOUND"


def wait_for_results(driver: webdriver.Chrome, timeout: int = 180) -> None:
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: "result" in d.current_url.lower() or "prediction" in d.current_url.lower())

    def result_or_error_present(d: webdriver.Chrome) -> bool:
        text = d.find_element(By.TAG_NAME, "body").text
        has_delg = re.search(
            r"Predicted\s+binding\s+affinity\s*\(\s*[∆Δ]\s*G\s*\)\s*:",
            text,
            re.IGNORECASE,
        )
        has_error = re.search(r"error|failed|invalid|please\s+check", text, re.IGNORECASE)
        return bool(has_delg or has_error)

    wait.until(result_or_error_present)


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
        (
            By.XPATH,
            "//button[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN PREDICTION')]",
        ),
        (
            By.XPATH,
            "//input[@type='submit' and contains(translate(@value, 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN PREDICTION')]",
        ),
        (
            By.XPATH,
            "//*[self::button or self::a][contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'RUN') and contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'PREDICTION')]",
        ),
    ]
    for by, selector in candidates:
        try:
            return wait.until(EC.element_to_be_clickable((by, selector)))
        except Exception:
            continue
    raise RuntimeError("Could not find RUN PREDICTION button on the page.")


def save_debug_artifacts(driver: webdriver.Chrome, pdb_id: str, debug_dir: Path) -> Tuple[Path, Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    html_path = debug_dir / f"{pdb_id}_debug.html"
    png_path = debug_dir / f"{pdb_id}_debug.png"
    html_path.write_text(driver.page_source, encoding="utf-8")
    driver.save_screenshot(str(png_path))
    return html_path, png_path


def run_prediction(
    driver: webdriver.Chrome,
    pdb_file: Path,
    timeout: int,
    verbose: bool = False,
) -> Tuple[str, str]:
    if verbose:
        print(f"[INFO] Opening page for {pdb_file.name}")
    driver.get(URL)

    upload = locate_upload_input(driver)
    upload.send_keys(str(pdb_file.resolve()))
    if verbose:
        print(f"[INFO] Uploaded file: {pdb_file.resolve()}")

    run_btn = locate_run_button(driver)
    run_btn.click()
    if verbose:
        print("[INFO] Clicked RUN PREDICTION")

    wait_for_results(driver, timeout=timeout)

    body_text = driver.find_element(By.TAG_NAME, "body").text
    del_g = extract_delg(body_text)
    pdb_id = pdb_file.stem
    if verbose:
        print(f"[INFO] Extracted for {pdb_id}: Del G = {del_g}")
    return pdb_id, del_g


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
        description="Upload PDB file(s) to csm_ab and extract Predicted binding affinity (∆G)."
    )
    parser.add_argument("--pdb-folder", required=True, help="Folder containing .pdb file(s).")
    parser.add_argument("--output", default="prediction_output.csv", help="Output csv file path.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs.")
    parser.add_argument("--timeout", type=int, default=180, help="Result wait timeout in seconds.")
    parser.add_argument(
        "--debug-dir",
        default="debug_artifacts",
        help="Directory to save page HTML/screenshot on failures.",
    )
    args = parser.parse_args()

    folder = Path(args.pdb_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"PDB folder not found: {folder}")

    pdb_files = find_pdb_files(folder)
    if not pdb_files:
        raise FileNotFoundError(f"No .pdb files found in folder: {folder}")

    if args.verbose:
        print(f"[INFO] Found {len(pdb_files)} PDB file(s) in {folder}")

    results = []
    driver = create_driver(headless=args.headless)
    debug_dir = Path(args.debug_dir)
    try:
        for pdb_file in pdb_files:
            try:
                results.append(
                    run_prediction(
                        driver,
                        pdb_file,
                        timeout=args.timeout,
                        verbose=args.verbose,
                    )
                )
            except Exception as exc:
                pdb_id = pdb_file.stem
                html_path, png_path = save_debug_artifacts(driver, pdb_id, debug_dir)
                error_text = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if args.verbose:
                    print(f"[ERROR] {pdb_id}: {error_text}")
                    print(f"[ERROR] URL at failure: {driver.current_url}")
                    if isinstance(exc, TimeoutException):
                        print(
                            "[HINT] Timeout waiting for result text. "
                            "Try larger --timeout or run without --headless to inspect UI behavior."
                        )
                    print(f"[DEBUG] Saved HTML: {html_path}")
                    print(f"[DEBUG] Saved screenshot: {png_path}")
                results.append((pdb_id, f"ERROR: {error_text}"))
    finally:
        driver.quit()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdb_name", "Del G"])
        for pdb_id, del_g in results:
            writer.writerow([pdb_id, del_g])

    print(f"Saved output to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
