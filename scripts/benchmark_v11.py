"""Structural A/B/C benchmark for V1.1.

A (single generic agent) and B (five skills copied by hand) are deterministic
proxies, not model runs. C is the orchestrated harness. The report separates
structure, evidence traceability and business outcomes so a structural score is
never presented as commercial quality.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.adapters import FixtureAdapter  # noqa: E402
from harness.orchestrator import Harness  # noqa: E402
from harness.package import _all_actions, markdown, snapshot  # noqa: E402
from harness.registry import ROLES  # noqa: E402

MODES = ("generic_single_agent", "manual_five_skills", "harness_orchestrated")
STAGES = list(ROLES)


class OneShotAdapter(FixtureAdapter):
    """Prose-only proxy for one general agent that plans the whole launch."""

    def execute(self, request):
        context = request["context"]
        if request["stage"] == "strategy":
            return {
                "recommendation": (
                    f"Launch {context['product']} to {context['audience']} and measure traction."
                )
            }
        kind = request["artifact_kind"]
        product = context.get("product", "the product")
        return {
            "kind": kind,
            "markdown": (
                f"# {kind} for {product}\n\n"
                "Run a small launch, publish content, contact prospects and review results weekly."
            ),
        }


class ManualHandoffAdapter(FixtureAdapter):
    """Proxy for copying drafts between skills without structured handoffs."""

    def execute(self, request):
        stripped = {key: value for key, value in request.items() if key not in {"handoffs", "decision"}}
        return super().execute(stripped)


def _run(values, case_id, run_id, stages, adapter):
    with TemporaryDirectory() as folder:
        harness = Harness(Path(folder) / "bench.sqlite")
        try:
            harness.initialize(
                {"schema_version": 1, "project_id": case_id, "values": deepcopy(values)}
            )
            harness.start(run_id, stages=stages)
            state = None
            for _ in range(10):
                state = harness.step(run_id, adapter)
                open_tasks = [task for task in state["tasks"] if task["status"] in {"pending", "queued"}]
                if not open_tasks:
                    break
            return state
        finally:
            harness.close()


def _measure(states):
    artifacts = 0
    actions = 0
    complete = 0
    quality = []
    export_bytes = 0
    failures = 0
    decision_ready = 0
    external = 0
    for state in states:
        package = snapshot(state, [])
        rows = _all_actions(package)
        artifacts += len(package["artifacts"])
        actions += len(rows)
        complete += sum(
            1
            for _, action in rows
            if all(
                action.get(key)
                for key in ("owner_role", "prerequisites", "resources", "metric", "next_step")
            )
        )
        quality.append(package["quality"]["score"])
        export_bytes += len(markdown(package))
        failures += sum(
            1 for item in package["quality"].get("consistency", []) if item.get("status") == "fail"
        )
        brief = package.get("decision_brief") or {}
        decision_ready += (brief.get("summary") or {}).get("decision_ready", 0)
        external += sum(
            1
            for area in brief.get("areas") or []
            for item in area.get("basis") or []
            if item.get("kind") == "external_evidence"
        )
    return {
        "artifacts": artifacts,
        "structured_actions": actions,
        "complete_actions": complete,
        "average_quality": round(sum(quality) / len(quality)) if quality else 0,
        "decision_ready_areas": round(decision_ready / len(states), 1) if states else 0,
        "external_basis_refs": round(external / len(states), 1) if states else 0,
        "consistency_failures": failures,
        "export_bytes": export_bytes,
        "model_calls": 0,
        "token_measurement": "not_measured",
        "cost_measurement": "not_incurred",
    }


def run_case(case, sources=None):
    started = perf_counter()
    values = deepcopy(case["values"])
    if sources:
        values["market_sources"] = sources
    generic = _run(values, case["id"], "generic", STAGES, OneShotAdapter())
    manual = [
        _run(values, case["id"], f"manual-{stage}", [stage], ManualHandoffAdapter())
        for stage in STAGES
    ]
    orchestrated = _run(values, case["id"], "harness", STAGES, FixtureAdapter())
    rows = {
        "generic_single_agent": _measure([generic]),
        "manual_five_skills": _measure(manual),
        "harness_orchestrated": _measure([orchestrated]),
    }
    for row in rows.values():
        row["wall_ms"] = round((perf_counter() - started) * 1000)
    return {
        "id": case["id"],
        "segment": case["segment"],
        "references": case.get("references", []),
        "reference_note": case.get("reference_note", ""),
        "modes": rows,
    }


def benchmark(live=False):
    cases = json.loads((ROOT / "evals/v1.1/cases.json").read_text(encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        sources = None
        if live:
            from harness.hn_research import fetch

            sources = fetch(
                {"topic": "market", "term": case.get("research_term", case["values"]["product"])[:120], "limit": 2}
            )
        rows.append(run_case(case, sources))
    return {
        "suite": "v1.1-structural-benchmark",
        "evidence_mode": "live_hn_snapshot" if live else "offline_no_sources",
        "mode_definitions": {
            "generic_single_agent": "Prose-only fixture proxy for one general agent. Not a model run.",
            "manual_five_skills": "Each skill runs in isolation without structured handoffs. Prose proxy.",
            "harness_orchestrated": "One run with decision contract, handoffs and the V1.1 package.",
        },
        "cases": rows,
        "boundary": (
            "All three modes are deterministic fixtures. They compare workflow structure, "
            "traceability and completeness only. No model, token, cost or business outcome is measured. "
            "Live HN snapshots are public discussion observations, not demand or market size."
        ),
        "real_model_execution": {"status": "not_run", "calls": 0},
        "business_outcome": "not_measured",
    }


def markdown_report(report):
    lines = [
        "# V1.1 structural GTM benchmark",
        "",
        report["boundary"],
        "",
        "| Case | Mode | Artifacts | Actions | Complete actions | Quality | Decision-ready | External refs | Consistency failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report["cases"]:
        for mode, row in case["modes"].items():
            lines.append(
                f"| {case['id']} | {mode} | {row['artifacts']} | {row['structured_actions']} | "
                f"{row['complete_actions']} | {row['average_quality']} | {row['decision_ready_areas']} | "
                f"{row['external_basis_refs']} | {row['consistency_failures']} |"
            )
    lines += ["", "Real model execution: NOT TESTED. Business outcome: not measured.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="attach live public HN snapshots")
    args = parser.parse_args()
    report = benchmark(live=args.live)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(markdown_report(report))
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
