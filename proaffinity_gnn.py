"""Compatibility launcher for environments where hyphenated script names are inconvenient.

Usage:
    python proaffinity_gnn.py
"""

from pathlib import Path
import runpy

SCRIPT = Path(__file__).with_name("ProAffinity-GNN.py")

if not SCRIPT.exists():
    raise FileNotFoundError(f"Expected script not found: {SCRIPT}")

runpy.run_path(str(SCRIPT), run_name="__main__")
