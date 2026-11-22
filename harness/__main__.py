"""Run the GTM Harness from the repository root."""

import argparse
import json
from pathlib import Path
import sqlite3

from . import __version__
from .adapters import FixtureAdapter, HandoffAdapter
from .codex_host import CodexAdapter, handoff
from .contracts import digest
from .gateway import Gateway
from .contracts import HarnessError
from .orchestrator import Harness


def input_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--db", required=True, help="SQLite file outside this repository"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("project")
    commands.add_parser("change").add_argument("patch")
    commands.add_parser("restore").add_argument("revision", type=int)
    approve = commands.add_parser("approve-mock")
    approve.add_argument("operation")
    approve.add_argument("--ttl", type=int, default=300)
    commands.add_parser("revoke-mock").add_argument("operation_id")
    commands.add_parser("execute-mock").add_argument("operation")
    commands.add_parser("receipts")
    for name in ("start", "step", "resume", "status", "handoff"):
        command = commands.add_parser(name)
        command.add_argument("run_id")
        if name == "start":
            command.add_argument(
                "--execution",
                choices=("fixture", "model", "handoff"),
                default="fixture",
            )
            selection = command.add_mutually_exclusive_group()
            selection.add_argument("--stages", nargs="+")
            selection.add_argument("--goal")
        if name in {"step", "resume", "handoff"}:
            command.add_argument(
                "--checkout", action="append", default=[], metavar="STAGE=DIR"
            )
        if name in {"step", "resume"}:
            command.add_argument("--model")
            command.add_argument("--results")
            command.add_argument("--timeout", type=int, default=120)
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
        elif args.command == "restore":
            result = harness.restore(args.revision)
        elif args.command == "start":
            harness.start(
                args.run_id, args.execution, stages=args.stages, goal=args.goal
            )
            result = harness.status(args.run_id)
        elif args.command == "status":
            result = harness.status(args.run_id)
        elif args.command in {
            "approve-mock",
            "revoke-mock",
            "execute-mock",
            "receipts",
        }:
            gateway = Gateway(harness)
            if args.command == "approve-mock":
                gateway.approve(input_json(args.operation), args.ttl)
                result = {"status": "approved", "executor": "mock"}
            elif args.command == "revoke-mock":
                gateway.revoke(args.operation_id)
                result = {"status": "revoked", "executor": "mock"}
            elif args.command == "execute-mock":
                result = gateway.write(input_json(args.operation))
            else:
                result = gateway.receipts()
        elif args.command == "handoff":
            checkouts = dict(value.split("=", 1) for value in args.checkout)
            state = harness.status(args.run_id)
            claim = harness._claim(
                args.run_id, state["execution"], False, False, preview=True
            )
            requests = [] if claim is None else claim[2]
            result = {"status": "manual_handoff", "tasks": []}
            for request in requests:
                checkout = checkouts.get(request["stage"])
                if not checkout:
                    raise HarnessError("provide a checkout for the selected stage")
                prompt, schema, skill_digest = handoff(checkout, request)
                result["tasks"].append(
                    {
                        "prompt": prompt,
                        "output_schema": schema,
                        "skill_document_digest": skill_digest,
                        "input_digest": digest(request),
                    }
                )
        else:
            result = harness.status(args.run_id)
            adapter = FixtureAdapter()
            if result["execution"] == "model":
                if not args.model or args.timeout <= 0:
                    raise HarnessError(
                        "model mode requires --model and a positive timeout"
                    )
                checkouts = dict(value.split("=", 1) for value in args.checkout)
                adapter = CodexAdapter(
                    checkouts, model=args.model, timeout=args.timeout
                )
            if result["execution"] == "handoff":
                if not args.results or args.command != "step":
                    raise HarnessError(
                        "handoff mode imports one stage with step --results"
                    )
                adapter = HandoffAdapter(input_json(args.results))
            limit = len(result["tasks"]) if args.command == "resume" else 1
            for index in range(limit):
                previous = result
                result = harness.step(
                    args.run_id,
                    adapter,
                    retry=args.retry and index == 0,
                    recover=args.recover and index == 0,
                )
                if result == previous or all(
                    task["status"] == "succeeded" for task in result["tasks"]
                ):
                    break
        print(json.dumps(result, ensure_ascii=True, indent=2))
        if args.command == "resume" and any(
            t["status"] == "blocked" for t in result["tasks"]
        ):
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
