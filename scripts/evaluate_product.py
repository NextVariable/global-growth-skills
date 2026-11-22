"""Execute the RC2 representative task matrix as an offline structural evaluation."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.adapters import FixtureAdapter
from harness.orchestrator import Harness
from harness.package import snapshot

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def complete(harness, run, steps):
    for _ in range(steps):
        harness.step(run, FixtureAdapter())
    return harness.status(run)


def exercise(case, path):
    started = monotonic()
    run, expected = case["id"], case["expected"]
    if case["data"] == "public":
        project = load("evals/rc2/public-project.json")
    else:
        project = load("examples/harness/project.json")
    with closing(Harness(path)) as h:
        h.initialize(project)
        h.start(run, goal=case["goal"])
        initial = h.step(run, FixtureAdapter()) if case.get("interrupt") else None
    with closing(Harness(path)) as h:
        state = complete(h, run, len(expected))
        if initial and initial["active_decision_id"] != state["active_decision_id"]:
            raise AssertionError("checkpoint decision ID changed")
        if case.get("change"):
            updated = h.update(load("examples/harness/price-change.json"))
            ids = set(updated["stale_artifact_ids"])
            stale = sorted(a["kind"] for a in state["artifacts"] if a["id"] in ids)
            if sorted(case["expected_stale"]) != stale:
                raise AssertionError(f"unexpected invalidation: {stale}")
            state = complete(h, run, len(expected))
        package = snapshot(state, [])
        if package["scope"] != expected or package["status"] != "ready_for_internal_review":
            raise AssertionError("workflow scope or completion mismatch")
        return {
            "id": run,
            "result": "passed",
            "data": case["data"],
            "scope": expected,
            "drafts": len(package["artifacts"]),
            "review_rubric_applied": False,
            "elapsed_ms": round((monotonic() - started) * 1000),
        }


def run_matrix():
    with TemporaryDirectory(prefix="gtm-task-matrix-") as work:
        results = []
        for case in load("evals/rc2/tasks.json"):
            try:
                results.append(exercise(case, Path(work) / (case["id"] + ".sqlite")))
            except Exception as exc:
                results.append({"id": case["id"], "result": "failed", "error": str(exc)})
    return {
        "execution": "fixture",
        "model_calls": 0,
        "passed": sum(r["result"] == "passed" for r in results),
        "total": len(results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = run_matrix()
    data = json.dumps(report, indent=2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(data + "\n", encoding="utf-8")
    print(data)
    return int(report["passed"] != report["total"])


if __name__ == "__main__":
    raise SystemExit(main())
