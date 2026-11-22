"""Synthetic tests for contract, atomicity, recovery and local-only execution."""

import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from harness.adapters import FixtureAdapter
from harness.contracts import HarnessError, ROOT
from harness.orchestrator import Harness

PROJECT = json.loads((ROOT / "examples/harness/project.json").read_text(encoding="utf-8"))
NEW_PRICE = {"price": {**PROJECT["values"]["price"], "amount_minor": 3000}}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "project.sqlite"
        self.h = Harness(self.path)
        self.addCleanup(self.h.close)
        self.h.initialize(copy.deepcopy(PROJECT))
        self.h.start("run")
        self.adapter = FixtureAdapter()

    def finish(self):
        self.h.step("run", self.adapter)
        return self.h.step("run", self.adapter)

    def tasks(self):
        return [task["status"] for task in self.h.status("run")["tasks"]]

    def test_strategy_queues_content_and_pins_catalog(self):
        result = self.h.step("run", self.adapter)
        self.assertEqual(self.tasks(), ["succeeded", "queued"])
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(len(result["evidence"]), 5)
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(
            result["skill_pins"]["strategy"]["revision"], catalog["skills"][0]["revision"]
        )

    def test_price_invalidates_only_pricing_and_resume_is_idempotent(self):
        before = self.finish()
        ids = {a["kind"]: a["id"] for a in before["artifacts"]}
        self.assertEqual(self.h.update(NEW_PRICE)["stale_artifact_ids"], [ids["pricing"]])
        self.assertEqual(self.h.update(NEW_PRICE), {"revision": 2, "stale_artifact_ids": []})
        self.h.start("run")
        result = self.h.step("run", self.adapter)
        self.assertEqual(result, self.h.step("run", self.adapter))
        active = {a["kind"]: a for a in result["artifacts"] if a["status"] == "draft"}
        self.assertEqual(active["positioning"]["id"], ids["positioning"])
        self.assertEqual(active["capabilities"]["id"], ids["capabilities"])
        self.assertNotEqual(active["pricing"]["id"], ids["pricing"])
        self.assertEqual(active["pricing"]["dependencies"], [{"field": "price", "revision": 2}])
        self.assertIn("3000", active["pricing"]["markdown"])
        update = self.h.update({"capabilities": []})
        self.assertEqual(update["stale_artifact_ids"], [ids["capabilities"]])
        refreshed = self.h.step("run", self.adapter)
        current = {a["kind"]: a for a in refreshed["artifacts"] if a["status"] == "draft"}
        self.assertEqual(current["positioning"], active["positioning"])
        self.assertEqual(current["pricing"], active["pricing"])
        self.assertEqual(
            current["capabilities"]["dependencies"], [{"field": "capabilities", "revision": 3}]
        )
        self.assertIn("None declared", current["capabilities"]["markdown"])

    def test_strategy_change_invalidates_dependent_positioning(self):
        old = self.finish()
        position = old["artifacts"][0]
        result = self.h.update({"audience": "partner teams"})
        self.assertEqual(result["stale_artifact_ids"], [position["id"]])
        self.assertEqual(self.tasks(), ["queued", "pending"])
        now = self.finish()
        self.assertNotEqual(old["active_decision_id"], now["active_decision_id"])
        self.assertEqual(now["artifacts"][-1]["decision_id"], now["active_decision_id"])

    def test_restart_cli_uses_saved_strategy_checkpoint(self):
        for args in (("step", "run"), ("resume", "run"), ("status", "run")):
            output = subprocess.check_output(
                [sys.executable, "-m", "harness", "--db", str(self.path), *args],
                cwd=ROOT,
                text=True,
            )
        data = json.loads(output)
        self.assertEqual([t["attempt"] for t in data["tasks"]], [1, 1])
        self.assertEqual(len(data["artifacts"]), 3)

    def test_interrupted_attempt_requires_recover(self):
        class Interrupt(FixtureAdapter):
            def execute(self, request):
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.h.step("run", Interrupt())
        h = Harness(self.path)
        self.addCleanup(h.close)
        with self.assertRaisesRegex(HarnessError, "explicit recovery"):
            h.step("run", self.adapter)
        result = h.step("run", self.adapter, recover=True)
        self.assertEqual(result["tasks"][0]["attempt"], 2)
        self.assertEqual(len(result["decisions"]), 1)

    def test_failure_leaves_no_partial_drafts_and_is_retryable(self):
        self.h.step("run", self.adapter)

        class Broken(FixtureAdapter):
            def execute(self, request):
                if request["artifact_kind"] == "pricing":
                    raise TimeoutError("private data")
                return super().execute(request)

        with self.assertRaisesRegex(HarnessError, "inspect status"):
            self.h.step("run", Broken())
        status = self.h.status("run")
        self.assertEqual(status["artifacts"], [])
        self.assertEqual(status["tasks"][1]["detail"], "TimeoutError")
        with self.assertRaisesRegex(HarnessError, "explicit retry"):
            self.h.step("run", self.adapter)
        result = self.h.step("run", self.adapter, retry=True)
        self.assertEqual(len(result["artifacts"]), 3)

    def test_change_during_execution_discards_old_result(self):
        h = Harness(self.path)
        self.addCleanup(h.close)

        class Updating(FixtureAdapter):
            def execute(self, request):
                h.update({"audience": "new segment"})
                return super().execute(request)

        with self.assertRaisesRegex(HarnessError, "superseded"):
            self.h.step("run", Updating())
        self.assertEqual(self.h.status("run")["decisions"], [])
        self.assertIn("new segment", self.finish()["decisions"][0]["recommendation"])

    def test_recovery_fences_out_old_attempt(self):
        h = Harness(self.path)
        self.addCleanup(h.close)

        class InterruptedWorker(FixtureAdapter):
            def execute(self, request):
                h.step("run", FixtureAdapter(), recover=True)
                return super().execute(request)

        with self.assertRaisesRegex(HarnessError, "superseded"):
            self.h.step("run", InterruptedWorker())
        self.assertEqual(len(self.h.status("run")["decisions"]), 1)

    def test_missing_evidence_blocks_then_resumes(self):
        h = Harness(self.path.parent / "missing.sqlite")
        self.addCleanup(h.close)
        project = copy.deepcopy(PROJECT)
        del project["values"]["price"]
        h.initialize(project)
        h.start("run")
        h.step("run", self.adapter)
        result = h.step("run", self.adapter)
        self.assertEqual(result["tasks"][1]["status"], "blocked")
        self.assertEqual(result["artifacts"], [])
        h.update(NEW_PRICE)
        self.assertEqual(len(h.step("run", self.adapter)["artifacts"]), 3)

    def test_external_action_in_result_is_rejected(self):
        self.h.step("run", self.adapter)

        class Injected(FixtureAdapter):
            def execute(self, request):
                if request["tool_policy"] != "deny_external_writes":
                    raise AssertionError("policy missing")
                return {**super().execute(request), "actions": [{"type": "publish"}]}

        with self.assertRaisesRegex(HarnessError, "attempt failed"):
            self.h.step("run", Injected())
        self.assertEqual(self.h.status("run")["artifacts"], [])

    def test_scope_and_mode_are_explicit(self):
        seen = []

        class Observe(FixtureAdapter):
            def execute(self, request):
                seen.append(copy.deepcopy(request))
                request["evidence"].clear()
                return super().execute(request)

        self.h.step("run", Observe())
        result = self.h.step("run", Observe())
        self.assertEqual(set(seen[2]["context"]), {"price"})
        self.assertNotIn("decision", seen[2])
        self.assertTrue(result["artifacts"][1]["dependencies"])
        self.h.start("model", "model")
        with self.assertRaisesRegex(HarnessError, "execution mode"):
            self.h.step("model", self.adapter)

    def test_invalid_patch_has_no_side_effects(self):
        with self.assertRaises(HarnessError):
            self.h.update({"price": {"amount_minor": -1}, "goal": "valid"})
        self.assertEqual(self.h.status("run")["context"]["revision"], 1)

    def test_future_db_is_rejected(self):
        conn = sqlite3.connect(self.path.parent / "future.sqlite")
        conn.execute("PRAGMA user_version=99")
        conn.close()
        with self.assertRaisesRegex(HarnessError, "unsupported database"):
            Harness(self.path.parent / "future.sqlite")

    def test_commit_failure_rolls_back_all_artifacts(self):
        self.h.step("run", self.adapter)
        self.h.db.execute("""
            CREATE TRIGGER reject_pricing BEFORE INSERT ON artifacts
            WHEN NEW.kind = 'pricing'
            BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            self.h.step("run", self.adapter)
        self.assertEqual(self.h.status("run")["artifacts"], [])
        self.assertEqual(self.tasks(), ["succeeded", "running"])
        self.h.db.execute("DROP TRIGGER reject_pricing")
        self.assertEqual(len(self.h.step("run", self.adapter, recover=True)["artifacts"]), 3)

    def test_cli_init_start_change_and_resume(self):
        path = self.path.parent / "cli.sqlite"

        def cli(*args):
            output = subprocess.check_output(
                [sys.executable, "-m", "harness", "--db", str(path), *args], cwd=ROOT, text=True
            )
            return json.loads(output)

        self.assertEqual(
            cli("init", "examples/harness/project.json")["initialized"], "meeting-demo"
        )
        cli("start", "cli")
        first = cli("resume", "cli")
        price_id = next(a["id"] for a in first["artifacts"] if a["kind"] == "pricing")
        self.assertEqual(
            cli("change", "examples/harness/price-change.json")["stale_artifact_ids"], [price_id]
        )
        second = cli("resume", "cli")
        self.assertEqual([t["attempt"] for t in second["tasks"]], [1, 2])
        self.assertEqual(len(second["artifacts"]), 4)
