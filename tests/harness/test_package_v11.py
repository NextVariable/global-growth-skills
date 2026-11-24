from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from harness.adapters import FixtureAdapter
from harness.evidence import audit_evidence
from harness.github_research import fetch as fetch_repository
from harness.hn_research import fetch as fetch_discussion
from harness.orchestrator import Harness
from harness.package import _all_actions, markdown, snapshot
from harness.research import review

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
        self.assertIn("No mapped competitor evidence is available", text)
        self.assertIn("- Approved · budget_constraints = 0 USD", text)
        self.assertIn("No public source was captured", text)

    def test_open_evidence_keeps_decision_areas_unresolved(self):
        state = self.run_stages()
        package = snapshot(state, [])
        statuses = {row["area"]: row["status"] for row in package["decision_brief"]["areas"]}
        self.assertEqual(statuses["competitive_positioning"], "needs_evidence")
        self.assertEqual(statuses["pricing_packaging"], "needs_evidence")

    def test_signal_claims_keep_their_class_from_persistence_to_export(self):
        now = datetime.now(timezone.utc)
        repo = fetch_repository(
            {"topic": "competitor", "term": "test", "limit": 1, "repository": "example/test"},
            get=lambda _: {
                "full_name": "example/test", "private": False,
                "html_url": "https://github.com/example/test",
                "stargazers_count": 18, "forks_count": 2, "open_issues_count": 1,
            },
            clock=lambda: now,
        )[0]
        discussion = fetch_discussion(
            {"topic": "competitor", "term": "test", "limit": 1},
            get=lambda _: {"hits": [{
                "objectID": "41234567", "title": "Show HN: Synthetic meeting-note assistant",
                "url": None, "points": 18, "num_comments": 2, "created_at": now.isoformat(),
            }]},
            clock=lambda: now,
        )[0]
        sources = [repo, discussion]

        class SignalHandoff:
            execution = "handoff"

            def execute(self, request):
                return {
                    "recommendation": "Check whether an opt-in pilot is worth testing.",
                    "claims": [{
                        "source_id": row["id"], "quote": row["excerpt"],
                        "text": f"Public activity recorded for {row['id']}.",
                    } for row in sources],
                    "citations": [row["id"] for row in sources],
                }

        self.h.update({"market_sources": sources})
        self.h.start("signals", stages=["strategy"], execution="handoff")
        state = self.h.step("signals", SignalHandoff())
        stored = state["decisions"][0]["evidence_audit"]["provenance"]
        self.assertEqual(stored["external_evidence"], [])
        self.assertEqual(len(stored["external_signal"]), 2)

        # Simulate the old persisted bucket to check re-export of pre-fix runs.
        stored["external_evidence"] = [
            {**row, "category": "external_evidence"} for row in stored.pop("external_signal")
        ]
        package = json.loads(json.dumps(snapshot(state, [])))
        for groups in (
            package["provenance"],
            package["decision"]["evidence_audit"]["provenance"],
            package["claim_audit"][0]["provenance"],
        ):
            self.assertEqual(groups["external_evidence"], [])
            self.assertEqual({(row["source_id"], row["source_provider"], row["semantic_support"])
                              for row in groups["external_signal"]},
                             {(row["id"], row["capture"]["provider"], "unverified") for row in sources})
        brief = next(row for row in package["decision_brief"]["areas"]
                     if row["area"] == "competitive_positioning")
        self.assertEqual(brief["status"], "needs_evidence")
        self.assertEqual({row["ref"] for row in brief["basis"] if row["kind"] == "external_signal"},
                         {row["id"] for row in sources})
        text = markdown(package)
        competitive = text.split("## Competitive landscape", 1)[1].split("## ", 1)[0]
        for row in sources:
            self.assertIn(f"External signal `{row['id']}` · semantic support: unverified", text)
            self.assertNotIn(row["id"], competitive)

        claims = [{"source_id": repo["id"], "quote": repo["excerpt"]}]
        adoption = audit_evidence(
            review(sources), claims, [repo["id"]], "The competitor has 18 paying customers.",
            execution="handoff",
        )
        self.assertEqual(adoption["status"], "missing_claims")


if __name__ == "__main__":
    unittest.main()
