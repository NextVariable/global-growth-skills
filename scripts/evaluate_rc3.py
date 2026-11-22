"""RC3 quality evaluation across four GTM verticals.

Fixture and reference modes are deterministic harness checks, not model quality
evidence. Model mode requires a local Codex CLI and records real calls; billing
is reported as not measured because the CLI does not expose per-call prices.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.adapters import FixtureAdapter  # noqa: E402
from harness.codex_host import CodexAdapter  # noqa: E402
from harness.contracts import HarnessError  # noqa: E402
from harness.gateway import Gateway  # noqa: E402
from harness.orchestrator import Harness  # noqa: E402
from harness.package import snapshot  # noqa: E402


class ReferenceAdapter:
    """Deterministic reference-quality deliverables; not a model or business result."""

    execution = "fixture"

    def __init__(self):
        self.last_receipt = None

    def _text(self, stage, request):
        values = request["context"]
        product = values.get("product", "the product")
        audience = values.get("audience", "the target audience")
        market = values.get("market", "the selected market")
        goal = values.get("goal", "validate demand")
        price = values.get("price", {"amount_minor": 0, "currency": "USD", "unit": "unit"})
        budget = values.get("budget", {"amount_minor": 0, "currency": "USD"})
        caps = "、".join(values.get("capabilities", [])) or "core workflow"
        assumptions = ["Willingness to pay and channel response remain unverified."]
        gaps = []
        if stage == "strategy":
            return {
                "recommendation": (
                    f"Enter {market} with {product} for {audience}. Constraint: budget "
                    f"{budget['amount_minor']} {budget['currency']}. Assumption: willingness to pay "
                    f"is unverified. Decision: run a focused pilot before scaling."
                ),
                "citations": [],
                "claims": [],
                "assumptions": assumptions,
                "evidence_gaps": gaps,
            }
        markdown = {
            "positioning": (
                f"{product} helps {audience} achieve {goal}. Value: one measurable workflow "
                f"instead of tool sprawl. CTA: start a paid pilot."
            ),
            "pricing": (
                f"Price {price['currency']} {price['amount_minor'] / 100:.2f} per {price['unit']}. "
                f"Assumption: the first 10 {audience} accept this price."
            ),
            "capabilities": f"Supports {caps} in one reviewable workflow.",
            "launch-plan": (
                f"Channel: {audience} communities and partner newsletters. Owner: growth lead. "
                f"Metric: 10 qualified {audience} within 30 days. Budget {budget['amount_minor']} "
                f"{budget['currency']}. Qualified pipe = signups with profile / visitors."
            ),
            "sales-plan": (
                f"Discovery with {audience}: confirm current workflow and cost. Activation: first "
                f"completed review. Retention: renewal at 90 days. 30-day sales window. "
                f"Activation rate = activated accounts / eligible accounts. Budget "
                f"{budget['amount_minor']} {budget['currency']}."
            ),
            "experiment-plan": (
                f"Primary metric for {audience}: activation rate. Denominator: eligible accounts. "
                f"Guardrail: refund rate under 5%. Decision rule: ship above 20% else stop. "
                f"14-day window. Activation rate = activated accounts / eligible accounts. Budget "
                f"{budget['amount_minor']} {budget['currency']}."
            ),
        }[request["artifact_kind"]]
        return {
            "kind": request["artifact_kind"],
            "markdown": markdown,
            "claims": [],
            "assumptions": assumptions,
            "evidence_gaps": gaps,
        }

    def execute(self, request):
        self.last_receipt = None
        return self._text(request["stage"], request)


def load_cases():
    return json.loads((ROOT / "evals/rc3/tasks.json").read_text(encoding="utf-8"))["cases"]


def run_case(case, mode, checkouts, model):
    with tempfile.TemporaryDirectory(prefix="rc3-eval-") as tmp:
        harness = Harness(Path(tmp) / "eval.sqlite")
        try:
            harness.initialize(
                {
                    "schema_version": 1,
                    "project_id": case["id"],
                    "values": case["values"],
                }
            )
            execution = "model" if mode == "model" else "fixture"
            harness.start(case["id"], execution)
            adapter = (
                CodexAdapter(checkouts=checkouts, model=model)
                if mode == "model"
                else ReferenceAdapter()
                if mode == "reference"
                else FixtureAdapter()
            )
            failures = []
            for stage in harness.status(case["id"])["plan"]:
                try:
                    harness.step(case["id"], adapter)
                except HarnessError as exc:
                    failures.append({"stage": stage, "error": str(exc)})
            package = snapshot(harness.status(case["id"]), Gateway(harness).receipts())
            receipts = [
                attempt["receipt"]
                for attempt in package["attempts"]
                if attempt.get("receipt")
            ]
            return {
                "id": case["id"],
                "vertical": case["vertical"],
                "status": package["status"],
                "completion": round(
                    sum(task["status"] == "succeeded" for task in package["tasks"])
                    / len(package["tasks"]),
                    3,
                ),
                "quality": package["quality"],
                "failures": failures,
                "model_calls": sum(receipt.get("calls") or 0 for receipt in receipts),
                "tokens": [
                    receipt.get("tokens") for receipt in receipts if receipt.get("tokens")
                ],
                "evidence_class": "real_model" if mode == "model" else "deterministic_fixture",
                "business_outcome": "not_measured",
            }
        finally:
            harness.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "reference", "model", "all"), default="fixture")
    parser.add_argument("--model", help="Codex model name; required for --mode model")
    parser.add_argument("--checkouts", help="directory with per-stage Skill checkouts")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    if args.mode == "model":
        if not args.model:
            raise SystemExit("--model is required for real model evaluation")
        if not shutil.which("codex"):
            raise SystemExit("Codex CLI is not installed; refusing to fabricate model results")
        if not args.checkouts:
            raise SystemExit("--checkouts is required for real model evaluation")
        checkouts = {
            stage: Path(args.checkouts) / stage
            for stage in ("strategy", "content", "launch", "sales", "experiments")
        }
        missing = [str(path) for path in checkouts.values() if not path.is_dir()]
        if missing:
            raise SystemExit("missing Skill checkouts: " + ", ".join(missing))
    else:
        checkouts = {}

    modes = ("fixture", "reference") if args.mode == "all" else (args.mode,)
    results = []
    for mode in modes:
        for case in load_cases():
            try:
                results.append({"mode": mode, **run_case(case, mode, checkouts, args.model)})
            except Exception as exc:  # one case must not hide the rest of the suite
                results.append(
                    {
                        "mode": mode,
                        "id": case["id"],
                        "vertical": case["vertical"],
                        "status": "error",
                        "completion": 0.0,
                        "quality": {"status": "fail", "score": 0, "items": []},
                        "failures": [{"stage": "case", "error": f"{type(exc).__name__}: {exc}"}],
                        "model_calls": 0,
                        "tokens": [],
                        "evidence_class": "real_model" if mode == "model" else "deterministic_fixture",
                        "business_outcome": "not_measured",
                    }
                )

    scores = [item["quality"]["score"] for item in results]
    report = {
        "suite": "rc3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "modes": list(modes),
        "cases": results,
        "summary": {
            "case_runs": len(results),
            "completion_rate": round(
                sum(item["completion"] for item in results) / len(results), 3
            ),
            "average_quality": round(statistics.mean(scores), 1) if scores else 0,
            "error_cases": sum(1 for item in results if item["status"] == "error"),
            "stage_failures": sum(len(item["failures"]) for item in results),
            "quality_by_mode": {
                mode: round(
                    statistics.mean(
                        item["quality"]["score"] for item in results if item["mode"] == mode
                    ),
                    1,
                )
                for mode in modes
            },
            "real_model_execution": {
                "status": "measured" if args.mode == "model" else "not_run",
                "calls": sum(
                    item["model_calls"] for item in results if item["mode"] == "model"
                ),
            },
            "cost": {
                "status": "not_incurred"
                if args.mode != "model"
                else "not_measured",
                "reason": "Deterministic modes make no model calls."
                if args.mode != "model"
                else "Codex CLI receipts expose tokens, not billing amounts.",
            },
            "business_outcome": "not_measured",
            "evidence_boundary": (
                "Fixture and reference modes verify harness structure and the quality rubric. "
                "They are not model quality or business-outcome evidence."
            ),
        },
    }
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
