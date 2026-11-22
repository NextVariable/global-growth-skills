"""Run the opt-in Harness suite and retain the complete unittest report."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/harness", "-v"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(result.stdout, encoding="utf-8")
    print(result.stdout, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
