import unittest

from harness.contracts import HarnessError
from harness.host import CodexHost, TaskInput, TaskResult, capability_matrix, host

REQUEST = {
    "project_id": "demo-project",
    "run_id": "demo-run",
    "stage": "strategy",
    "skill": {
        "skill_id": "global-gtm-strategy-skill",
        "revision": "a" * 40,
        "repository": "https://github.com/NextVariable/global-growth-skills",
        "path": "SKILL.md",
    },
    "context": {
        "product": "Analytics for indie SaaS",
        "audience": "Solo founders",
        "goal": "First 20 qualified trials",
    },
    "evidence": [
        {"field": "product", "revision": 1, "source": "operator_input", "sha256": "b" * 64}
    ],
    "tool_policy": "deny_external_writes",
}


class HostContractTests(unittest.TestCase):
    def test_round_trip_preserves_every_field(self):
        task = TaskInput.from_request(REQUEST)
        self.assertEqual(task.to_request(), REQUEST)

    def test_optional_decision_brief_round_trips(self):
        from harness.intelligence import build_brief

        brief = build_brief(
            REQUEST["context"],
            {"sources": [], "citation_ids": [], "contradictions": [], "status": "needs_review"},
        )
        request = {**REQUEST, "decision_brief": brief}
        task = TaskInput.from_request(request)
        self.assertEqual(task.to_request(), request)

    def test_invalid_task_input_is_rejected(self):
        with self.assertRaises(HarnessError):
            TaskInput.from_request({**REQUEST, "tool_policy": "allow_all"})
        with self.assertRaises(HarnessError):
            TaskInput.from_request({**REQUEST, "unknown": True})

    def test_fixture_host_returns_structured_result(self):
        task = TaskInput.from_request(REQUEST)
        result = host("fixture").execute(task)
        self.assertIsInstance(result, TaskResult)
        self.assertEqual(result.status, "succeeded")
        self.assertIn("recommendation", result.result)
        self.assertTrue(result.result["actions"])

    def test_codex_host_wraps_errors_instead_of_raising(self):
        class Broken:
            last_receipt = {"error_code": "auth_required"}

            def execute(self, request):
                raise RuntimeError("secret detail that should not leak")

        result = CodexHost(Broken()).execute(TaskInput.from_request(REQUEST))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "auth_required")
        self.assertNotIn("secret", result.error)

    def test_capabilities_are_declared_honestly(self):
        matrix = {row["name"]: row["capabilities"] for row in capability_matrix()}
        self.assertEqual(matrix["codex"]["tool_policy"], "enforced_by_host")
        self.assertEqual(matrix["fixture"]["tool_policy"], "not_enforced")
        self.assertNotEqual(matrix["codex"]["context"], matrix["fixture"]["context"])

    def test_task_result_requires_failure_detail(self):
        with self.assertRaises(HarnessError):
            TaskResult("failed", {})
        with self.assertRaises(HarnessError):
            TaskResult("maybe", {})


if __name__ == "__main__":
    unittest.main()
