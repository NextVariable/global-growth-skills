import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from harness.codex_host import CodexAdapter, handoff, output_schema
from harness.contracts import HarnessError


class CodexHostTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.checkout = Path(directory.name)

        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.checkout), *args], text=True)

        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        skill = self.checkout / "skills/example/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("Original pins", encoding="utf-8")
        git("add", ".")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        revision = git("rev-parse", "HEAD").strip()
        skill.write_text("Uncommitted text", encoding="utf-8")
        self.request = {
            "stage": "strategy",
            "skill": {"revision": revision, "path": "skills/example"},
        }
        self.adapter = CodexAdapter({"strategy": self.checkout}, model="fixture-model")

    def test_claim_output_schemas_allow_only_required_draft_fields(self):
        strategy = output_schema("strategy")
        self.assertEqual(set(strategy["properties"]), set(strategy["required"]))
        self.assertIn("contract", strategy["required"])
        launch = output_schema("launch")
        self.assertEqual(set(launch["properties"]), set(launch["required"]))
        self.assertIn({"type": "null"}, launch["properties"]["constraint_refs"]["anyOf"])
        for schema in (strategy, launch):
            fields = schema["properties"]["claims"]["items"]
            self.assertEqual(set(fields["properties"]), set(fields["required"]))
            self.assertEqual(set(fields["required"]), {"source_id", "quote", "text"})

    def test_decision_schemas_use_the_strict_host_subset_recursively(self):
        from jsonschema import Draft202012Validator

        def visit(node):
            self.assertFalse(
                set(node) & {"$ref", "$defs", "allOf", "if", "then", "else", "not"}
            )
            if node.get("type") == "object":
                self.assertEqual(set(node["properties"]), set(node["required"]))
                self.assertIs(node["additionalProperties"], False)
                for prop in node["properties"].values():
                    visit(prop)
            for branch in node.get("anyOf", []):
                visit(branch)
            if "items" in node:
                visit(node["items"])

        for stage in ("strategy", "content", "launch", "sales", "experiments"):
            schema = output_schema(stage)
            self.assertEqual(schema["type"], "object")
            Draft202012Validator.check_schema(schema)
            visit(schema)

    def test_reads_pinned_blob_over_worktree(self):
        prompt, schema, digest, selection = handoff(self.checkout, self.request)
        self.assertIn("Original pins", prompt)
        self.assertNotIn("Uncommitted text", prompt)
        self.assertEqual(
            schema["required"],
            [
                "recommendation",
                "contract",
                "citations",
                "claims",
                "assumptions",
                "evidence_gaps",
            ],
        )
        self.assertEqual(schema["properties"]["claims"]["items"]["properties"]["text"], {"type": "string"})
        self.assertEqual(len(digest), 64)
        self.assertEqual(selection["included"], ["SKILL.md"])
        self.assertGreater(selection["included_bytes"], 0)

    def test_document_budget_keeps_entrypoint_and_reports_omissions(self):
        reference = self.checkout / "skills/example/references/market.md"
        reference.parent.mkdir(parents=True)
        reference.write_text("Market reference", encoding="utf-8")
        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(self.checkout), *args], text=True
            )

        git("add", "skills/example/references/market.md")
        git("-c", "commit.gpgsign=false", "commit", "-qm", "reference")
        revision = git("rev-parse", "HEAD").strip()
        request = {
            "stage": "strategy",
            "skill": {"revision": revision, "path": "skills/example"},
        }
        prompt, _, _, selection = handoff(self.checkout, request, budget=0)
        self.assertIn("Original pins", prompt)
        self.assertNotIn("Market reference", prompt)
        self.assertEqual(selection["omitted"], ["references/market.md"])
        prompt, _, _, selection = handoff(self.checkout, request, budget=10)
        self.assertIn("Original pins", prompt)
        self.assertNotIn("Market reference", prompt)
        self.assertEqual(selection["omitted"], ["references/market.md"])

    def test_receipt_and_host_invocation_are_read_only(self):
        def host(args, **options):
            self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
            self.assertIn("mcp_servers={}", args)
            self.assertIn("shell_tool", args)
            self.assertIn('approval_policy="never"', args)
            self.assertIn("Original pins", options["input"])
            Path(args[args.index("--output-last-message") + 1]).write_text(
                '{"recommendation":"Review","citations":[]}', encoding="utf-8"
            )
            events = [
                {"type": "turn.started"},
                {"type": "turn.completed", "usage": {"input_tokens": 11}},
            ]
            return SimpleNamespace(
                returncode=0, stderr="", stdout="\n".join(map(json.dumps, events))
            )

        # The real Git pin reader is tested separately above.
        with (
            patch(
                "harness.codex_host.handoff",
                return_value=("Original pins", {}, "x", {"included": ["SKILL.md"], "omitted": [], "included_bytes": 1, "package_bytes": 1}),
            ),
            patch("harness.codex_host.subprocess.run", side_effect=host),
        ):
            self.assertEqual(self.adapter.execute(self.request)["recommendation"], "Review")
        self.assertEqual(self.adapter.last_receipt["tokens"], {"input_tokens": 11})

    def test_timeout_records_failure_without_fabricated_tokens(self):
        with (
            patch(
                "harness.codex_host.handoff",
                return_value=("input", {}, "x", {"included": ["SKILL.md"], "omitted": [], "included_bytes": 1, "package_bytes": 1}),
            ),
            patch(
                "harness.codex_host.subprocess.run",
                side_effect=subprocess.TimeoutExpired("host", 1),
            ),
        ):
            with self.assertRaisesRegex(HarnessError, "timeout"):
                self.adapter.execute(self.request)
        self.assertEqual(self.adapter.last_receipt["error_code"], "timeout")
        self.assertIsNone(self.adapter.last_receipt["tokens"])
