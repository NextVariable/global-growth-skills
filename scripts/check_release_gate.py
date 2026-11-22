"""Check release gate and readiness files against the current candidate commit."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
COMMIT_FIELDS = ("accepted_head", "head_commit", "base_commit", "merge_commit")
SHA = re.compile(r"^[0-9a-f]{40}$")


def git(*arguments, check=True):
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def commit_exists(sha):
    return git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def is_ancestor(sha):
    return git("merge-base", "--is-ancestor", sha, "HEAD", check=False).returncode == 0


def tracked_files():
    return len([line for line in git("ls-files").stdout.splitlines() if line])


def declared_tests(report):
    match = re.search(r"Ran (\d+) tests?", Path(report).read_text())
    return int(match.group(1)) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unittest-report", help="unittest output to compare with declared test counts")
    parser.add_argument(
        "--shallow",
        action="store_true",
        help="skip commit existence and ancestry checks when the clone has no history",
    )
    args = parser.parse_args()

    failures = []
    expected_catalog = {
        entry["skill"]: entry["revision"]
        for entry in json.loads((ROOT / "catalog.json").read_text())["skills"]
    }
    count = tracked_files()
    measured_tests = declared_tests(args.unittest_report) if args.unittest_report else None

    for path in sorted(VALIDATION.glob("*.json")):
        data = json.loads(path.read_text())
        label = path.name
        for field in COMMIT_FIELDS:
            sha = data.get(field)
            if not sha:
                continue
            if not SHA.fullmatch(sha):
                failures.append(f"{label}: {field} is not a 40-character commit SHA")
            elif not args.shallow and not commit_exists(sha):
                failures.append(f"{label}: {field} {sha} is not in this checkout")
            elif not args.shallow and not is_ancestor(sha):
                failures.append(f"{label}: {field} {sha} is not an ancestor of HEAD")

        ci_head = (data.get("ci") or {}).get("head")
        if ci_head:
            if not SHA.fullmatch(ci_head):
                failures.append(f"{label}: ci.head is not a commit SHA")
            elif not args.shallow and not commit_exists(ci_head):
                failures.append(f"{label}: ci.head {ci_head} is not in this checkout")
            elif not args.shallow and not is_ancestor(ci_head):
                failures.append(f"{label}: ci.head {ci_head} is not an ancestor of HEAD")

        catalog = data.get("catalog")
        if isinstance(catalog, dict) and "revisions" in catalog:
            if catalog["revisions"] != expected_catalog:
                failures.append(f"{label}: catalog revisions do not match catalog.json")
            if catalog.get("entries") not in (None, len(expected_catalog)):
                failures.append(f"{label}: catalog entry count does not match catalog.json")

        verification = data.get("verification")
        if isinstance(verification, dict):
            if "tracked_files" in verification and verification["tracked_files"] != count:
                failures.append(
                    f"{label}: tracked_files is {verification['tracked_files']}, checkout has {count}"
                )
            declared = verification.get("harness_tests")
            if measured_tests is not None and declared != measured_tests:
                failures.append(
                    f"{label}: harness_tests is {declared}, report ran {measured_tests}"
                )

    for failure in failures:
        print(f"FAIL {failure}")
    if not failures:
        print(f"OK release gates match HEAD {git('rev-parse', '--short', 'HEAD').stdout.strip()}; "
              f"{count} tracked files")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
