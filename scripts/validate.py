#!/usr/bin/env python3
"""Validate the five-repository catalog and offline installer behavior."""
from pathlib import Path
import subprocess
import sys
from install import load_catalog

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    try:
        entries = load_catalog()
    except (OSError, ValueError, KeyError) as exc:
        print(f"Catalog failed: {exc}")
        sys.exit(1)
    print(f"Catalog: {len(entries)} separate repositories")
    sys.exit(subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT).returncode)
