"""Build a portable, review-only snapshot of an active GTM run."""

from html import escape
import re

from .decision import markdown_lines as contract_lines
from .provenance import format_money
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


def _money_label(field, value):
    amount = value.get("amount_minor")
    currency = value.get("currency")
    if type(amount) is not int or not isinstance(currency, str):
        return f"{field} = unknown"
    label = f"{field} = {format_money(amount, currency.upper())}"
    unit = value.get("unit")
    if isinstance(unit, str) and unit.strip():
        label += f" ({unit.strip()})"
    return label


def _slot_label(field, slot):
    if field == "budget_constraints":
        return _money_label(field, slot)
    if field == "observation_window":
        return f"{field} = {slot.get('value')} {slot.get('unit')}"
    if field == "independence_conditions":
        values = slot.get("values") or []
        return f"{field} = " + "; ".join(str(value) for value in values)
    value = slot.get("value")
    unit = slot.get("unit")
    return f"{field} = {value}" + (f" {unit}" if unit else "")


def _dedupe(items):
    seen = set()
    unique = []
    for item in items:
        key = (item["category"], item.get("field"), item["label"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _provenance(state, decision, active):
    operator = []
    external = []
    inference = []
    proposals = []
    values = state["context"]["values"]
    for field in ("goal", "budget", "price"):
        value = values.get(field)
        if isinstance(value, dict):
            operator.append(
                {
                    "category": "operator_input",
                    "label": _money_label(field, value),
                    "field": field,
                }
            )
        elif isinstance(value, str) and value.strip():
            operator.append(
                {
                    "category": "operator_input",
                    "label": f"{field} = {value.strip()[:300]}",
                    "field": field,
                }
            )
    records = ([("strategy", decision)] if decision else []) + [
        (item["kind"], item) for item in active
    ]
    for label, item in records:
        contract = item.get("contract") if label == "strategy" else None
        if contract:
            approved = contract.get("approval_status") == "approved"
            for field in (
                "target_value",
                "sample_size",
                "observation_window",
                "independence_conditions",
            ):
                slot = contract.get(field)
                if not isinstance(slot, dict):
                    continue
                if slot.get("state") == "decided" and approved:
                    operator.append(
                        {
                            "category": "operator_input",
                            "label": _slot_label(field, slot),
                            "field": field,
                        }
                    )
                elif slot.get("state") == "proposed":
                    proposals.append(
                        {
                            "category": "proposal",
                            "label": _slot_label(field, slot) + " (unapproved)",
                            "field": field,
                        }
                    )
        for assumption in item.get("assumptions") or []:
            inference.append(
                {"category": "inference", "label": str(assumption)[:500]}
            )
        # Stored result claims are raw model data. Link the validated claim map.
        for claim in (item.get("evidence_audit") or {}).get("claims", []):
            if not claim.get("source_id") or not claim.get("claim_id"):
                continue
            external.append(
                {
                    "category": "external_evidence",
                    "label": str(claim.get("text") or claim.get("quote") or "")[:500],
                    "field": str(claim.get("claim_key") or "claim"),
                    "source_id": claim["source_id"],
                    "claim_id": claim["claim_id"],
                }
            )
        check = item.get("constraint_check") or {}
        for proposal in check.get("proposals") or []:
            if isinstance(proposal, dict) and proposal.get("field"):
                proposals.append(
                    {
                        "category": "proposal",
                        "label": (
                            f"{proposal['field']} · "
                            f"{proposal.get('reason') or 'proposed change'}"
                        )[:500],
                        "field": proposal["field"],
                    }
                )
    return {
        "operator_input": _dedupe(operator),
        "external_evidence": _dedupe(external),
        "inference": _dedupe(inference),
        "proposal": _dedupe(proposals),
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
        "provenance": _provenance(state, decision, active),
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
                "provenance": (item.get("evidence_audit") or {}).get("provenance", {}),
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
    provenance = package.get("provenance") or {}
    if any(
        provenance.get(key)
        for key in ("operator_input", "external_evidence", "inference", "proposal")
    ):
        lines += ["## Provenance and source classes", ""]
        for key, label in (
            ("operator_input", "Operator input"),
            ("external_evidence", "External evidence"),
            ("inference", "Inference (unverified)"),
            ("proposal", "Proposal (unapproved)"),
        ):
            items = provenance.get(key) or []
            lines.append(f"- {label} · {len(items)}")
            for entry in items[:5]:
                lines.append(f"  - {_text(entry['label'])}")
            if len(items) > 5:
                lines.append(f"  - … {len(items) - 5} more")
        lines.append("")
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
