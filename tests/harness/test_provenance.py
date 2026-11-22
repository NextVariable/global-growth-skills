"""Provenance regressions for operator inputs versus external evidence."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import decision as dc
from harness.contracts import HarnessError, ROOT, validate
from harness.evidence import audit_evidence
from harness.orchestrator import Harness
from harness.package import markdown, snapshot
from harness.research import review

PROJECT = json.loads(
    (ROOT / "examples/harness/project.json").read_text(encoding="utf-8")
)
STAGES = ("strategy", "content", "launch", "sales", "experiments")
BUDGET_ZERO = {"amount_minor": 0, "currency": "USD", "unit": "total"}
BUDGET_HUNDRED = {"amount_minor": 10000, "currency": "USD", "unit": "total"}
SOURCE = {
    "id": "survey-1",
    "claim_key": "interest",
    "url": "https://example.org/survey",
    "observed_on": "2024-01-01",
    "valid_until": "2030-01-01",
    "kind": "observation",
    "stance": "supports",
    "excerpt": "Synthetic survey entry.",
    "confidence_basis": "Fixture only.",
}
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


def approved_contract():
    contract = dc.build(
        copy.deepcopy(CONTRACT),
        "dec-0123456789abcdef",
        {"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
    )
    return dc.revise(
        contract, copy.deepcopy(CONTRACT), reason="operator approval", actor="posix-uid:1000"
    )


def audit(text, *, context=None, contract=None, sources=None, claims=None):
    return audit_evidence(
        review(copy.deepcopy(sources if sources is not None else [SOURCE])),
        claims or [],
        [],
        text,
        execution="model",
        context=context,
        contract=contract,
    )


class ProvenanceClassificationTests(unittest.TestCase):
    def test_approved_zero_budget_needs_no_external_citation(self):
        result = audit(
            "Run the pilot with a 0 USD cash budget.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
        )
        self.assertFalse(result["missing_claims"])
        self.assertEqual(result["status"], "no_claims")
        self.assertNotEqual(result["status"], "verified")
        self.assertEqual(
            result["provenance"]["unmapped_external_flags"],
            [],
        )
        self.assertEqual(
            [item["field"] for item in result["provenance"]["operator_input"]],
            ["budget"],
        )

    def test_without_operator_context_the_same_budget_stays_missing_claims(self):
        # Pre-fix behaviour: the same prose is treated as an external fact.
        result = audit("Run the pilot with a 0 USD cash budget.")
        self.assertTrue(result["missing_claims"])
        self.assertEqual(result["status"], "missing_claims")

    def test_approved_hundred_budget_needs_no_external_citation(self):
        result = audit(
            "The approved cash budget is 100 USD for the pilot.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_HUNDRED)},
        )
        self.assertFalse(result["missing_claims"])
        self.assertIn(
            "budget", [item["field"] for item in result["provenance"]["operator_input"]]
        )

    def test_approved_sample_and_window_are_operator_input(self):
        result = audit(
            "Recruit 2 independent participants and observe them over 14 days.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
            contract=approved_contract(),
        )
        self.assertFalse(result["missing_claims"])
        fields = {item["field"] for item in result["provenance"]["operator_input"]}
        self.assertIn("sample_size", fields)
        self.assertIn("target_value", fields)
        self.assertIn("observation_window", fields)

    def test_unapproved_sample_is_not_operator_input(self):
        pending = dc.build(
            copy.deepcopy(CONTRACT),
            "dec-0123456789abcdef",
            {"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
        )
        self.assertEqual(pending["approval_status"], "pending")
        result = audit(
            "Recruit 2 independent participants over 14 days.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
            contract=pending,
        )
        fields = {item["field"] for item in result["provenance"]["operator_input"]}
        self.assertNotIn("sample_size", fields)
        self.assertNotIn("observation_window", fields)

    def test_unpriced_competitor_price_still_needs_a_source(self):
        result = audit(
            "The leading competitor charges $49 per seat each month.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
        )
        self.assertTrue(result["missing_claims"])
        self.assertEqual(result["status"], "missing_claims")
        self.assertIn("price_in_prose", result["provenance"]["unmapped_external_flags"])

    def test_unverified_paying_customer_count_still_needs_a_source(self):
        result = audit(
            "20 paying customers already renew the product.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
        )
        self.assertTrue(result["missing_claims"])
        self.assertIn("adoption_count_in_prose", result["provenance"]["unmapped_external_flags"])

    def test_model_invented_success_threshold_is_not_operator_input(self):
        result = audit(
            "Require a 60% conversion increase before declaring success.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
            contract=approved_contract(),
        )
        self.assertTrue(result["missing_claims"])
        fields = {item["field"] for item in result["provenance"]["operator_input"]}
        self.assertNotIn("target_value", fields)
        self.assertIn("percentage_claim_in_prose", result["provenance"]["unmapped_external_flags"])

    def test_market_size_still_needs_a_source(self):
        result = audit(
            "The market size is $4B and grows quickly.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
        )
        self.assertTrue(result["missing_claims"])
        self.assertIn("market_size_in_prose", result["provenance"]["unmapped_external_flags"])

    def test_mapped_external_claim_is_separate_from_operator_constraints(self):
        result = audit(
            "Three participants completed the pilot, matching the external survey.",
            context={"goal": "Validate demand", "budget": copy.deepcopy(BUDGET_ZERO)},
            contract=approved_contract(),
            claims=[
                {
                    "source_id": "survey-1",
                    "quote": "Synthetic survey entry.",
                    "text": "Three participants completed a pilot.",
                }
            ],
        )
        self.assertEqual(len(result["provenance"]["external_evidence"]), 1)
        self.assertEqual(
            result["provenance"]["external_evidence"][0]["source_id"], "survey-1"
        )
        operator_fields = {
            item["field"] for item in result["provenance"]["operator_input"]
        }
        self.assertEqual(operator_fields, set())

    def test_external_suggestion_cannot_replace_the_approved_standard(self):
        contract = approved_contract()
        declared = dc.declaration(contract)
        declared["proposals"] = [
            {
                "field": "sample_size",
                "reason": "An external survey suggests three participants.",
                "value": 3,
            }
        ]
        self.assertEqual(dc.check(contract, declared)["status"], "proposal_only")
        declared["constraints"]["sample_size"] = {
            "state": "decided",
            "value": 3,
            "unit": "participant",
        }
        self.assertEqual(dc.check(contract, declared)["status"], "drifted")

    def test_model_cannot_declare_its_own_provenance(self):
        with self.assertRaises(HarnessError):
            validate(
                "strategy-result",
                {
                    "recommendation": "Validate demand.",
                    "provenance": {"operator_input": []},
                },
            )


class ProvenanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.sqlite"
        project = copy.deepcopy(PROJECT)
        project["values"]["budget"] = copy.deepcopy(BUDGET_ZERO)
        project["values"]["market_sources"] = [copy.deepcopy(SOURCE)]
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        if not hasattr(os, "geteuid"):
            fixture_identity = patch.object(
                Harness, "operator_identity", return_value="posix-uid:1000"
            )
            fixture_identity.start()
            self.addCleanup(fixture_identity.stop)
        self.h.initialize(project)
        self.h.start("run", "handoff", stages=list(STAGES))

    def adapter(self, proposal=False):
        class Adapter:
            execution = "handoff"

            def execute(self, request):
                if request["stage"] == "strategy":
                    return {
                        "recommendation": (
                            "Run a 0 USD pilot with 2 independent participants over 14 days."
                        ),
                        "contract": copy.deepcopy(CONTRACT),
                        "claims": [],
                        "assumptions": ["Founders can recruit two independent teams."],
                    }
                kind = request["artifact_kind"]
                if kind in {"pricing", "capabilities"}:
                    return {"kind": kind, "markdown": f"# {kind}", "claims": []}
                declared = dc.declaration(request["decision"]["contract"])
                if proposal and kind == "launch-plan":
                    declared["proposals"] = [
                        {
                            "field": "sample_size",
                            "reason": "A partner offered three teams.",
                            "value": 3,
                        }
                    ]
                return {
                    "kind": kind,
                    "markdown": (
                        f"# {kind}\n\nKeep the 0 USD budget, recruit 2 participants "
                        "and observe for 14 days."
                    ),
                    "constraint_refs": declared,
                    "claims": [],
                    "assumptions": ["Recruitment takes one week."],
                }

        return Adapter()

    def test_package_status_and_provenance_classes(self):
        state = self.h.step("run", self.adapter())
        strategy = state["decisions"][-1]
        self.assertFalse(strategy["evidence_audit"]["missing_claims"])
        self.assertNotEqual(strategy["evidence_audit"]["status"], "missing_claims")
        self.h.revise_decision("run", CONTRACT, reason="fixture approval", expected_revision=1)
        state = self.h.step("run", self.adapter(proposal=True))
        state = self.h.step("run", self.adapter(proposal=True))
        state = self.h.step("run", self.adapter(proposal=True))
        state = self.h.step("run", self.adapter(proposal=True))

        package = snapshot(state, [])
        self.assertNotEqual(package["status"], "incomplete_evidence")
        self.assertEqual(package["status"], "needs_decision_review")
        operator_fields = {item["field"] for item in package["provenance"]["operator_input"]}
        self.assertIn("budget", operator_fields)
        self.assertIn("sample_size", operator_fields)
        self.assertIn("observation_window", operator_fields)
        self.assertEqual(package["provenance"]["external_evidence"], [])
        self.assertTrue(package["provenance"]["inference"])
        self.assertTrue(package["provenance"]["proposal"])
        self.assertIn("0 USD", markdown(package))

    def test_evidence_change_invalidates_downstream_drafts(self):
        state = self.h.step("run", self.adapter())
        self.h.revise_decision("run", CONTRACT, reason="fixture approval", expected_revision=1)
        for _ in range(4):
            state = self.h.step("run", self.adapter())
        launch = next(a for a in state["artifacts"] if a["kind"] == "launch-plan")
        updated = self.h.update({"budget": copy.deepcopy(BUDGET_HUNDRED)})
        self.assertIn(launch["id"], updated["stale_artifact_ids"])
        stale = {a["kind"] for a in self.h.status("run")["artifacts"] if a["status"] == "stale"}
        self.assertIn("launch-plan", stale)

    def test_resume_keeps_operator_provenance(self):
        before = self.h.step("run", self.adapter())
        audit_before = before["decisions"][-1]["evidence_audit"]["provenance"]
        revision_before = before["decisions"][-1]["contract"]["decision_revision"]
        self.h.close()
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        after = self.h.status("run")
        self.assertEqual(
            after["decisions"][-1]["evidence_audit"]["provenance"], audit_before
        )
        self.assertEqual(
            after["decisions"][-1]["contract"]["decision_revision"], revision_before
        )
        self.assertIn(
            "budget",
            [item["field"] for item in audit_before["operator_input"]],
        )


if __name__ == "__main__":
    unittest.main()
