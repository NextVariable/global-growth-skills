from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from harness.adapters import FixtureAdapter
from harness.orchestrator import Harness
from harness.contracts import digest, encode
from harness.store import DDL

PROJECT = {
    "schema_version": 1,
    "project_id": "saas",
    "values": {
        "product": "Review assistant",
        "goal": "qualified trials",
        "audience": "small teams",
        "price": {"amount_minor": 2000, "currency": "USD", "unit": "month"},
        "capabilities": ["draft reviews"],
    },
}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "app.sqlite"
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        self.h.initialize(PROJECT)

    def test_full_handoff_and_selective_invalidation(self):
        self.h.start("all", goal="完整 GTM")
        for _ in range(5):
            state = self.h.step("all", FixtureAdapter())
        self.assertTrue(all(t["status"] == "succeeded" for t in state["tasks"]))
        artifacts = {a["kind"]: a for a in state["artifacts"]}
        self.assertIn(
            artifacts["launch-plan"]["id"], artifacts["experiment-plan"]["handoff_ids"]
        )
        self.assertIn(
            artifacts["pricing"]["id"], artifacts["sales-plan"]["handoff_ids"]
        )
        self.h.update({"price": {**PROJECT["values"]["price"], "amount_minor": 2500}})
        stale = {
            a["kind"]
            for a in self.h.status("all")["artifacts"]
            if a["status"] == "stale"
        }
        self.assertEqual(stale, {"pricing", "sales-plan", "experiment-plan"})
        for _ in range(3):
            state = self.h.step("all", FixtureAdapter())
        self.assertTrue(all(t["status"] == "succeeded" for t in state["tasks"]))

    def test_goal_routes_only_launch(self):
        self.h.start("channels", goal="优化渠道获客")
        state = self.h.step("channels", FixtureAdapter())
        self.assertEqual(state["plan"], ["launch"])
        self.assertEqual([item["kind"] for item in state["artifacts"]], ["launch-plan"])
        self.assertEqual(state["decisions"], [])

    def test_migrates_v1_and_preserves_saved_checkpoint(self):
        old = self.path.parent / "old.sqlite"
        with sqlite3.connect(old) as db:
            db.executescript(DDL)
            db.execute("INSERT INTO project VALUES ('old', 1)")
            db.execute("INSERT INTO runs VALUES ('old', '{}', 'fixture', NULL)")
            db.execute("INSERT INTO tasks VALUES ('old','strategy','queued',0,NULL)")
            db.execute("INSERT INTO tasks VALUES ('old','content','pending',0,NULL)")
            for field, value in PROJECT["values"].items():
                evidence = {
                    "field": field,
                    "revision": 1,
                    "source": "operator_input",
                    "sha256": digest(value),
                }
                db.execute(
                    "INSERT INTO evidence VALUES (?,1,?,?)",
                    (field, encode(value), encode(evidence)),
                )
        restored = Harness(old)
        self.addCleanup(restored.close)
        self.assertEqual(restored.status("old")["workflow_version"], 1)
        self.assertEqual(len(restored.status("old")["tasks"]), 2)
