"""Run the optional two-stage paired Codex evaluation on the public product case."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.codex_host import CodexAdapter
from harness.contracts import HarnessError, ROOT, digest, validate
from harness.orchestrator import Harness, STRATEGY_FIELDS
from harness.registry import skill_registry
from harness.research import review, source_dependencies


def baseline(adapter, project, result):
    """Replay an explicit handoff field selection without the workflow store."""
    roles = skill_registry()
    values = project["values"]
    for stage, fields in (
        ("strategy", STRATEGY_FIELDS),
        ("launch", (*STRATEGY_FIELDS, "capabilities")),
    ):
        fields = (*fields, *(key for key in ("market", "budget") if key in values))
        market = review(values.get("market_sources", []))
        request = {
            "project_id": project["project_id"],
            "run_id": "manual-replay",
            "stage": stage,
            "skill": roles[stage],
            "tool_policy": "deny_external_writes",
            "context": {key: values[key] for key in fields},
            "evidence": [
                {
                    "field": key,
                    "revision": 1,
                    "source": "operator_input",
                    "sha256": digest(values[key]),
                }
                for key in fields
            ],
            "market_review": market,
        }
        if stage == "launch":
            request.update(
                artifact_kind="launch-plan",
                handoffs=[
                    {
                        "id": 1,
                        "kind": "manual-strategy-note",
                        "markdown": "Provisional strategy and evidence limitations:\n\n"
                        + result["steps"][0]["output"]["recommendation"],
                    }
                ],
            )
        row = {"stage": stage, "request": request}
        result["steps"].append(row)
        try:
            row["output"] = validate(
                "strategy-result" if stage == "strategy" else "content-result",
                adapter.execute(request),
            )
            source_dependencies(
                market, row["output"].get("claims", []), row["output"].get("citations", [])
            )
            if stage == "launch" and row["output"]["kind"] != "launch-plan":
                raise HarnessError("unexpected artifact kind")
        finally:
            row["receipt"] = adapter.last_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=("manual-replay", "harness"))
    parser.add_argument("--strategy-checkout", required=True)
    parser.add_argument("--launch-checkout", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--project", type=Path, default=ROOT / "evals/v1/public-project.json")
    parser.add_argument(
        "--evidence",
        type=Path,
        action="append",
        default=[],
        help="Saved research result from the same public case",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    target = args.output_dir.resolve()
    if target.is_relative_to(ROOT):
        parser.error("use a temporary output directory outside the repository")
    target.mkdir()
    project = json.loads(args.project.read_text(encoding="utf-8"))
    if args.evidence:
        sources = {
            row["id"]: row
            for path in args.evidence
            for row in json.loads(path.read_text(encoding="utf-8"))["retrieved"]
        }
        project["values"]["market_sources"] = list(sources.values())
    validate("project-input", project)
    adapter = CodexAdapter(
        {"strategy": args.strategy_checkout, "launch": args.launch_checkout},
        model=args.model,
    )
    result = {
        "arm": args.arm,
        "execution": "model",
        "project": project,
        "steps": [],
        "requested_model": args.model,
        "pricing": "unknown",
        "operator_interventions": None,
        "comparison": "fixed handoff field replay; no human labor time measured",
    }
    started = time.monotonic()
    db = None
    try:
        if args.arm == "manual-replay":
            baseline(adapter, project, result)
        else:
            db = Harness(target / "project.sqlite")
            db.initialize(project)
            db.start("paired", "model", stages=["strategy", "launch"])
            for _ in range(2):
                db.step("paired", adapter)
        result["status"] = "succeeded"
        return 0
    except HarnessError as exc:
        result.update(status="failed", error=str(exc))
        return 1
    finally:
        if db is not None:
            result["state"] = db.status("paired")
            db.close()
        result["wall_ms"] = round((time.monotonic() - started) * 1000)
        (target / "run.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
