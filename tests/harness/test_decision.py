import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import decision as dc
from harness.contracts import HarnessError, ROOT, validate
from harness.orchestrator import Harness
from harness.package import markdown, snapshot

PROJECT = json.loads(
    (ROOT / "examples/harness/project.json").read_text(encoding="utf-8")
)
STAGES = ("strategy", "content", "launch", "sales", "experiments")

CONTRACT = {
    "objective": {"state": "decided", "value": "Validate demand"},
    "primary_metric": {
        "state": "decided",
        "value": "qualified independent completions",
    },
    "metric_definition": {
        "state": "decided",
        "value": "A distinct person from a distinct project who completes the setup without guidance",
    },
    "unit": {"state": "decided", "value": "participant"},
    "target_value": {"state": "decided", "value": 2, "unit": "participant"},
    "comparator": {"state": "decided", "value": "at_least"},
    "sample_size": {"state": "decided", "value": 2, "unit": "participant"},
    "independence_conditions": {
        "state": "decided",
        "values": ["different project", "no shared operator"],
    },
    "observation_window": {"state": "decided", "value": 14, "unit": "days"},
    "budget_constraints": {
        "state": "decided",
        "amount_minor": 0,
        "currency": "USD",
        "unit": "total",
    },
}


def scripted(**changes):
    """A five-stage adapter that copies the contract unless a stage is mutated."""

    class Adapter:
        execution = "handoff"

        def execute(self, request):
            stage = request["stage"]
            if stage == "strategy":
                return {
                    "recommendation": "Validate two independent completions.",
                    "contract": copy.deepcopy(CONTRACT),
                    "claims": [],
                    "assumptions": [],
                }
            kind = request["artifact_kind"]
            if kind in {"pricing", "capabilities"}:
                return {"kind": kind, "markdown": f"# {kind}", "claims": []}
            declared = dc.declaration(request["decision"]["contract"])
            mutate = changes.get(kind) or changes.get(stage)
            if mutate:
                mutate(declared)
            return {
                "kind": kind,
                "markdown": f"# {kind}\n\nTwo independent participants over 14 days.",
                "constraint_refs": declared,
                "claims": [],
            }

    return Adapter()


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.sqlite"
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        if not hasattr(os, "geteuid"):
            fixture_identity = patch.object(Harness, "operator_identity", return_value="posix-uid:1000")
            fixture_identity.start()
            self.addCleanup(fixture_identity.stop)
        self.h.initialize(copy.deepcopy(PROJECT))
        self.h.start("run", "handoff", stages=list(STAGES))

    def contract(self):
        return self.h.status("run")["decisions"][-1]["contract"]

    def approve_seed(self):
        self.h.step("run", scripted())
        self.h.revise_decision("run", CONTRACT, reason="fixture approval", expected_revision=1)

    def test_contract_starts_pending_with_typed_constraints(self):
        self.h.step("run", scripted())
        contract = self.contract()
        self.assertEqual(contract["decision_revision"], 1)
        self.assertEqual(contract["approval_status"], "pending")
        self.assertEqual(contract["change_initiator"], "model")
        self.assertEqual(contract["primary_metric"]["value"], "qualified independent completions")
        self.assertEqual(contract["sample_size"], {"state": "proposed", "value": 2, "unit": "participant"})
        self.assertEqual(contract["observation_window"]["value"], 14)
        validate("decision-contract", contract)

    def test_unknown_values_are_not_invented(self):
        draft = {key: {"state": "unknown"} for key in dc.FIELDS}
        contract = dc.build(
            draft,
            "dec-0123456789abcdef",
            {"goal": "Validate demand"},
            [],
            [],
        )
        self.assertEqual(contract["target_value"], {"state": "unknown"})
        declared = dc.declaration(contract)
        self.assertEqual(set(declared["constraints"]), {"objective"})
        self.assertEqual(
            dc.check(contract, declared)["status"],
            "consistent",
        )
        invented = copy.deepcopy(declared)
        invented["constraints"]["sample_size"] = {"state": "decided", "value": 2}
        outcome = dc.check(contract, invented)
        self.assertEqual(outcome["status"], "drifted")
        self.assertEqual(outcome["drift"][0]["field"], "sample_size")
        self.assertEqual(outcome["drift"][0]["kind"], "fabricated")

    def test_acquisition_cannot_change_two_people_to_three(self):
        self.approve_seed()
        self.h.step("run", scripted())

        def to_three(declared):
            declared["constraints"]["sample_size"] = {
                "state": "decided",
                "value": 3,
                "unit": "participant",
            }

        with self.assertRaisesRegex(HarnessError, "attempt failed"):
            self.h.step("run", scripted(**{"launch-plan": to_three}))
        status = self.h.status("run")
        launch = next(task for task in status["tasks"] if task["stage"] == "launch")
        self.assertEqual(launch["status"], "failed")
        self.assertIn("sample_size changed", launch["detail"])
        self.assertFalse(
            any(a["kind"] == "launch-plan" and a["status"] == "draft" for a in status["artifacts"])
        )
        self.assertEqual(self.contract()["sample_size"]["value"], 2)

    def test_experiments_cannot_assert_an_unapproved_sixty_percent_standard(self):
        self.approve_seed()
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        self.h.step("run", scripted())

        def to_sixty(declared):
            declared["constraints"]["target_value"] = {
                "state": "decided",
                "value": 60,
                "unit": "percent",
            }

        with self.assertRaises(HarnessError):
            self.h.step("run", scripted(**{"experiment-plan": to_sixty}))
        failure = next(
            task for task in self.h.status("run")["tasks"] if task["stage"] == "experiments"
        )
        self.assertEqual(failure["status"], "failed")
        self.assertIn("target_value changed", failure["detail"])
        self.assertEqual(self.contract()["target_value"]["value"], 2)

    def test_decimal_target_value_is_a_decided_threshold(self):
        draft = copy.deepcopy(CONTRACT)
        draft["target_value"] = {"state": "decided", "value": 60.0, "unit": "percent"}
        contract = dc.build(draft, "dec-0123456789abcdef", {"goal": "x"})
        contract = dc.revise(contract, draft, reason="fixture approval", actor="posix-uid:1000")
        self.assertEqual(
            contract["target_value"],
            {"state": "decided", "value": 60.0, "unit": "percent"},
        )
        validate("decision-contract", contract)
        declared = dc.declaration(contract)
        self.assertEqual(dc.check(contract, declared)["status"], "consistent")
        declared["constraints"]["target_value"] = {
            "state": "decided",
            "value": 0.6,
            "unit": "percent",
        }
        outcome = dc.check(contract, declared)
        self.assertEqual(outcome["status"], "drifted")
        self.assertEqual(outcome["drift"][0]["field"], "target_value")

    def test_sample_size_must_stay_an_integer(self):
        draft = copy.deepcopy(CONTRACT)
        draft["sample_size"] = {"state": "decided", "value": 2.5, "unit": "participant"}
        with self.assertRaises(HarnessError):
            dc.build(draft, "dec-0123456789abcdef", {"goal": "x"})

    def test_same_number_with_a_different_unit_is_drift(self):
        contract = dc.build(
            copy.deepcopy(CONTRACT), "dec-0123456789abcdef", {"goal": "x"}
        )
        contract = dc.revise(contract, CONTRACT, reason="fixture approval", actor="posix-uid:1000")
        declared = dc.declaration(contract)
        declared["constraints"]["target_value"] = {
            "state": "decided",
            "value": 2,
            "unit": "team",
        }
        outcome = dc.check(contract, declared)
        self.assertEqual(outcome["status"], "drifted")
        self.assertEqual(outcome["drift"][0]["kind"], "changed")
        self.assertEqual(outcome["drift"][0]["expected"]["unit"], "participant")

    def test_budget_window_and_deleted_independence_are_drift(self):
        contract = dc.build(
            copy.deepcopy(CONTRACT), "dec-0123456789abcdef", {"goal": "x"}
        )
        contract = dc.revise(contract, CONTRACT, reason="fixture approval", actor="posix-uid:1000")
        declared = dc.declaration(contract)
        del declared["constraints"]["independence_conditions"]
        declared["constraints"]["budget_constraints"] = {
            "state": "decided",
            "amount_minor": 100,
            "currency": "EUR",
            "unit": "total",
        }
        declared["constraints"]["observation_window"] = {
            "state": "decided",
            "value": 7,
            "unit": "days",
        }
        fields = {item["field"]: item["kind"] for item in dc.check(contract, declared)["drift"]}
        self.assertEqual(fields["independence_conditions"], "omitted")
        self.assertEqual(fields["budget_constraints"], "changed")
        self.assertEqual(fields["observation_window"], "changed")

    def test_same_metric_name_with_a_different_denominator_is_drift(self):
        contract = dc.build(
            copy.deepcopy(CONTRACT), "dec-0123456789abcdef", {"goal": "x"}
        )
        contract = dc.revise(contract, CONTRACT, reason="fixture approval", actor="posix-uid:1000")
        declared = dc.declaration(contract)
        declared["constraints"]["metric_definition"] = {
            "state": "decided",
            "value": "A distinct person from any project who starts the setup",
        }
        outcome = dc.check(contract, declared)
        self.assertEqual(outcome["status"], "drifted")
        self.assertEqual(outcome["drift"][0]["field"], "metric_definition")

    def test_reasoned_proposal_is_kept_but_never_replaces_the_contract(self):
        def propose(declared):
            declared["proposals"] = [
                {
                    "field": "sample_size",
                    "reason": "A larger pilot would reduce variance.",
                    "value": {"state": "proposed", "value": 4, "unit": "participant"},
                }
            ]

        self.approve_seed()
        self.h.step("run", scripted())
        result = self.h.step(
            "run", scripted(**{"launch-plan": propose})
        )
        launch = next(a for a in result["artifacts"] if a["kind"] == "launch-plan")
        self.assertEqual(launch["constraint_check"]["status"], "proposal_only")
        self.assertEqual(launch["constraint_check"]["proposals"][0]["field"], "sample_size")
        self.assertEqual(self.contract()["sample_size"]["value"], 2)

    def test_model_cannot_self_approve_or_invent_a_proposal_reason(self):
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        for proposal in (
            {"field": "sample_size", "value": {"state": "proposed", "value": 3}},
            {
                "field": "sample_size",
                "reason": "raised by model",
                "approved": True,
                "value": {"state": "proposed", "value": 3},
            },
        ):
            result = {
                "kind": "launch-plan",
                "markdown": "# launch",
                "constraint_refs": {
                    **dc.declaration(self.contract()),
                    "proposals": [proposal],
                },
            }
            with self.subTest(proposal=proposal):
                with self.assertRaises(HarnessError):
                    validate("content-result", result)

    def test_strategy_cannot_declare_itself_approved(self):
        draft = copy.deepcopy(CONTRACT)
        draft["approval_status"] = "approved"
        with self.assertRaises(HarnessError):
            validate(
                "strategy-result",
                {"recommendation": "x", "contract": draft},
            )

    def test_revision_preserves_history_and_invalidates_bound_drafts(self):
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        before = self.h.status("run")
        kept = {a["kind"]: a["id"] for a in before["artifacts"] if a["kind"] in {"pricing", "capabilities"}}
        result = self.h.revise_decision(
            "run",
            {
                "sample_size": {
                    "state": "decided",
                    "value": 3,
                    "unit": "participant",
                }
            },
            reason="Operator approved a wider pilot",
        )
        self.assertEqual(result["decision_revision"], 2)
        status = self.h.status("run")
        revisions = [item["contract"]["decision_revision"] for item in status["decisions"]]
        self.assertEqual(revisions, [1, 2])
        self.assertEqual(status["decisions"][1]["contract"]["approval_status"], "approved")
        self.assertEqual(status["decisions"][1]["contract"]["change_reason"], "Operator approved a wider pilot")
        self.assertEqual(
            status["decisions"][1]["contract"]["approved_by"], self.h.operator_identity()
        )
        self.assertEqual(
            status["decisions"][1]["operator_approval"]["principal"], self.h.operator_identity()
        )
        self.assertEqual(status["decisions"][1]["contract"]["change_initiator"], "human")
        active = {a["kind"]: a for a in status["artifacts"] if a["status"] == "draft"}
        self.assertEqual(set(active), {"pricing", "capabilities"})
        self.assertEqual(active["pricing"]["id"], kept["pricing"])
        self.assertEqual(active["capabilities"]["id"], kept["capabilities"])
        self.assertIn("queued", [t["status"] for t in status["tasks"]])

    def test_stale_declaration_is_refused(self):
        self.h.step("run", scripted())
        old = self.contract()
        old_declaration = dc.declaration(old)
        self.h.revise_decision(
            "run",
            {"sample_size": {"state": "decided", "value": 3, "unit": "participant"}},
            reason="wider pilot",
        )
        new = self.contract()
        outcome = dc.check(new, old_declaration)
        self.assertEqual(outcome["status"], "stale_version")
        self.assertEqual(outcome["drift"][0]["kind"], "stale")

    def test_reasoned_but_unapproved_change_is_still_drift(self):
        contract = dc.build(
            copy.deepcopy(CONTRACT), "dec-0123456789abcdef", {"goal": "x"}
        )
        declared = dc.declaration(contract)
        declared["constraints"]["sample_size"] = {
            "state": "decided",
            "value": 3,
            "unit": "participant",
            "reason": "A larger pilot would reduce variance.",
        }
        outcome = dc.check(contract, declared)
        self.assertEqual(outcome["status"], "drifted")
        self.assertEqual(outcome["drift"][0]["field"], "sample_size")

    def test_approved_revision_propagates_to_rebuilt_drafts(self):
        for _ in range(4):
            self.h.step("run", scripted())
        result = self.h.revise_decision(
            "run",
            {"sample_size": {"state": "decided", "value": 3, "unit": "participant"}},
            reason="Operator approved a wider pilot",
        )
        self.assertEqual(result["decision_revision"], 2)
        for _ in range(4):
            self.h.step("run", scripted())
        status = self.h.status("run")
        revisions = [d["contract"]["decision_revision"] for d in status["decisions"]]
        self.assertEqual(revisions, [1, 2])
        active = {a["kind"]: a for a in status["artifacts"] if a["status"] == "draft"}
        for kind in ("launch-plan", "sales-plan", "experiment-plan"):
            self.assertEqual(active[kind]["constraint_check"]["status"], "consistent")
            self.assertEqual(
                active[kind]["constraint_check"]["decision_revision"], 2
            )
            self.assertEqual(active[kind]["decision_revision"], 2)
        self.assertEqual(self.contract()["sample_size"]["value"], 3)

    def test_strategy_two_then_acquisition_three_then_experiments_sixty(self):
        self.approve_seed()
        self.h.step("run", scripted())

        def to_three(declared):
            declared["constraints"]["sample_size"] = {
                "state": "decided",
                "value": 3,
                "unit": "participant",
            }

        with self.assertRaises(HarnessError):
            self.h.step("run", scripted(**{"launch-plan": to_three}))
        status = self.h.status("run")
        self.assertEqual(status["decisions"][-1]["contract"]["sample_size"]["value"], 2)
        self.assertEqual(
            status["decisions"][-1]["contract"]["target_value"]["value"], 2
        )
        # A conforming retry still carries the original two-person standard.
        self.h.step("run", scripted(), retry=True)
        self.h.step("run", scripted())

        def to_sixty(declared):
            declared["constraints"]["target_value"] = {
                "state": "decided",
                "value": 60.0,
                "unit": "percent",
            }

        with self.assertRaises(HarnessError):
            self.h.step("run", scripted(**{"experiment-plan": to_sixty}))
        status = self.h.status("run")
        self.assertEqual(status["decisions"][-1]["contract"]["sample_size"]["value"], 2)
        self.assertEqual(
            status["decisions"][-1]["contract"]["target_value"]["value"], 2
        )

    def test_downstream_cannot_reuse_a_superseded_revision(self):
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        superseded = dc.declaration(self.contract())
        self.h.revise_decision(
            "run",
            {"sample_size": {"state": "decided", "value": 3, "unit": "participant"}},
            reason="wider pilot",
        )
        self.h.step("run", scripted())

        class Stale:
            execution = "handoff"

            def execute(self, request):
                return {
                    "kind": request["artifact_kind"],
                    "markdown": "# launch",
                    "constraint_refs": copy.deepcopy(superseded),
                    "claims": [],
                }

        with self.assertRaises(HarnessError):
            self.h.step("run", Stale())
        launch = next(
            task for task in self.h.status("run")["tasks"] if task["stage"] == "launch"
        )
        self.assertEqual(launch["status"], "failed")
        self.assertIn("stale_version", launch["detail"])

    def test_invalid_runtime_slot_leaves_retryable_failure(self):
        adapter = scripted()
        execute = adapter.execute

        def invalid(request):
            result = execute(request)
            result["contract"]["comparator"]["value"] = "not-a-comparator"
            return result

        adapter.execute = invalid
        with self.assertRaisesRegex(HarnessError, "attempt failed"):
            self.h.step("run", adapter)
        self.assertEqual(self.h.status("run")["tasks"][0]["status"], "failed")
        self.assertEqual(self.h.step("run", scripted(), retry=True)["tasks"][0]["status"], "succeeded")

    def test_matching_refs_with_conflicting_prose_require_independent_review(self):
        self.approve_seed()
        adapter = scripted()
        execute = adapter.execute

        def conflicting(request):
            result = execute(request)
            if request.get("artifact_kind") == "launch-plan":
                result["markdown"] = "Proceed only if 3 people finish and conversion reaches 60%."
            return result

        adapter.execute = conflicting
        for _ in range(4):
            state = self.h.step("run", adapter)
        launch = next(a for a in state["artifacts"] if a["kind"] == "launch-plan")
        self.assertEqual(launch["constraint_check"]["status"], "consistent")
        package = snapshot(state, [])
        self.assertEqual(package["status"], "needs_decision_review")
        self.assertIn({"kind": "launch-plan", "id": launch["id"]}, package["decision_review"]["records"])
        self.assertIn("Independent decision review required", markdown(package))

    def test_review_identity_cannot_come_from_patch_or_stale_request(self):
        self.h.step("run", scripted())
        with self.assertRaises(HarnessError):
            self.h.revise_decision("run", {"approved_by": "operator"}, reason="spoof")
        with self.assertRaisesRegex(HarnessError, "revision changed"):
            self.h.revise_decision("run", CONTRACT, reason="old approval", expected_revision=99)
        self.assertEqual(self.contract()["approval_status"], "pending")

    @unittest.skipUnless(hasattr(os, "geteuid"), "POSIX database ownership boundary")
    def test_revision_refuses_shared_database(self):
        self.h.step("run", scripted())
        self.path.chmod(0o644)
        with self.assertRaisesRegex(HarnessError, "owner-only"):
            self.h.revise_decision("run", CONTRACT, reason="shared file")

    def test_unattested_legacy_approval_downgrades_without_rewriting_history(self):
        self.h.step("run", scripted())
        row = self.h.db.execute("SELECT id,data FROM decisions").fetchone()
        data = json.loads(row["data"])
        data["contract"] = dc.revise(data["contract"], CONTRACT, reason="legacy", actor="operator")
        self.h.db.execute("UPDATE decisions SET data=? WHERE id=?", (json.dumps(data), row["id"]))
        effective = self.contract()
        self.assertEqual(effective["sample_size"]["state"], "proposed")
        self.assertEqual(effective["decision_revision"], 2)
        self.assertEqual(effective["approval_status"], "pending")
        stored = self.h.db.execute("SELECT data FROM decisions").fetchone()[0]
        self.assertEqual(json.loads(stored)["contract"]["approval_status"], "approved")

    def test_resume_uses_the_same_contract_revision(self):
        self.h.step("run", scripted())
        contract = self.contract()
        digest_before = dc.declaration(contract)
        self.h.close()
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        first = self.h._claim("run", "handoff", False, False, preview=True)
        self.assertIsNotNone(first)
        request = first[2][0]
        self.assertEqual(request["decision"]["decision_id"], contract["decision_id"])
        self.assertEqual(request["decision"]["decision_revision"], 1)
        self.assertEqual(request["decision"]["contract"], contract)
        self.assertEqual(dc.declaration(request["decision"]["contract"]), digest_before)

    def test_export_shows_the_contract_and_never_calls_a_proposal_approved(self):
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        self.h.step("run", scripted())
        package = snapshot(self.h.status("run"), [])
        lines = markdown(package)
        contract = self.contract()
        self.assertIn(f"Decision contract `{contract['decision_id']}`", lines)
        self.assertIn("revision 1", lines)
        self.assertIn("**sample_size**", lines)
        self.assertIn("pending", lines)


if __name__ == "__main__":
    unittest.main()
