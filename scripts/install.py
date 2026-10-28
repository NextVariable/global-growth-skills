#!/usr/bin/env python3
"""Preview or install selected pinned skills. Existing directories are never merged."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load_catalog(path=ROOT / "catalog.json"):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("schema_version")) is not int
        or catalog["schema_version"] != 1
    ):
        raise ValueError("catalog must be an object with schema_version 1")
    entries = catalog.get("skills")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise ValueError("skills must be a list of skill objects")
    required = ("skill", "repository", "revision", "path")
    if any(any(not isinstance(item.get(field), str) for field in required) for item in entries):
        raise ValueError("each skill requires string skill, repository, revision and path fields")
    names = [item["skill"] for item in entries]
    if len(entries) != 5 or len(set(names)) != 5:
        raise ValueError("catalog must contain five distinct skills")
    if len({item["repository"] for item in entries}) != 5:
        raise ValueError("each skill must have its own repository")
    for item in entries:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item["skill"]):
            raise ValueError("invalid skill identifier")
        if not re.fullmatch(r"https://github\.com/NextVariable/[a-z0-9-]+", item["repository"]):
            raise ValueError("unexpected repository URL")
        if not re.fullmatch(r"[0-9a-f]{40}", item["revision"]):
            raise ValueError("revision must be a full commit SHA")
        if item["path"] != f"skills/{item['skill']}":
            raise ValueError("unexpected install path")
    return entries


def validate_install_record(entries, path):
    """Reject catalog updates that still claim installation of older revisions."""
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {item["skill"]: item["revision"] for item in entries}
    records = record.get("skills", [])
    actual = {item["skill"]: item["revision"] for item in records}
    if len(records) != len(expected) or actual != expected:
        raise ValueError(
            "installation acceptance revisions differ from catalog; rerun the pinned install"
        )
    if any(item.get("format_check") != "passed" for item in records):
        raise ValueError("installation acceptance contains an unvalidated package")
    return record


def select(entries, only):
    names = set(only or [item["skill"] for item in entries])
    unknown = names - {item["skill"] for item in entries}
    if unknown:
        raise ValueError("unknown skill: " + ", ".join(sorted(unknown)))
    return [item for item in entries if item["skill"] in names]


def check_dest(entries, dest):
    if dest.exists() and not dest.is_dir():
        raise ValueError("destination is not a directory")
    for item in entries:
        target = dest / item["skill"]
        if target.exists() or target.is_symlink():
            raise ValueError(f"already exists; no files changed: {target}")


def fetch(item, checkout):
    # Keep this outside the downloaded tree so a repository cannot supply hooks.
    hooks = checkout.parent / (checkout.name + "-trusted-empty-hooks")
    hooks.mkdir()
    commands = [
        ["git", "init", "--quiet", str(checkout)],
        ["git", "-C", str(checkout), "remote", "add", "origin", item["repository"] + ".git"],
        [
            "git",
            "-C",
            str(checkout),
            "fetch",
            "--ipv4",
            "--quiet",
            "--depth",
            "1",
            "origin",
            item["revision"],
        ],
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            f"core.hooksPath={hooks}",
            "checkout",
            "--quiet",
            "--detach",
            "FETCH_HEAD",
        ],
    ]
    for command in commands:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    actual = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if actual != item["revision"]:
        raise ValueError("downloaded revision mismatch")
    source = checkout / item["path"]
    if not source.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("install source escapes checkout")
    return source


def install(entries, dest, fetcher=fetch):
    check_dest(entries, dest)
    installed = []
    with tempfile.TemporaryDirectory(prefix="growth-skills-") as temp:
        sources = []
        for index, item in enumerate(entries):
            source = fetcher(item, Path(temp) / str(index))
            if not (source / "SKILL.md").is_file() or not (source / "LICENSE").is_file():
                raise ValueError(f"incomplete skill package: {item['skill']}")
            if source.is_symlink() or any(path.is_symlink() for path in source.rglob("*")):
                raise ValueError("symlinks are not accepted in install units")
            sources.append(source)
        # All downloads complete before changing the destination.
        check_dest(entries, dest)
        dest.mkdir(parents=True, exist_ok=True)
        for item, source in zip(entries, sources):
            target = dest / item["skill"]
            try:
                shutil.copytree(
                    source,
                    target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                )
            except OSError as exc:
                raise ValueError(
                    f"copy failed at {target}; inspect that directory; previously installed: {', '.join(installed) or 'none'}"
                ) from exc
            installed.append(item["skill"])
    return installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--only", nargs="+")
    parser.add_argument(
        "--install", action="store_true", help="download and copy; otherwise only preview"
    )
    args = parser.parse_args()
    try:
        entries = select(load_catalog(), args.only)
        dest = args.dest.expanduser().absolute()
        for item in entries:
            print(f"{item['skill']} @ {item['revision'][:12]} -> {dest / item['skill']}")
        if not args.install:
            print(
                "Preview only. Add --install to download and copy. Existing skill directories will not be overwritten."
            )
            return 0
        installed = install(entries, dest)
        print("Installed: " + ", ".join(installed))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"Installation stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
