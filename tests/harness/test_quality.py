import unittest

from harness.package import snapshot
from harness.quality import assess


def artifact(kind, markdown, **overrides):
    row = {
        "id": f"art-{kind}",
        "kind": kind,
        "status": "draft",
        "markdown": markdown,
        "claims": [],
        "assumptions": ["Pricing and capacity assumptions are unverified."],
        "evidence_audit": {"status": "verified", "evidence_gaps": []},
    }
    row.update(overrides)
    return row


def strong_state():
    audience = "indie developers"
    return {
        "run_id": "run",
        "execution": "fixture",
        "plan": {},
        "active_decision_id": "dec-1",
        "context": {
            "revision": 1,
            "values": {
                "audience": audience,
                "price": {"amount_minor": 4900, "currency": "USD"},
                "budget": {"amount_minor": 50000, "currency": "USD"},
            },
        },
        "decisions": [
            {
                "id": "dec-1",
                "recommendation": (
                    f"Enter the {audience} market with the Pro plan. Constraints: $50000 budget. "
                    "Assumption: demand is unverified. Decision: validate before scaling."
                ),
            }
        ],
        "artifacts": [
            artifact(
                "positioning",
                f"Why {audience} choose Acme: value and benefit. CTA: start free.",
            ),
            artifact("pricing", "Price USD 49 per seat per month."),
            artifact("capabilities", "Supports import, review and export workflows."),
            artifact(
                "launch-plan",
                f"Channel: {audience} communities. Owner: growth lead. "
                f"Metric: 20 qualified teams. Budget 50000 USD. "
                "Qualified teams = signups with profile / visitors.",
            ),
            artifact(
                "sales-plan",
                f"Discovery for {audience}. Activation: first review. Retention: renewal. "
                "Budget USD 50000. 30-day window. Activation rate = activated / eligible.",
            ),
            artifact(
                "experiment-plan",
                f"Primary metric for {audience}: activation rate. Denominator: eligible teams. "
                "Guardrail: refund rate under 5%. Decision rule: ship above 20% else stop. "
                "14 days. Activation rate = activated teams / eligible teams. Budget USD 50000.",
            ),
        ],
        "tasks": [{"status": "succeeded"}],
        "skill_pins": {},
        "history": [],
    }


class QualityTests(unittest.TestCase):
    def test_strong_package_passes_structural_checks(self):
        quality = assess(strong_state())
        self.assertEqual(quality["status"], "pass", quality)
        self.assertEqual(quality["score"], 100)
        self.assertTrue(all(item["checks"] for item in quality["items"]))
        self.assertTrue(all(finding["ok"] for finding in quality["consistency"]))

    def test_weak_package_fails_and_names_missing_elements(self):
        state = strong_state()
        state["decisions"][0]["recommendation"] = "We will try something."
        state["artifacts"] = [artifact("experiment-plan", "We will test stuff.")]
        quality = assess(state)
        self.assertEqual(quality["status"], "fail")
        missing = {
            check["name"]
            for item in quality["items"]
            for check in item["checks"]
            if not check["ok"]
        }
        self.assertIn("decision", missing)
        self.assertIn("guardrail", missing)
        self.assertIn("decision_rule", missing)

    def test_missing_claims_block_review_readiness(self):
        state = strong_state()
        state["artifacts"][0]["evidence_audit"] = {
            "status": "missing_claims",
            "evidence_gaps": ["No structured claim uses eligible sources."],
        }
        package = snapshot(state, [])
        self.assertEqual(package["status"], "incomplete_evidence")
        self.assertTrue(
            any(item["evidence_status"] == "missing_claims" for item in package["quality"]["items"])
        )


if __name__ == "__main__":
    unittest.main()
