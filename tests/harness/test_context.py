import json
import unittest

from harness.research import prompt_review
from harness.telemetry import cost_report


def source(index, excerpt=None):
    return {
        "id": f"hn-{index:020d}",
        "claim_key": f"hn-{index:020d}",
        "url": f"https://news.ycombinator.com/item?id={index}",
        "observed_on": "2026-11-22",
        "valid_until": "2026-11-29",
        "kind": "observation",
        "stance": "supports",
        "excerpt": excerpt or f"Public discussion {index} about the chosen market.",
        "confidence_basis": "Public snapshot.",
        "capture": {"provider": "hn-public"},
        "status": "reviewable",
        "freshness": "fresh",
        "injection_flags": [],
    }


def market(rows):
    return {
        "sources": rows,
        "status": "sources_available",
        "citation_ids": [row["id"] for row in rows],
        "contradictions": [],
        "freshness": {"fresh": len(rows), "expiring": 0, "expired": 0},
    }


class EvidencePackingTests(unittest.TestCase):
    def test_prompt_keeps_locator_and_reports_packing(self):
        packed = prompt_review(market([source(1)]))
        self.assertEqual(packed["packing"]["included"], 1)
        self.assertEqual(packed["packing"]["omitted"], 0)
        row = packed["sources"][0]
        self.assertEqual(row["url"], "https://news.ycombinator.com/item?id=1")
        self.assertEqual(row["claim_key"], "hn-00000000000000000001")
        self.assertNotIn("confidence_basis", row)

    def test_long_excerpts_are_truncated_with_notice(self):
        packed = prompt_review(market([source(1, "x" * 5000)]))
        row = packed["sources"][0]
        self.assertLessEqual(len(row["excerpt"]), 900)
        self.assertTrue(row["excerpt"].endswith("[truncated]"))
        self.assertEqual(packed["packing"]["truncated_excerpts"], 1)

    def test_source_count_and_budget_are_bounded(self):
        rows = [source(index, "y" * 400) for index in range(1, 21)]
        packed = prompt_review(market(rows), max_sources=5, budget=600)
        self.assertLessEqual(len(packed["sources"]), 5)
        self.assertLessEqual(packed["packing"]["used_chars"], 600)
        self.assertGreater(packed["packing"]["omitted"], 0)

    def test_non_citable_or_blocked_sources_never_reach_prompts(self):
        rows = [source(1), source(2), source(3)]
        rows[1]["capture"] = None
        rows[2]["injection_flags"] = ["ignore_instructions"]
        packed = prompt_review(market(rows))
        self.assertEqual([row["id"] for row in packed["sources"]], [rows[0]["id"]])
        self.assertEqual(packed["packing"]["candidates"], 1)

    def test_packing_is_deterministic(self):
        rows = [source(index) for index in range(1, 4)]
        first = json.dumps(prompt_review(market(rows)), sort_keys=True)
        second = json.dumps(prompt_review(market(rows)), sort_keys=True)
        self.assertEqual(first, second)


class CostReportTests(unittest.TestCase):
    def state(self, receipts):
        return {
            "run_id": "demo",
            "execution": "model",
            "history": [
                {"stage": stage, "attempt": 1, "data": {"host_receipt": receipt}}
                for stage, receipt in receipts
            ],
        }

    def test_totals_come_only_from_receipts(self):
        report = cost_report(
            self.state(
                [
                    (
                        "strategy",
                        {
                            "calls": 1,
                            "duration_ms": 1000,
                            "prompt_bytes": 4000,
                            "skill_document_bytes": 700,
                            "tokens": {"input_tokens": 900, "output_tokens": 100},
                            "status": "completed",
                        },
                    ),
                    (
                        "content",
                        {
                            "calls": 2,
                            "duration_ms": 2000,
                            "prompt_bytes": 6000,
                            "skill_package_bytes": 800,
                            "tokens": {"input_tokens": 1800, "output_tokens": 300},
                            "status": "failed",
                        },
                    ),
                ]
            )
        )
        self.assertEqual(report["totals"]["calls"], 3)
        self.assertEqual(report["totals"]["input_tokens"], 2700)
        self.assertEqual(report["totals"]["output_tokens"], 400)
        self.assertEqual(report["totals"]["duration_ms"], 3000)
        self.assertEqual(report["stages"]["content"]["statuses"], ["failed"])
        self.assertEqual(report["cost"]["status"], "not_estimated")

    def test_empty_history_is_not_model_execution(self):
        report = cost_report({"run_id": "fixture", "execution": "fixture", "history": []})
        self.assertFalse(report["totals"]["model_executed"])
        self.assertEqual(report["totals"]["calls"], 0)


if __name__ == "__main__":
    unittest.main()
