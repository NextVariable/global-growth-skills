"""Run the offline GTM Harness from the repository root."""

import argparse
import json
from pathlib import Path
import sqlite3

from .adapters import FixtureAdapter
from .contracts import HarnessError
from .orchestrator import Harness


def input_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite file outside this repository")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("project")
    commands.add_parser("change").add_argument("patch")
    for name in ("start", "step", "resume", "status"):
        command = commands.add_parser(name)
        command.add_argument("run_id")
        if name == "start":
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--stages", nargs="+")
            selection.add_argument("--goal")
        if name in {"step", "resume"}:
            command.add_argument("--retry", action="store_true")
            command.add_argument("--recover", action="store_true")

    args = parser.parse_args()
    harness = None
    try:
        if args.command != "init" and not Path(args.db).is_file():
            raise HarnessError("initialize a project first")
        harness = Harness(args.db)
        if args.command == "init":
            project = input_json(args.project)
            harness.initialize(project)
            result = {"initialized": project["project_id"]}
        elif args.command == "change":
            result = harness.update(input_json(args.patch))
        elif args.command == "start":
            harness.start(args.run_id, stages=args.stages, goal=args.goal)
            result = harness.status(args.run_id)
        elif args.command == "status":
            result = harness.status(args.run_id)
        else:
            result = harness.status(args.run_id)
            limit = len(result["tasks"]) if args.command == "resume" else 1
            for index in range(limit):
                previous = result
                result = harness.step(args.run_id, FixtureAdapter(),
                                      retry=args.retry and index == 0, recover=args.recover and index == 0)
                if result == previous or all(task["status"] == "succeeded" for task in result["tasks"]):
                    break
        print(json.dumps(result, ensure_ascii=True, indent=2))
        if args.command == "resume" and any(t["status"] == "blocked" for t in result["tasks"]):
            return 2
        return 0
    except (HarnessError, OSError, ValueError, sqlite3.Error) as exc:
        detail = str(exc) if isinstance(exc, HarnessError) else type(exc).__name__
        parser.exit(1, f"Harness error: {detail}\n")
    finally:
        if harness is not None:
            harness.close()


if __name__ == "__main__":
    raise SystemExit(main())
