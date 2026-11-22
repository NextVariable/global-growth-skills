"""Traceable GTM decision brief for the five-skill workflow.

The brief is a structure, not an answer. It lists the decision areas, the
operator facts and external sources each area may rely on, and the questions
that stay open. A model may recommend inside an artifact, but it cannot turn an
unmet question into a verified fact, and it cannot rewrite approved limits.
"""

from .contracts import HarnessError

AREAS = (
    ("market_prioritization", "Which market segment should be entered first, and why?"),
    ("icp_segmentation", "Which buyer and user segments share a measurable pain and budget?"),
    ("competitive_positioning", "How should the product be positioned against named alternatives?"),
    ("value_proposition", "Which outcome claim is both differentiated and supportable?"),
    ("channel_prioritization", "Which acquisition channels fit the ICP and the available budget?"),
    ("pricing_packaging", "Which package and price can be tested without inventing willingness to pay?"),
    ("acquisition_experiment", "Which smallest experiment can falsify the channel and message hypothesis?"),
    ("sales_qualification", "Which observable signals qualify or disqualify a prospect?"),
    ("activation_retention", "Which first-value event predicts retention well enough to plan around?"),
)

TOPIC_HINTS = {
    "market_prioritization": ("market", "icp"),
    "icp_segmentation": ("icp", "market"),
    "competitive_positioning": ("competitor",),
    "value_proposition": ("competitor", "icp"),
    "channel_prioritization": ("channel", "icp"),
    "pricing_packaging": ("competitor",),
    "acquisition_experiment": ("channel",),
    "sales_qualification": ("icp", "competitor"),
    "activation_retention": ("icp",),
}

GUARDRAILS = {
    "market_prioritization": "Do not treat search interest, repository stars or traffic as market size.",
    "icp_segmentation": "Do not infer budget or urgency from an audience label alone.",
    "competitive_positioning": "Every named competitor comparison needs a captured source or stays a hypothesis.",
    "value_proposition": "A claim without operator confirmation or external evidence stays a proposal.",
    "channel_prioritization": "Do not recommend paid spend above the approved budget.",
    "pricing_packaging": "Competitor list prices may inform packaging; they do not set willingness to pay.",
    "acquisition_experiment": "Keep the approved sample, target and observation window unless the operator revises them.",
    "sales_qualification": "Qualification signals must be observable before contact, not demographic guesses.",
    "activation_retention": "Do not promise retention lift before a measured baseline exists.",
}


def _operator_refs(inputs, contract):
    refs = []
    for field in ("product", "audience", "goal", "market", "budget", "price", "capabilities"):
        if field in inputs:
            refs.append({"kind": "operator_input", "ref": field})
    if isinstance(contract, dict):
        for field in ("budget_constraints", "target_value", "sample_size", "observation_window"):
            slot = contract.get(field)
            if isinstance(slot, dict) and slot.get("state") == "decided":
                refs.append({"kind": "operator_input", "ref": f"decision.{field}"})
    return refs


def build_brief(inputs, market, contract=None):
    """Return nine decision areas with explicit basis and unresolved questions."""
    if not isinstance(inputs, dict) or not isinstance(market, dict):
        raise HarnessError("decision brief requires project inputs and a market review")
    operator = _operator_refs(inputs, contract)
    eligible = set(market.get("citation_ids", []))
    sources = [row for row in market.get("sources", []) if row.get("id") in eligible]
    contradictions = set(market.get("contradictions", []))
    areas = []
    for area, question in AREAS:
        topics = TOPIC_HINTS[area]
        evidence = [
            {"kind": "external_evidence", "ref": row["id"], "topic": (row.get("capture") or {}).get("topic")}
            for row in sources
            if (row.get("capture") or {}).get("topic") in topics
            and row.get("claim_key") not in contradictions
        ]
        basis = [*operator, *evidence]
        unresolved = []
        if not evidence:
            unresolved.append("No captured public source matches this area yet.")
        if area in {"pricing_packaging", "competitive_positioning"} and not evidence:
            unresolved.append("Competitor pricing or positioning must not be asserted without a source.")
        if area in {"acquisition_experiment", "activation_retention"}:
            for field, label in (
                ("target_value", "target value"),
                ("sample_size", "sample size"),
                ("observation_window", "observation window"),
            ):
                slot = (contract or {}).get(field)
                if not isinstance(slot, dict) or slot.get("state") != "decided":
                    unresolved.append(f"Approve the {label} before planning a measured result.")
        status = "needs_evidence" if unresolved else "decision_ready"
        areas.append(
            {
                "area": area,
                "question": question,
                "status": status,
                "basis": basis,
                "unresolved": unresolved,
                "guardrail": GUARDRAILS[area],
            }
        )
    return {
        "areas": areas,
        "summary": {
            "areas": len(areas),
            "decision_ready": sum(row["status"] == "decision_ready" for row in areas),
            "needs_evidence": sum(row["status"] == "needs_evidence" for row in areas),
            "eligible_sources": len(sources),
        },
        "policy": (
            "Basis entries are the only allowed support for a recommendation. "
            "A missing source or approval stays an explicit hypothesis."
        ),
    }
