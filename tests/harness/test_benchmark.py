import unittest

from scripts.benchmark_v11 import benchmark


class StructuralBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = benchmark(live=False)

    def test_covers_three_segments_and_three_modes(self):
        self.assertEqual(
            [case["id"] for case in self.report["cases"]],
            ["ai-saas", "developer-tools", "smart-hardware"],
        )
        for case in self.report["cases"]:
            self.assertEqual(
                set(case["modes"]),
                {"generic_single_agent", "manual_five_skills", "harness_orchestrated"},
            )

    def test_harness_beats_prose_proxy_on_structure(self):
        for case in self.report["cases"]:
            generic = case["modes"]["generic_single_agent"]
            harness = case["modes"]["harness_orchestrated"]
            self.assertEqual(generic["complete_actions"], 0)
            self.assertGreater(harness["complete_actions"], 0)
            self.assertGreaterEqual(harness["average_quality"], generic["average_quality"])
            self.assertGreaterEqual(harness["artifacts"], generic["artifacts"])

    def test_harness_exposes_traceable_decisions(self):
        for case in self.report["cases"]:
            harness = case["modes"]["harness_orchestrated"]
            self.assertEqual(harness["decision_ready_areas"], 0)
            self.assertIn("traceability", self.report["boundary"])

    def test_no_model_or_business_claim_is_smuggled_in(self):
        self.assertEqual(self.report["real_model_execution"], {"status": "not_run", "calls": 0})
        self.assertEqual(self.report["business_outcome"], "not_measured")
        for case in self.report["cases"]:
            for row in case["modes"].values():
                self.assertEqual(row["model_calls"], 0)
                self.assertEqual(row["token_measurement"], "not_measured")


if __name__ == "__main__":
    unittest.main()
