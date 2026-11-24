"""Host integration boundary and deterministic synthetic implementation."""

from typing import Protocol


class Adapter(Protocol):
    """Host integrations must enforce the request's tool policy out of process.

    Return structured drafts only. Calls can be repeated after recovery.
    """

    execution: str

    def execute(self, request: dict) -> dict: ...


class FixtureAdapter:
    execution = "fixture"

    def execute(self, request):
        context = request["context"]
        if request["stage"] == "strategy":
            return {
                "recommendation": f"Focus on {context['audience']} for {context['goal']}.",
                "actions": [
                    {
                        "title": "Confirm the ICP with five problem interviews",
                        "owner_role": "Founder",
                        "prerequisites": ["A consenting interview list"],
                        "resources": ["5 hours of interview time"],
                        "metric": "Qualified problem confirmations",
                        "next_step": "Book the first two interviews this week.",
                    }
                ],
            }
        kind = request["artifact_kind"]
        if kind == "positioning":
            positioning = request.get("decision", {}).get(
                "recommendation", f"For {context['audience']}: {context['goal']}."
            )
            markdown = f"# {context['product']}\n\n{positioning}"
        elif kind == "pricing":
            price = context["price"]
            markdown = f"Price: {price['amount_minor']} minor units ({price['currency']}) per {price['unit']}."
        elif kind == "capabilities":
            markdown = "Supported: " + (
                ", ".join(context["capabilities"]) or "None declared."
            )
        else:
            recipes = {
                "launch-plan": "Test one channel with a small, consent-based pilot and track qualified replies.",
                "sales-plan": "Draft discovery questions for the intended audience and define a follow-up decision.",
                "experiment-plan": "Define eligible users, a primary outcome, a guardrail, and a stopping rule before testing.",
            }
            markdown = f"# {kind} for {context['product']}\n\n" + recipes[kind]
            if request.get("handoffs"):
                markdown += "\n\nInputs: " + ", ".join(
                    h["kind"] for h in request["handoffs"]
                )
        result = {"kind": kind, "markdown": markdown}
        if kind in {"launch-plan", "sales-plan", "experiment-plan"}:
            result["actions"] = [
                {
                    "title": f"Run the first {kind.replace('-plan', '')} step",
                    "owner_role": "Founder",
                    "prerequisites": ["Approved budget and target"],
                    "resources": ["Existing product access"],
                    "metric": "Qualified responses",
                    "next_step": "Record the baseline before contacting anyone.",
                }
            ]
        return result


class HandoffAdapter:
    """Import operator-supplied results without claiming a verified model call."""

    execution = "handoff"

    def __init__(self, entries):
        from .contracts import HarnessError, validate

        validate("handoff-results", entries)
        self.results = {item["input_digest"]: item["result"] for item in entries}
        if len(self.results) != len(entries):
            raise HarnessError("duplicate handoff input digest")

    def execute(self, request):
        from .contracts import HarnessError, digest

        value = self.results.get(digest(request))
        if value is None:
            raise HarnessError("handoff does not match the current request snapshot")
        return value
