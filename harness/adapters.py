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
            return {"recommendation": f"Focus on {context['audience']} for {context['goal']}."}
        kind = request["artifact_kind"]
        if kind == "positioning":
            markdown = f"# {context['product']}\n\n{request['decision']['recommendation']}"
        elif kind == "pricing":
            price = context["price"]
            markdown = f"Price: {price['amount_minor']} minor units ({price['currency']}) per {price['unit']}."
        else:
            markdown = "Supported: " + (", ".join(context["capabilities"]) or "None declared.")
        return {"kind": kind, "markdown": markdown}
