import argparse
import csv
import re
from pathlib import Path
from typing import List, Tuple

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

URL = "https://www.iitm.ac.in/bioinfo/PPA_Pred/prediction.html"


def find_fasta_files(folder: Path) -> List[Path]:
    valid = {".fa", ".fasta", ".faa", ".fas"}
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in valid])


def read_first_two_fasta_entries(fasta_file: Path) -> Tuple[Tuple[str, str], Tuple[str, str]]:
    """Read FASTA input supporting either:
    1) two separate FASTA entries, or
    2) one FASTA entry with chain1:chain2 sequence split by ':'

    Always returns headers in requested format: >pdbid_A and >pdbid_B.
    """
    entries: List[Tuple[str, str]] = []
    header = None
    seq_chunks: List[str] = []

    with fasta_file.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    entries.append((header, "".join(seq_chunks)))
                header = line
                seq_chunks = []
            else:
                seq_chunks.append(re.sub(r"\s+", "", line))

    if header is not None:
        entries.append((header, "".join(seq_chunks)))

    file_id = fasta_file.stem

    # Case A: two FASTA records
    if len(entries) >= 2:
        s1 = entries[0][1]
        s2 = entries[1][1]
        if not s1 or not s2:
            raise ValueError(f"First two FASTA sequences in {fasta_file.name} must be non-empty")
        return (f">{file_id}_A", s1), (f">{file_id}_B", s2)

    # Case B: one FASTA record with chain1:chain2 sequence format
    if len(entries) == 1:
        full_seq = entries[0][1]
        if ":" not in full_seq:
            raise ValueError(
                f"FASTA file {fasta_file.name} has one sequence; expected chain1:chain2 separated by ':'"
            )
        left, right = full_seq.split(":", 1)
        s1 = left.strip()
        s2 = right.strip()
        if not s1 or not s2:
            raise ValueError(
                f"FASTA file {fasta_file.name} has ':' separator but one side is empty"
            )
        return (f">{file_id}_A", s1), (f">{file_id}_B", s2)

    raise ValueError(f"FASTA file {fasta_file.name} does not contain valid sequence data")


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    # Reduce Chrome automation fingerprinting/infobars.
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(options=options)

    # Best-effort patch to mask navigator.webdriver for sites that hard-block automation.
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            },
        )
    except Exception:
        pass

    return driver


def find_first(driver: webdriver.Chrome, locators: List[Tuple[str, str]], timeout: int = 30):
    wait = WebDriverWait(driver, timeout)
    for by, sel in locators:
        try:
            return wait.until(EC.presence_of_element_located((by, sel)))
        except Exception:
            continue
    raise RuntimeError(f"Could not find element with locators: {locators}")


def _visible_elements(driver: webdriver.Chrome, xpath: str) -> List[WebElement]:
    return [elem for elem in driver.find_elements(By.XPATH, xpath) if elem.is_displayed()]


def locate_sequence_fields(driver: webdriver.Chrome, timeout: int = 30) -> Tuple[WebElement, WebElement]:
    """Locate the two sequence fields, preferring the known PPA-Pred2 IDs."""
    driver.switch_to.default_content()

    # First, use stable IDs from the PPA-Pred2 form when present.
    try:
        protein1 = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "sequence1"))
        )
        protein2 = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "sequence2"))
        )
        return protein1, protein2
    except Exception:
        pass

    candidate_xpaths = [
        "//textarea[not(@disabled)]",
        "//input[not(@disabled) and (@type='text' or not(@type))]",
        "//*[@contenteditable='true']",
    ]

    def find_in_current_context() -> Tuple[WebElement, WebElement] | None:
        for xpath in candidate_xpaths:
            elems = _visible_elements(driver, xpath)
            if len(elems) >= 2:
                return elems[0], elems[1]
        return None

    found = find_in_current_context()
    if found:
        return found

    frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")
    for frame in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            found = find_in_current_context()
            if found:
                return found
        except Exception:
            continue

    raise RuntimeError(
        "Could not locate two editable sequence input fields on page or within iframes"
    )


def click_or_submit(driver: webdriver.Chrome, context_elem: WebElement | None = None) -> None:
    """Submit the prediction form with strong preference for PPA-Pred2's known form controls."""
    submit_locators: List[Tuple[str, str]] = [
        (By.CSS_SELECTOR, "#myForm input[type='submit']"),
        (By.CSS_SELECTOR, "input[type='submit']"),
        (By.CSS_SELECTOR, "button[type='submit']"),
    ]

    for by, locator in submit_locators:
        try:
            elem = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((by, locator))
            )
            elem.click()
            return
        except Exception:
            continue

    if context_elem is not None:
        try:
            form = driver.execute_script(
                "return arguments[0].closest('form');", context_elem
            )
            if form is not None:
                submitted = driver.execute_script(
                    """
                    const form = arguments[0];
                    const submit = form.querySelector("input[type='submit'], button[type='submit']");
                    if (submit && !submit.disabled) { submit.click(); return true; }
                    if (typeof form.requestSubmit === 'function') { form.requestSubmit(); return true; }
                    return false;
                    """,
                    form,
                )
                if submitted:
                    return
        except Exception:
            pass

    raise RuntimeError("Could not submit PPA-Pred2 prediction form")




def select_antigen_antibody(driver: webdriver.Chrome) -> None:
    """Select Antigen-Antibody in the class dropdown under the input heading."""
    dropdown_candidates = [
        "//label[contains(.,'Select the class of the protein-protein complex of your interest')]/following::select[1]",
        "//select[contains(@name,'class') or contains(@id,'class')]",
        "//select[contains(@name,'complex') or contains(@id,'complex')]",
        "//select[1]",
    ]

    select_elem = None
    for xp in dropdown_candidates:
        elems = driver.find_elements(By.XPATH, xp)
        if elems:
            select_elem = elems[0]
            break

    if select_elem is None:
        return

    sel = Select(select_elem)

    # Strong preference for Antigen-Antibody (handle case variations/spacing)
    target = None
    for opt in sel.options:
        text = re.sub(r"\s+", " ", opt.text.strip()).lower()
        if "antigen" in text and "antibody" in text:
            target = opt
            break

    if target is not None:
        sel.select_by_visible_text(target.text)
        return

    for text in ["Antigen-Antibody", "Antigen-ANtibody", "Antigen - Antibody", "Antigen Antibody"]:
        try:
            sel.select_by_visible_text(text)
            return
        except Exception:
            continue




def is_url_not_found_page(driver: webdriver.Chrome) -> bool:
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return False
    markers = [
        "url is not found",
        "specified url is not found",
        "404 not found",
    ]
    return any(m in body_text for m in markers)

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


def save_debug_artifacts(driver: webdriver.Chrome, file_id: str, debug_dir: Path) -> Tuple[Path, Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    html_path = debug_dir / f"{file_id}_ppapred2_debug.html"
    png_path = debug_dir / f"{file_id}_ppapred2_debug.png"
    html_path.write_text(driver.page_source, encoding="utf-8")
    driver.save_screenshot(str(png_path))
    return html_path, png_path




def is_transient_connection_error(exc: Exception) -> bool:
    if isinstance(exc, RuntimeError) and "url-not-found" in str(exc).lower():
        return True
    if not isinstance(exc, WebDriverException):
        return False
    message = str(exc).lower()
    transient_markers = [
        "err_connection_closed",
        "err_connection_reset",
        "disconnected",
        "chrome not reachable",
        "target frame detached",
        "tab crashed",
    ]
    return any(marker in message for marker in transient_markers)


def save_debug_artifacts_safe(driver: webdriver.Chrome, file_id: str, debug_dir: Path) -> Tuple[Path | None, Path | None]:
    try:
        return save_debug_artifacts(driver, file_id, debug_dir)
    except Exception:
        return None, None


def restart_driver(driver: webdriver.Chrome, headless: bool, verbose: bool) -> webdriver.Chrome:
    try:
        driver.quit()
    except Exception:
        pass
    if verbose:
        print("[WARN] Restarting browser session after transient WebDriver/network failure.")
    return create_driver(headless=headless)

def run_prediction(driver: webdriver.Chrome, fasta_file: Path, timeout: int, verbose: bool) -> Tuple[str, str, str]:
    (h1, seq1), (h2, seq2) = read_first_two_fasta_entries(fasta_file)
    file_id = fasta_file.stem

    if verbose:
        print(f"[INFO] {file_id}: using FASTA entries {h1} and {h2}")

    driver.get(URL)

    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") == "complete")

    select_antigen_antibody(driver)

    protein1, protein2 = locate_sequence_fields(driver, timeout=30)

    protein1.clear()
    protein1.send_keys(f"{h1}\n{seq1}")
    protein2.clear()
    protein2.send_keys(f"{h2}\n{seq2}")

    click_or_submit(driver, context_elem=protein1)

    # Some server-side failures return a generic "URL is not found" page.
    if is_url_not_found_page(driver):
        raise RuntimeError(
            "PPA-Pred2 returned a URL-not-found page after submit; retrying may recover."
        )

    wait_for_result_page(driver, timeout)

    text = driver.find_element(By.TAG_NAME, "body").text
    del_g, kd = parse_output_text(text)

    if verbose:
        print(f"[INFO] {file_id}: Del G={del_g}, Kd={kd}")

    return file_id, del_g, kd


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape PPA_Pred2 predictions for FASTA files.")
    parser.add_argument("--fasta-folder", required=True, help="Folder containing .fa/.fasta files")
    parser.add_argument("--output", default="ppapred2_output.csv", help="Output CSV path")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--timeout", type=int, default=240, help="Timeout for results (seconds)")
    parser.add_argument("--verbose", action="store_true", help="Print verbose logs")
    parser.add_argument("--debug-dir", default="debug_artifacts", help="Directory for HTML/screenshot on errors")
    parser.add_argument("--retries", type=int, default=2, help="Retries per FASTA file after transient browser/network errors")
    args = parser.parse_args()

    folder = Path(args.fasta_folder)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"FASTA folder not found: {folder}")

    fasta_files = find_fasta_files(folder)
    if not fasta_files:
        raise FileNotFoundError(f"No FASTA files found in folder: {folder}")

    if args.verbose:
        print(f"[INFO] Found {len(fasta_files)} FASTA file(s) in {folder}")

    rows: List[Tuple[str, str, str]] = []
    driver = create_driver(headless=args.headless)
    debug_dir = Path(args.debug_dir)
    max_attempts = max(1, args.retries + 1)

    try:
        for fasta_file in fasta_files:
            file_id = fasta_file.stem
            last_exc: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    rows.append(run_prediction(driver, fasta_file, args.timeout, args.verbose))
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    transient = is_transient_connection_error(exc)

                    if transient and attempt < max_attempts:
                        if args.verbose:
                            print(
                                f"[WARN] {file_id}: transient WebDriver/network error "
                                f"on attempt {attempt}/{max_attempts}: {exc}"
                            )
                        driver = restart_driver(driver, headless=args.headless, verbose=args.verbose)
                        continue

                    html_path, png_path = save_debug_artifacts_safe(driver, file_id, debug_dir)
                    msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                    if args.verbose:
                        print(f"[ERROR] {file_id}: {msg}")
                        try:
                            print(f"[ERROR] URL at failure: {driver.current_url}")
                        except Exception:
                            print("[ERROR] URL at failure: <unavailable>")
                        if isinstance(exc, TimeoutException):
                            print("[HINT] Result text did not appear before timeout. Try --timeout 420 and inspect debug artifacts.")
                        elif transient:
                            print("[HINT] Transient connection crash from Chromium/network. Retried automatically; increase --retries if needed.")
                        if html_path and png_path:
                            print(f"[DEBUG] Saved HTML: {html_path}")
                            print(f"[DEBUG] Saved screenshot: {png_path}")
                        else:
                            print("[DEBUG] Could not save debug artifacts because browser session was unavailable.")
                    rows.append((file_id, f"ERROR: {msg}", "ERROR"))
                    break

            if last_exc is not None and args.verbose and max_attempts > 1:
                print(f"[INFO] {file_id}: exhausted {max_attempts} attempt(s).")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pdb_id", "Del G", "Kd"])
        writer.writerows(rows)

    print(f"Saved output to: {out.resolve()}")


if __name__ == "__main__":
    main()
