import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from harness.codex_host import CodexAdapter, handoff, output_schema
from harness.contracts import HarnessError
from harness.decision import FIELDS, declaration
from harness.orchestrator import Harness
from harness.package import markdown, snapshot


STAGES = ("strategy", "content", "launch", "sales", "experiments")
ACTION = {
    "title": "Review the draft", "owner_role": "Operator",
    "prerequisites": [], "resources": [], "metric": "Drafts reviewed",
    "next_step": "Record the outcome in the log.",
}


def host_slots(value, schema):
    if value is None:
        return None
    if "anyOf" in schema:
        schema = schema["anyOf"][0]
    if schema.get("type") == "object":
        return {key: host_slots(value.get(key), field) for key, field in schema["properties"].items()}
    if schema.get("type") == "array":
        return [host_slots(item, schema["items"]) for item in value]
    return value


class CodexHostTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.checkout = Path(directory.name)
        database_directory = TemporaryDirectory()
        self.addCleanup(database_directory.cleanup)
        self.databases = Path(database_directory.name)

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

    def model_run(self, name):
        harness = Harness(self.databases / f"{name}.sqlite")
        self.addCleanup(harness.close)
        project = Path(__file__).resolve().parents[2] / "examples/harness/project.json"
        harness.initialize(json.loads(project.read_text(encoding="utf-8")))
        pin = {
            **self.request["skill"], "skill_id": "example",
            "repository": "https://github.com/example/skill",
        }
        with patch("harness.orchestrator.skill_registry", return_value=dict.fromkeys(STAGES, pin)):
            harness.start(name, stages=STAGES, execution="model")
        adapter = CodexAdapter(dict.fromkeys(STAGES, self.checkout), model="fixture-model")
        return harness, adapter

    def simulated_host(self, change):
        real_run = subprocess.run

        def host(args, **options):
            if args[0] == "git":
                return real_run(args, **options)
            self.assertEqual(args[:2], ["codex", "exec"])
            request = json.loads(options["input"].split("\n\nTASK:\n", 1)[1])
            schema = json.loads(
                Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8")
            )
            validate = Draft202012Validator(schema).validate
            result = {"claims": [], "assumptions": [], "evidence_gaps": []}
            if request["stage"] == "strategy":
                result.update(
                    recommendation="Review the first workflow.", citations=[],
                    contract={field: {"state": "unknown"} for field in FIELDS},
                )
            else:
                result.update(kind=request["artifact_kind"], markdown="Internal review draft.")
                if "decision" in request:
                    result["constraint_refs"] = declaration(request["decision"]["contract"])
            wire = host_slots(result, schema)
            validate(wire)
            change(wire, request, validate)
            Path(args[args.index("--output-last-message") + 1]).write_text(
                json.dumps(wire), encoding="utf-8"
            )
            return SimpleNamespace(
                returncode=0, stderr="",
                stdout='{"type":"turn.started"}\n{"type":"turn.completed","usage":{"input_tokens":1}}',
            )

        return patch("harness.codex_host.subprocess.run", side_effect=host)

    def test_host_actions_forms_persist_and_export_across_all_five_stages(self):
        for name, actions in (("missing", None), ("null", None), ("empty", []), ("valid", [ACTION])):
            with self.subTest(actions=name):
                harness, adapter = self.model_run(name)

                def change(wire, request, validate):
                    wire["actions"] = actions
                    validate(wire)
                    if name == "missing":
                        del wire["actions"]
                    if request["stage"] == "launch" and name == "valid":
                        # An explicit null proposal value is legal storage data.
                        wire["constraint_refs"]["proposals"] = [
                            {"field": "target_value", "reason": "Review later.", "value": None}
                        ]
                        validate(wire)

                with self.simulated_host(change):
                    for stage in STAGES:
                        state = harness.step(name, adapter)
                        self.assertEqual(next(t for t in state["tasks"] if t["stage"] == stage)["status"],
                                         "succeeded")
                package = json.loads(json.dumps(snapshot(harness.status(name), [])))
                self.assertEqual(len(package["artifacts"]), 6)
                self.assertEqual(sum("host_receipt" in e["data"] for e in package["attempts"]), 7)
                self.assertEqual(package["decision"]["contract"]["observation_window"],
                                 {"state": "unknown"})
                for row in [package["decision"], *package["artifacts"]]:
                    if name in {"missing", "null"}:
                        self.assertNotIn("actions", row)
                    else:
                        self.assertEqual(row["actions"], actions)
                if name == "valid":
                    launch = next(a for a in package["artifacts"] if a["kind"] == "launch-plan")
                    self.assertIsNone(launch["constraint_refs"]["proposals"][0]["value"])
                self.assertEqual(ACTION["title"] in markdown(package), name == "valid")

    def test_host_invalid_types_and_required_nulls_are_rejected_before_persistence(self):
        content_cases = (
            ("string", {"actions": "draft"}, "actions (type)"),
            ("number", {"actions": 3}, "actions (type)"),
            ("object", {"actions": {}}, "actions (type)"),
            ("null-item", {"actions": [None]}, "actions/0 (type)"),
            ("null-owner", {"actions": [{**ACTION, "owner_role": None}]}, "actions/0/owner_role (type)"),
            ("null-markdown", {"markdown": None}, "markdown (type)"),
            ("null-claims", {"claims": None}, "claims (type)"),
            ("unknown-property", {"unrecognized": None}, "(additionalProperties)"),
            ("invalid-kind", {"kind": "unknown"}, "kind (enum)"),
            ("missing-decision", {"constraint_refs": None}, "decision constraints not_declared"),
        )
        strategy_cases = (
            ("null-recommendation", {"recommendation": None}, "recommendation (type)"),
            ("null-contract", {"contract": None}, "contract (type)"),
        )
        cases = [("content", *case) for case in content_cases]
        cases += [("strategy", *case) for case in strategy_cases]
        for stage, name, fields, error in cases:
            with self.subTest(name=name):
                harness, adapter = self.model_run(name)

                def change(wire, request, validate):
                    if request["stage"] == stage:
                        # Bypass the simulated host's schema check to exercise runtime rejection.
                        wire.update(fields)

                with self.simulated_host(change):
                    if stage == "content":
                        harness.step(name, adapter)
                    with self.assertRaisesRegex(HarnessError, f"{stage} attempt failed"):
                        harness.step(name, adapter)
                state = harness.status(name)
                self.assertIn(error, next(t for t in state["tasks"] if t["stage"] == stage)["detail"])
                self.assertEqual(state["artifacts"], [])

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
                "actions",
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
