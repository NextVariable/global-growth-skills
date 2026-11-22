"""Build a portable, review-only snapshot of an active GTM run."""

from html import escape
import re

from .research import prose_review, review, source_dependencies

HEADING = {
    "positioning": "Positioning, messaging and landing page draft",
    "pricing": "Pricing draft",
    "capabilities": "Product capability draft",
    "launch-plan": "Channel acquisition plan",
    "sales-plan": "Sales and retention playbook",
    "experiment-plan": "Experiment plan and KPI measurement framework",
}


def snapshot(state, receipts):
    sources = review(state["context"]["values"].get("market_sources", []))
    decisions = state["decisions"]
    decision = next((item for item in decisions if item["id"] == state["active_decision_id"]), None)
    active = [item for item in state["artifacts"] if item["status"] == "draft"]
    return {
        "schema_version": 1,
        "run_id": state["run_id"],
        "execution": state["execution"],
        "status": "ready_for_internal_review"
        if all(t["status"] == "succeeded" for t in state["tasks"])
        else "incomplete",
        "scope": state["plan"],
        "context": {
            **state["context"],
            "values": {
                k: v for k, v in state["context"]["values"].items() if k != "market_sources"
            },
        },
        "decision": decision,
        "artifacts": active,
        "historical_artifact_ids": [a["id"] for a in state["artifacts"] if a["status"] == "stale"],
        "tasks": state["tasks"],
        "evidence_review": sources,
        "claim_audit": [
            {
                "record": label,
                "exact_excerpt_checks": len(item.get("claims", [])),
                "source_ids": sorted(
                    source_dependencies(
                        sources, item.get("claims", []), item.get("citation_ids", [])
                    )
                )
                if item.get("claims") or item.get("citation_ids")
                else [],
                "prose_flags": prose_review(item.get("markdown", item.get("recommendation", ""))),
            }
            for label, item in (
                ([("strategy", decision)] if decision else []) + [(a["kind"], a) for a in active]
            )
        ],
        "skill_pins": state["skill_pins"],
        "attempts": state["history"],
        "read_receipts": [r for r in receipts if r["event"] in {"read_confirmed", "read_failed"}],
    }


def _text(value):
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))
    return escape(value, quote=False).replace("![", r"\!\[")


def _claim_lines(item):
    return [
        f"- Evidence `{_text(claim['source_id'])}` · {_text(claim['quote'])}"
        for claim in item.get("claims", [])
    ]


def markdown(package):
    context = package["context"]
    lines = [
        "# GTM Package",
        "",
        f"Project `{context['project_id']}` · revision {context['revision']} · run `{package['run_id']}`",
        f"Execution `{package['execution']}` · {package['status']}",
        "",
        "Internal review. Validate any proposed action and any factual assertion outside the evidence log before reuse.",
        "",
        "## Project and workflow",
        "",
    ]
    for field in ("product", "market", "audience", "goal", "budget"):
        if field in context["values"]:
            lines.append(f"- **{field}** · {_text(context['values'][field])}")
    lines += ["", *[f"- `{t['stage']}` · {t['status']}" for t in package["tasks"]], ""]
    decision = package["decision"]
    if decision:
        lines += [
            "## Market, ICP and GTM strategy",
            "",
            f"Decision `{decision['id']}` · {decision.get('market_status', 'review required')}",
            "",
            _text(decision["recommendation"]),
            "",
            *_claim_lines(decision),
            "",
        ]
    for a in package["artifacts"]:
        lines += [
            f"## {HEADING[a['kind']]}",
            "",
            f"Draft `{a['id']}` · inputs {a.get('handoff_ids', [])}",
            "",
            _text(a["markdown"]),
            "",
            *_claim_lines(a),
            "",
        ]
    lines += ["## Evidence and decision log", ""]
    for item in package["claim_audit"]:
        flags = ", ".join(item["prose_flags"]) or "none detected"
        lines.append(
            f"- {item['record']} · exact excerpts {item['exact_excerpt_checks']} · prose flags {flags}"
        )
    lines.append("")
    if not package["evidence_review"]["sources"]:
        lines += ["No market source was supplied.", ""]
    for row in package["evidence_review"]["sources"]:
        lines += [
            f"- `{row['id']}` · {row['status']} · observed {row['observed_on']} · valid through {row['valid_until']}",
            f"  - Locator `{_text(row['url']).replace(chr(96), '&#96;')}`",
            f"  - Observation {_text(row['excerpt'])}",
        ]
    return "\n".join(lines) + "\n"
