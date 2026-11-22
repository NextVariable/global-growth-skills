from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from harness.adapters import FixtureAdapter
from harness.orchestrator import Harness
from harness.package import _all_actions, markdown, snapshot

ROOT = Path(__file__).resolve().parents[2]
PROJECT = json.loads((ROOT / "evals/rc2/public-project.json").read_text(encoding="utf-8"))


class PackageV11Tests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.h = Harness(Path(folder.name) / "v11.sqlite")
        self.addCleanup(self.h.close)
        self.h.initialize(deepcopy(PROJECT))

    def run_stages(self):
        self.h.start("v11", stages=["strategy", "content", "launch"])
        state = None
        for _ in range(3):
            state = self.h.step("v11", FixtureAdapter())
        return state

    def test_package_has_executive_market_and_decision_sections(self):
        state = self.run_stages()
        package = snapshot(state, [])
        text = markdown(package)
        for heading in (
            "## Executive summary",
            "## Market and ICP research",
            "## Competitive landscape",
            "## GTM decision register",
            "## KPI and measurement framework",
            "## Action register",
            "## Evidence and decision register",
        ):
            self.assertIn(heading, text)
        self.assertEqual(package["decision_brief"]["summary"]["areas"], 9)
        self.assertEqual(len(package["decision_brief"]["areas"]), 9)

    def test_actions_are_rendered_with_owners_and_metrics(self):
        state = self.run_stages()
        package = snapshot(state, [])
        text = markdown(package)
        self.assertIn("- Owner role ·", text)
        self.assertIn("- Prerequisites ·", text)
        self.assertIn("- Metric ·", text)
        self.assertIn("- Next step ·", text)
        titles = [action["title"] for _, action in _all_actions(package)]
        self.assertIn("Confirm the ICP with five problem interviews", titles)

    def test_summary_states_evidence_limits_instead_of_fake_certainty(self):
        state = self.run_stages()
        package = snapshot(state, [])
        text = markdown(package)
        self.assertIn("No competitor source was captured", text)
        self.assertIn("- Approved · budget_constraints = 0 USD", text)
        self.assertIn("No public source was captured", text)

    def test_open_evidence_keeps_decision_areas_unresolved(self):
        state = self.run_stages()
        package = snapshot(state, [])
        statuses = {row["area"]: row["status"] for row in package["decision_brief"]["areas"]}
        self.assertEqual(statuses["competitive_positioning"], "needs_evidence")
        self.assertEqual(statuses["pricing_packaging"], "needs_evidence")


if __name__ == "__main__":
    unittest.main()
