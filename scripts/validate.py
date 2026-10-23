#!/usr/bin/env python3
"""Validate the five-repository catalog and offline installer behavior."""

from pathlib import Path
import re
import subprocess
import sys
from install import load_catalog

ROOT = Path(__file__).resolve().parents[1]


def documentation_errors(root):
    """Check maintained documentation links; raw historical outputs are not rewritten."""
    errors = []
    files = [root / "README.md", root / "CONTRIBUTING.md"]
    files += list((root / "docs").rglob("*.md"))
    files += list((root / "examples").rglob("*.md"))
    for path in files:
        if not path.is_file():
            continue
        body = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for link in re.findall(r"\[[^\]\n]+\]\(([^)]+)\)", body):
            target = link.split("#", 1)[0].strip("<>")
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                errors.append(f"broken documentation link: {path.relative_to(root)} -> {target}")
    return errors


if __name__ == "__main__":
    try:
        entries = load_catalog()
    except (OSError, ValueError, KeyError) as exc:
        print(f"Catalog failed: {exc}")
        sys.exit(1)
    errors = documentation_errors(ROOT)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"Catalog: {len(entries)} separate repositories")
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT
        ).returncode
    )
