import os
import shlex
import subprocess
import sys
import venv
from pathlib import Path

REPO_URL = "https://github.com/legendzzy/ProAffinity-GNN.git"
DEFAULT_CLONE_DIR = Path("external") / "ProAffinity-GNN"


def step(msg: str) -> None:
    print(f"\n[STEP] {msg}", flush=True)


def run_cmd(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    printable = " ".join(shlex.quote(c) for c in cmd)
    where = f" (cwd={cwd})" if cwd else ""
    print(f"[CMD] {printable}{where}", flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def ensure_repo(path: Path) -> None:
    if (path / ".git").exists():
        step(f"Repository already exists at {path}. Pulling latest changes")
        run_cmd(["git", "pull", "--ff-only"], cwd=path)
        return

    step(f"Cloning ProAffinity-GNN into {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["git", "clone", REPO_URL, str(path)])


def ensure_venv(venv_dir: Path) -> Path:
    step(f"Creating virtual environment at {venv_dir} (if missing)")
    if not venv_dir.exists():
        venv.create(str(venv_dir), with_pip=True)

    if os.name == "nt":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"

    if not py.exists():
        raise RuntimeError(f"Python executable not found in virtualenv: {py}")
    return py


def install_dependencies(repo_dir: Path, py_exe: Path) -> None:
    step("Installing/upgrading Python dependencies")
    run_cmd([str(py_exe), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    req = repo_dir / "requirements.txt"
    if req.exists():
        run_cmd([str(py_exe), "-m", "pip", "install", "-r", str(req)])

    pyproject = repo_dir / "pyproject.toml"
    setup_py = repo_dir / "setup.py"
    if pyproject.exists() or setup_py.exists():
        run_cmd([str(py_exe), "-m", "pip", "install", "-e", str(repo_dir)])


def discover_command(repo_dir: Path) -> list[str] | None:
    candidates = [
        ["python", "predict.py", "--pdb", "{pdb}"],
        ["python", "inference.py", "--pdb", "{pdb}"],
        ["python", "main.py", "--pdb", "{pdb}"],
        ["python", "test.py", "--pdb", "{pdb}"],
        ["python", "predict.py", "{pdb}"],
        ["python", "inference.py", "{pdb}"],
    ]
    for c in candidates:
        script = repo_dir / c[1]
        if script.exists():
            return c
    return None


def run_prediction(repo_dir: Path, py_exe: Path, pdb_input: str) -> None:
    step("Preparing prediction command")
    discovered = discover_command(repo_dir)

    if discovered is None:
        print("[INFO] Could not auto-detect prediction entrypoint.")
        print("[INFO] Please provide a command template using {pdb}, e.g.:")
        print("       python predict.py --pdb {pdb}")
        custom = input("Prediction command template: ").strip()
        if not custom:
            raise RuntimeError("Prediction command template is required.")
        cmd = shlex.split(custom)
    else:
        cmd = discovered
        print(f"[INFO] Auto-detected command template: {' '.join(cmd)}")

    rendered = [pdb_input if part == "{pdb}" else part for part in cmd]
    rendered[0] = str(py_exe) if rendered[0] == "python" else rendered[0]

    step("Running model prediction")
    run_cmd(rendered, cwd=repo_dir)

    print("\n[DONE] Prediction command finished.")
    print("[INFO] Read the command output above for the predicted value.")


def main() -> None:
    print("ProAffinity-GNN setup + prediction helper")
    print("This script will clone/update the repository, install dependencies, and run prediction.")

    repo_dir = DEFAULT_CLONE_DIR
    venv_dir = repo_dir / ".venv"

    use_default = input(f"Use default clone directory '{repo_dir}'? [Y/n]: ").strip().lower()
    if use_default in {"n", "no"}:
        custom = input("Enter clone directory path: ").strip()
        if not custom:
            raise RuntimeError("Clone directory path is required.")
        repo_dir = Path(custom).expanduser().resolve()
        venv_dir = repo_dir / ".venv"

    pdb_input = input("Enter your PDB file path (or PDB ID, depending on tool support): ").strip()
    if not pdb_input:
        raise RuntimeError("PDB input is required.")

    ensure_repo(repo_dir)
    py_exe = ensure_venv(venv_dir)
    install_dependencies(repo_dir, py_exe)
    run_prediction(repo_dir, py_exe, pdb_input)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
