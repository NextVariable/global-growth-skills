import unittest

from harness.intelligence import AREAS, build_brief


def source(ident, topic, claim_key=None):
    return {
        "id": ident,
        "claim_key": claim_key or ident,
        "url": f"https://example.com/{ident}",
        "observed_on": "2026-11-22",
        "valid_until": "2026-12-22",
        "kind": "observation",
        "stance": "supports",
        "excerpt": "A captured public page.",
        "confidence_basis": "Public snapshot.",
        "capture": {"provider": "web-public", "topic": topic},
    }


def market(rows=(), contradictions=()):
    return {
        "sources": list(rows),
        "citation_ids": [row["id"] for row in rows],
        "contradictions": list(contradictions),
        "status": "sources_available" if rows else "needs_review",
        "freshness": {"fresh": len(rows), "expiring": 0, "expired": 0},
    }


INPUTS = {
    "product": "Analytics for indie SaaS",
    "audience": "Solo founders with 100+ paying accounts",
    "goal": "First 20 qualified trials",
    "budget": {"amount_minor": 10000, "currency": "USD", "unit": "one-off"},
}


class DecisionBriefTests(unittest.TestCase):
    def test_always_covers_nine_areas(self):
        brief = build_brief(INPUTS, market())
        self.assertEqual([row["area"] for row in brief["areas"]], [area for area, _ in AREAS])
        self.assertEqual(brief["summary"]["areas"], 9)

    def test_operator_facts_are_not_external_evidence(self):
        brief = build_brief(INPUTS, market())
        basis = [item for row in brief["areas"] for item in row["basis"]]
        self.assertTrue(any(item["ref"] == "budget" for item in basis))
        self.assertFalse(any(item["kind"] == "external_evidence" for item in basis))
        self.assertTrue(all(row["status"] == "needs_evidence" for row in brief["areas"]))

    def test_competitor_source_grounds_positioning_only(self):
        brief = build_brief(INPUTS, market([source("web-a", "competitor")]))
        by_area = {row["area"]: row for row in brief["areas"]}
        self.assertEqual(by_area["competitive_positioning"]["status"], "decision_ready")
        self.assertIn("web-a", [item["ref"] for item in by_area["competitive_positioning"]["basis"]])
        self.assertEqual(by_area["channel_prioritization"]["status"], "needs_evidence")

    def test_contradicted_source_never_counts_as_support(self):
        brief = build_brief(INPUTS, market([source("web-a", "competitor")], ["web-a"]))
        by_area = {row["area"]: row for row in brief["areas"]}
        self.assertEqual(by_area["competitive_positioning"]["status"], "needs_evidence")
        self.assertNotIn("web-a", [item["ref"] for item in by_area["competitive_positioning"]["basis"]])

    def test_approved_measurement_slots_close_experiment_gaps(self):
        contract = {
            "approval_status": "approved",
            "budget_constraints": {
                "state": "decided",
                "amount_minor": 0,
                "currency": "USD",
                "unit": "one-off",
            },
            "target_value": {"state": "decided", "value": 10, "unit": "%"},
            "sample_size": {"state": "decided", "value": 2, "unit": "users"},
            "observation_window": {"state": "decided", "value": 14, "unit": "days"},
        }
        brief = build_brief(INPUTS, market([source("web-c", "channel")]), contract)
        by_area = {row["area"]: row for row in brief["areas"]}
        self.assertEqual(by_area["acquisition_experiment"]["status"], "decision_ready")
        refs = [item["ref"] for item in by_area["acquisition_experiment"]["basis"]]
        self.assertIn("decision.observation_window", refs)
        self.assertIn("decision.budget_constraints", refs)

    def test_missing_contract_keeps_measurement_questions_open(self):
        brief = build_brief(INPUTS, market([source("web-c", "channel")]))
        area = next(row for row in brief["areas"] if row["area"] == "acquisition_experiment")
        self.assertEqual(area["status"], "needs_evidence")
        self.assertTrue(any("target value" in item for item in area["unresolved"]))

    def test_every_area_carries_a_guardrail(self):
        brief = build_brief(INPUTS, market())
        self.assertTrue(all(row["guardrail"] for row in brief["areas"]))
        self.assertIn("stars", next(r["guardrail"] for r in brief["areas"] if r["area"] == "market_prioritization"))


if __name__ == "__main__":
    unittest.main()
