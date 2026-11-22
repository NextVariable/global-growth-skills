"""Run the GTM Harness from the repository root."""

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from . import __version__
from .adapters import FixtureAdapter, HandoffAdapter
from .codex_host import CodexAdapter, handoff
from .contracts import HarnessError, digest
from .gateway import Gateway
from .orchestrator import Harness
from .package import markdown, snapshot
from .pins import prepare_pins
from .registry import ROLES
from .web_research import PROVIDER as WEB_PROVIDER


def input_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def doctor(db):
    import jsonschema

    checks = [
        {
            "check": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": sys.version.split()[0],
        },
        {"check": "jsonschema", "ok": True, "detail": jsonschema.__version__},
    ]
    target = Path(db).expanduser().resolve()
    checks.append(
        {
            "check": "database_path",
            "ok": not str(target).startswith(str(Path.cwd().resolve()) + "/")
            and target.parent.is_dir(),
            "detail": str(target),
        }
    )
    codex = shutil.which("codex")
    checks.append(
        {
            "check": "codex_cli",
            "ok": bool(codex),
            "detail": codex or "not installed; fixture and handoff modes still work",
        }
    )
    return {
        "version": __version__,
        "ok": all(check["ok"] for check in checks if check["check"] != "codex_cli"),
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--db", required=True, help="SQLite file outside this repository")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("project")
    commands.add_parser("prepare-pins").add_argument("directory")
    commands.add_parser("change").add_argument("patch")
    commands.add_parser("restore").add_argument("revision", type=int)
    approve = commands.add_parser("approve-mock")
    approve.add_argument("operation")
    approve.add_argument("--ttl", type=int, default=300)
    commands.add_parser("revoke-mock").add_argument("operation_id")
    commands.add_parser("execute-mock").add_argument("operation")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("operation")
    commands.add_parser("receipts")
    research = commands.add_parser("research", help="retrieve and store public GitHub evidence")
    research.add_argument("topic", choices=("market", "competitor", "icp", "channel"))
    research.add_argument("term", help="public search keywords; do not include private data")
    research.add_argument("--repository", help="exact public OWNER/REPO lookup")
    research.add_argument("--limit", type=int, default=3)
    web = commands.add_parser(
        "research-web", help="snapshot one public HTTPS page (no redirects, no login)"
    )
    web.add_argument("url")
    web.add_argument("--topic", choices=("market", "competitor", "icp", "channel"), required=True)
    web.add_argument("--claim-key", help="group sources that make the same assertion")
    web.add_argument("--quote", help="verbatim fragment to capture instead of the page summary")
    web.add_argument("--valid-days", type=int, default=30)
    commands.add_parser("doctor", help="check runtime, schema and CLI prerequisites")
    audit = commands.add_parser("audit", help="evidence and quality audit for one run")
    audit.add_argument("run_id")
    export = commands.add_parser("export")
    export.add_argument("run_id")
    export.add_argument("--format", choices=("json", "markdown"), default="markdown")
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
                "--checkouts-dir", type=Path, help="directory with Skill repos named by stage"
            )
            command.add_argument("--checkout", action="append", default=[], metavar="STAGE=DIR")
        if name in {"step", "resume"}:
            command.add_argument("--model")
            command.add_argument("--results")
            command.add_argument("--timeout", type=int, default=120)
            command.add_argument("--retry", action="store_true")
            command.add_argument("--recover", action="store_true")

    args = parser.parse_args()
    harness = None
    exit_code = 0
    try:
        if args.command == "prepare-pins":
            print(json.dumps(prepare_pins(args.directory), indent=2))
            return 0
        if args.command == "doctor":
            result = doctor(args.db)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 2
        if getattr(args, "checkouts_dir", None):
            args.checkout = [
                f"{stage}={args.checkouts_dir / stage}" for stage in ROLES
            ] + args.checkout
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
            harness.start(args.run_id, args.execution, stages=args.stages, goal=args.goal)
            result = harness.status(args.run_id)
        elif args.command == "status":
            result = harness.status(args.run_id)
        elif args.command in {
            "approve-mock",
            "revoke-mock",
            "execute-mock",
            "receipts",
            "research",
            "research-web",
            "prepare",
        }:
            gateway = Gateway(harness)
            if args.command == "research":
                query = {"topic": args.topic, "term": args.term, "limit": args.limit}
                if args.repository:
                    query["repository"] = args.repository
                result = gateway.research(query)
            elif args.command == "research-web":
                query = {
                    "url": args.url,
                    "topic": args.topic,
                    "valid_days": args.valid_days,
                }
                if args.claim_key:
                    query["claim_key"] = args.claim_key
                if args.quote:
                    query["quote"] = args.quote
                result = gateway.research(query, provider=WEB_PROVIDER)
            elif args.command == "prepare":
                result = gateway.prepare(input_json(args.operation))
            elif args.command == "approve-mock":
                gateway.approve(input_json(args.operation), args.ttl)
                result = {"status": "approved", "executor": "mock"}
            elif args.command == "revoke-mock":
                gateway.revoke(args.operation_id)
                result = {"status": "revoked", "executor": "mock"}
            elif args.command == "execute-mock":
                result = gateway.write(input_json(args.operation))
            else:
                result = gateway.receipts()
        elif args.command == "export":
            result = snapshot(harness.status(args.run_id), Gateway(harness).receipts())
            if args.format == "markdown":
                print(markdown(result), end="")
                return 0
        elif args.command == "audit":
            package = snapshot(harness.status(args.run_id), Gateway(harness).receipts())
            result = {
                "run_id": package["run_id"],
                "status": package["status"],
                "quality": package["quality"],
                "claim_audit": package["claim_audit"],
                "sources": [
                    {
                        key: row[key]
                        for key in (
                            "id",
                            "status",
                            "observed_on",
                            "valid_until",
                            "freshness",
                            "injection_flags",
                        )
                    }
                    for row in package["evidence_review"]["sources"]
                ],
            }
            exit_code = 2 if package["status"] == "incomplete_evidence" else 0
        elif args.command == "handoff":
            checkouts = dict(value.split("=", 1) for value in args.checkout)
            state = harness.status(args.run_id)
            claim = harness._claim(args.run_id, state["execution"], False, False, preview=True)
            requests = [] if claim is None else claim[2]
            result = {"status": "manual_handoff", "tasks": []}
            for request in requests:
                checkout = checkouts.get(request["stage"])
                if not checkout:
                    raise HarnessError("provide a checkout for the selected stage")
                prompt, schema, skill_digest, selection = handoff(checkout, request)
                result["tasks"].append(
                    {
                        "prompt": prompt,
                        "output_schema": schema,
                        "skill_document_digest": skill_digest,
                        "skill_selection": selection,
                        "prompt_bytes": len(prompt.encode("utf-8")),
                        "input_digest": digest(request),
                    }
                )
        else:
            result = harness.status(args.run_id)
            adapter = FixtureAdapter()
            if result["execution"] == "model":
                if not args.model or args.timeout <= 0:
                    raise HarnessError("model mode requires --model and a positive timeout")
                checkouts = dict(value.split("=", 1) for value in args.checkout)
                adapter = CodexAdapter(checkouts, model=args.model, timeout=args.timeout)
            if result["execution"] == "handoff":
                if not args.results or args.command != "step":
                    raise HarnessError("handoff mode imports one stage with step --results")
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
        if args.command == "resume" and any(t["status"] == "blocked" for t in result["tasks"]):
            return 2
        return exit_code
    except (HarnessError, OSError, ValueError, sqlite3.Error) as exc:
        detail = str(exc) if isinstance(exc, HarnessError) else type(exc).__name__
        parser.exit(1, f"Harness error: {detail}\n")
    finally:
        if harness is not None:
            harness.close()


if __name__ == "__main__":
    raise SystemExit(main())
