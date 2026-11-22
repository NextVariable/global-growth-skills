"""Build a portable, review-only snapshot of an active GTM run."""

from html import escape
import re

from .decision import markdown_lines as contract_lines
from .quality import assess, markdown_lines
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
    records = ([("strategy", decision)] if decision else []) + [(a["kind"], a) for a in active]
    audits = [item.get("evidence_audit") or {} for _, item in records]
    quality = assess(state)
    review_records = [
        {"kind": label, "id": item["id"]}
        for label, item in records
        if decision
        and decision.get("contract")
        and item.get("execution", state["execution"]) in {"model", "handoff"}
        and (label == "strategy" or item.get("decision_id") == decision["id"])
    ]
    decision_review = {
        "status": "required" if review_records else "not_applicable",
        "records": review_records,
    }
    if not all(t["status"] == "succeeded" for t in state["tasks"]):
        status = "incomplete"
    elif any(audit.get("status") == "missing_claims" for audit in audits):
        status = "incomplete_evidence"
    elif review_records:
        status = "needs_decision_review"
    elif any(
        audit.get("status") in {"needs_review", "unsupported_claims", "partial", "conflict"}
        for audit in audits
    ):
        status = "needs_evidence_review"
    elif quality["status"] == "fail":
        status = "needs_quality_review"
    else:
        status = "ready_for_internal_review"
    return {
        "schema_version": 1,
        "run_id": state["run_id"],
        "execution": state["execution"],
        "status": status,
        "scope": state["plan"],
        "context": {
            **state["context"],
            "values": {
                k: v for k, v in state["context"]["values"].items() if k != "market_sources"
            },
        },
        "decision": decision,
        "artifacts": active,
        "quality": quality,
        "decision_review": decision_review,
        "historical_artifact_ids": [a["id"] for a in state["artifacts"] if a["status"] == "stale"],
        "tasks": state["tasks"],
        "evidence_review": sources,
        "claim_audit": [
            {
                "record": label,
                "evidence_status": (item.get("evidence_audit") or {}).get("status", "not_applicable"),
                "exact_excerpt_checks": len(item.get("claims", [])),
                "support_checks": [
                    claim["support"]
                    for claim in (item.get("evidence_audit") or {}).get("claims", [])
                ],
                "semantic_support": [
                    claim["semantic_support"]
                    for claim in (item.get("evidence_audit") or {}).get("claims", [])
                ],
                "source_ids": sorted(
                    source_dependencies(
                        sources, item.get("claims", []), item.get("citation_ids", [])
                    )
                )
                if item.get("claims") or item.get("citation_ids")
                else [],
                "prose_flags": prose_review(item.get("markdown", item.get("recommendation", ""))),
                "evidence_gaps": (item.get("evidence_audit") or {}).get("evidence_gaps", []),
            }
            for label, item in records
        ],
        "skill_pins": state["skill_pins"],
        "attempts": state["history"],
        "read_receipts": [r for r in receipts if r["event"] in {"read_confirmed", "read_failed"}],
    }


def _text(value):
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))
    return escape(value, quote=False).replace("![", r"\!\[")


def _field_value(value):
    if isinstance(value, dict) and "amount_minor" in value:
        amount = f"{value['currency']} {value['amount_minor']:,} minor units"
        unit = value.get("unit")
        return f"{amount} · {unit}" if unit else amount
    return value


def _claim_lines(item):
    lines = []
    for claim in item.get("claims", []):
        text = f" · {_text(claim['text'])}" if claim.get("text") else ""
        lines.append(
            f"- Evidence `{_text(claim['source_id'])}` · {_text(claim['quote'])}{text}"
        )
    return lines


def _note_lines(item):
    lines = []
    for assumption in item.get("assumptions") or []:
        lines.append(f"- Assumption · {_text(assumption)}")
    for gap in item.get("evidence_gaps") or []:
        lines.append(f"- Evidence gap · {_text(gap)}")
    return lines


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
            lines.append(f"- **{field}** · {_text(_field_value(context['values'][field]))}")
    lines += ["", *[f"- `{t['stage']}` · {t['status']}" for t in package["tasks"]], ""]
    if package["decision_review"]["status"] == "required":
        lines += [
            "**Independent decision review required.** The declaration check covers structured "
            "values only. Compare the generated prose with the approved contract before use.",
            "",
        ]
    decision = package["decision"]
    if decision:
        lines += [
            "## Market, ICP and GTM strategy",
            "",
            f"Decision `{decision['id']}` · {decision.get('market_status', 'review required')}",
            "",
            _text(decision["recommendation"]),
            "",
        ]
        contract = decision.get("contract")
        if contract:
            lines += [
                f"Decision contract `{contract['decision_id']}` · revision {contract['decision_revision']} · approval `{contract['approval_status']}`",
                "",
                *contract_lines(contract, format_text=_text),
                "",
            ]
            if contract.get("change_reason"):
                lines += [
                    f"- Change · {_text(contract['change_reason'])} · initiated by "
                    f"{contract.get('change_initiator')} · approved by {contract.get('approved_by')}",
                    "",
                ]
        lines += [
            *_claim_lines(decision),
            *_note_lines(decision),
            "",
        ]
    for a in package["artifacts"]:
        lines += [
            f"## {HEADING[a['kind']]}",
            "",
            f"Draft `{a['id']}` · inputs {a.get('handoff_ids', [])}",
            "",
        ]
        check = a.get("constraint_check")
        if check:
            lines += [
                f"Structured references `{check['status']}` · decision revision {check['decision_revision']}",
                "",
            ]
            for proposal in check.get("proposals") or []:
                lines.append(
                    f"- Proposal only, not approved · {proposal['field']} · {_text(proposal.get('reason') or '')}"
                )
            if check.get("proposals"):
                lines.append("")
        lines += [
            _text(a["markdown"]),
            "",
            *_claim_lines(a),
            *_note_lines(a),
            "",
        ]
    lines += markdown_lines(package["quality"], format_text=_text) + [""]
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
