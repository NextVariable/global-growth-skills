from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import os
import unittest

from harness.adapters import FixtureAdapter, HandoffAdapter
from harness.contracts import HarnessError, digest
from harness.gateway import Gateway
from harness.orchestrator import Harness
from harness.research import review

PROJECT = {
    "schema_version": 1,
    "project_id": "one",
    "values": {
        "product": "Demo SaaS",
        "goal": "market fit",
        "audience": "small teams",
        "price": {"amount_minor": 1000, "currency": "USD", "unit": "month"},
        "capabilities": ["export"],
    },
}
SOURCE = {
    "id": "survey",
    "claim_key": "interest",
    "url": "https://example.org/survey",
    "observed_on": "2024-01-01",
    "valid_until": "2030-01-01",
    "kind": "observation",
    "stance": "supports",
    "excerpt": "Synthetic survey entry.",
    "confidence_basis": "Fixture only.",
}
OPERATION = {
    "id": "publish-demo",
    "project_id": "one",
    "kind": "publish",
    "target": "mock-channel",
    "payload": {"text": "Review draft"},
}


class SharedTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.h = Harness(Path(temp.name) / "work.sqlite")
        self.addCleanup(self.h.close)
        self.h.initialize(copy.deepcopy(PROJECT))


@unittest.skipUnless(hasattr(os, "getuid"), "requires local POSIX operator identity")
class GatewayTests(SharedTests):
    def setUp(self):
        super().setUp()
        self.now = 100
        self.gateway = Gateway(self.h, clock=lambda: self.now)

    def test_unapproved_mutated_cross_project_and_duplicate_are_denied(self):
        with self.assertRaises(HarnessError):
            self.gateway.write(OPERATION)
        self.gateway.approve(OPERATION, 10)
        for attempted in (
            {**OPERATION, "target": "changed"},
            {**OPERATION, "project_id": "two"},
        ):
            with self.assertRaises(HarnessError):
                self.gateway.write(attempted)
        self.assertEqual(self.gateway.mock.calls, 0)
        self.assertEqual(self.gateway.write(OPERATION)["executor"], "mock")
        with self.assertRaises(HarnessError):
            self.gateway.write(OPERATION)
        self.assertEqual(self.gateway.mock.calls, 1)
        self.assertEqual(
            [r["event"] for r in self.gateway.receipts()],
            ["approved", "outcome_unknown", "confirmed"],
        )

    def test_expiry_and_revocation(self):
        self.gateway.approve(OPERATION, 1)
        self.now = 101
        with self.assertRaises(HarnessError):
            self.gateway.write(OPERATION)
        other = {**OPERATION, "id": "revoked"}
        self.gateway.approve(other, 10)
        self.gateway.revoke("revoked")
        with self.assertRaises(HarnessError):
            self.gateway.write(other)
        self.assertEqual(self.gateway.mock.calls, 0)

    def test_unknown_result_is_not_retried(self):
        class Broken:
            def execute(self, operation):
                raise TimeoutError

        self.gateway.mock = Broken()
        self.gateway.approve(OPERATION, 10)
        with self.assertRaisesRegex(HarnessError, "unknown"):
            self.gateway.write(OPERATION)
        with self.assertRaisesRegex(HarnessError, "denied"):
            self.gateway.write(OPERATION)
        self.assertEqual(self.gateway.receipts()[-1]["event"], "outcome_unknown")


class ResearchTests(SharedTests):
    def test_block_stale_conflicted_and_unverified_as_citations(self):
        reject = {**SOURCE, "id": "counter", "stance": "contradicts"}
        expired = {**SOURCE, "id": "expired", "valid_until": "2024-03-01"}
        unverified = {**SOURCE, "id": "rumor", "kind": "hypothesis"}
        result = review([SOURCE, reject, expired, unverified], date(2026, 1, 1))
        self.assertEqual(result["citation_ids"], [])
        self.assertEqual(result["contradictions"], ["interest"])
        self.assertEqual(
            [i["status"] for i in result["sources"]],
            ["reviewable", "reviewable", "stale", "unverified"],
        )

    def test_unknown_citation_fails_and_no_market_output_is_marked(self):
        class Invented(FixtureAdapter):
            def execute(self, request):
                return {"recommendation": "Test", "citations": ["fake"]}

        self.h.start("run", stages=["strategy"])
        with self.assertRaises(HarnessError):
            self.h.step("run", Invented())
        state = self.h.step("run", FixtureAdapter(), retry=True)
        self.assertEqual(state["decisions"][0]["market_status"], "needs_review")
        self.assertEqual(state["decisions"][0]["citation_ids"], [])

    def test_read_allowlist_and_failure_receipt(self):
        gateway = Gateway(
            self.h,
            readers={"search": lambda query: [SOURCE], "broken": lambda query: None},
        )
        self.assertEqual(gateway.read("search", "market")[0]["id"], "survey")
        with self.assertRaises(HarnessError):
            gateway.read("broken", "market")
        with self.assertRaises(HarnessError):
            gateway.read("unknown", "market")
        self.assertEqual(
            [r["event"] for r in gateway.receipts()], ["read_confirmed", "read_failed"]
        )

    def test_restore_appends_new_version_and_marks_changed_draft(self):
        self.h.start("run", stages=["content"])
        initial = self.h.step("run", FixtureAdapter())
        self.h.update({"price": {**PROJECT["values"]["price"], "amount_minor": 2000}})
        self.h.step("run", FixtureAdapter())
        result = self.h.restore(1)
        self.assertEqual(result["revision"], 3)
        state = self.h.step("run", FixtureAdapter())
        self.assertEqual(state["artifacts"][0], initial["artifacts"][0])
        self.assertEqual(
            state["context"]["values"]["price"], PROJECT["values"]["price"]
        )

    def test_handoff_result_requires_exact_request(self):
        self.h.start("run", "handoff", stages=["strategy"])
        request = self.h._claim("run", "handoff", False, False, preview=True)[2][0]
        self.h.update({"goal": "changed"})
        adapter = HandoffAdapter(
            [{"input_digest": digest(request), "result": {"recommendation": "old"}}]
        )
        with self.assertRaises(HarnessError):
            self.h.step("run", adapter)
        self.assertEqual(self.h.status("run")["decisions"], [])
