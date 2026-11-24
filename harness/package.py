"""Build a portable, review-only snapshot of an active GTM run."""

from html import escape
import re

from .decision import markdown_lines as contract_lines
from .evidence import claim_provenance
from .intelligence import build_brief
from .provenance import format_money
from .quality import assess, markdown_lines
from .research import prose_review, review, source_dependencies, source_kind


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
        key = (
            item["category"], item.get("field"), item["label"],
            item.get("claim_id"), item.get("semantic_support"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _provenance(state, decision, active):
    operator = []
    external = []
    signals = []
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
        provenance = (item.get("evidence_audit") or {}).get("provenance", {})
        external.extend(provenance.get("external_evidence", []))
        signals.extend(provenance.get("external_signal", []))
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
        "external_signal": _dedupe(signals),
        "inference": _dedupe(inference),
        "proposal": _dedupe(proposals),
    }


def _render_record(record, sources):
    """Normalize old persisted provenance for export without rewriting history."""
    audit = record.get("evidence_audit")
    if not audit:
        return record
    provenance = {
        **audit.get("provenance", {}),
        **claim_provenance(sources, audit.get("claims", [])),
    }
    return {**record, "evidence_audit": {**audit, "provenance": provenance}}


def snapshot(state, receipts):
    sources = review(state["context"]["values"].get("market_sources", []))
    decisions = state["decisions"]
    decision = next((item for item in decisions if item["id"] == state["active_decision_id"]), None)
    if decision:
        decision = _render_record(decision, sources["sources"])
    active = [
        _render_record(item, sources["sources"])
        for item in state["artifacts"] if item["status"] == "draft"
    ]
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
        "decision_brief": build_brief(
            state["context"]["values"], sources, (decision or {}).get("contract")
        ),
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


def _claim_lines(item, sources):
    lines = []
    claims = (item.get("evidence_audit") or {}).get("claims", []) or item.get("claims", [])
    for claim in claims:
        source_id = claim["source_id"]
        category = source_kind(sources.get(source_id))
        label = "External signal" if category == "external_signal" else "External evidence"
        semantic = claim.get("semantic_support", "unverified")
        text = f" · {_text(claim['text'])}" if claim.get("text") else ""
        lines.append(
            f"- {label} `{_text(source_id)}` · semantic support: {_text(semantic)} · "
            f"{_text(claim['quote'])}{text}"
        )
    return lines


def _note_lines(item):
    lines = []
    for assumption in item.get("assumptions") or []:
        lines.append(f"- Assumption · {_text(assumption)}")
    for gap in item.get("evidence_gaps") or []:
        lines.append(f"- Evidence gap · {_text(gap)}")
    return lines


def _all_actions(package):
    rows = []
    decision = package.get("decision")
    if decision and decision.get("actions"):
        rows.extend(("strategy", item) for item in decision["actions"])
    for artifact in package["artifacts"]:
        for item in artifact.get("actions") or []:
            rows.append((artifact["kind"], item))
    return rows


def _executive_lines(package):
    context = package["context"]["values"]
    review = package["evidence_review"]
    decision = package.get("decision") or {}
    actions = _all_actions(package)
    lines = [
        "## Executive summary",
        "",
        f"- **Product** · {_text(context.get('product', 'not supplied'))}",
        f"- **Goal** · {_text(context.get('goal', 'not supplied'))}",
        f"- **ICP** · {_text(context.get('audience', 'not supplied'))}",
    ]
    if "budget" in context:
        lines.append(f"- **Budget** · {_text(_field_value(context['budget']))}")
    lines += [
        f"- **Market sources** · {len(review['sources'])} source(s), "
        f"{len(review['citation_ids'])} citable, {len(review['contradictions'])} contradiction(s)",
        f"- **Package status** · `{package['status']}` · quality `{package['quality']['status']}` "
        f"({package['quality']['score']}/100)",
        f"- **Structured actions** · {len(actions)}",
    ]
    if decision.get("recommendation"):
        lines.append(f"- **Strategy snapshot** · {_text(decision['recommendation'])[:600]}")
    blockers = [
        task["stage"] for task in package["tasks"] if task["status"] != "succeeded"
    ]
    if blockers:
        lines.append(f"- **Open stages** · {', '.join(blockers)}")
    if package["decision_review"]["status"] == "required":
        lines.append("- **Next gate** · independent decision review is required before external use")
    elif not actions:
        lines.append("- **Next step** · convert the prose into owned actions before execution")
    else:
        lines.append(f"- **Next step** · {_text(actions[0][1]['next_step'])}")
    return [*lines, ""]


def _market_lines(package):
    review = package["evidence_review"]
    values = package["context"]["values"]
    freshness = review.get("freshness") or {}
    lines = [
        "## Market and ICP research",
        "",
        f"- **ICP hypothesis** · {_text(values.get('audience', 'not supplied'))}",
        f"- **Source review** · `{review['status']}` · citable {len(review['citation_ids'])}",
        f"- **Freshness** · fresh {freshness.get('fresh', 0)} · "
        f"expiring {freshness.get('expiring', 0)} · expired {freshness.get('expired', 0)}",
        f"- **Contradictions** · {len(review['contradictions'])}",
    ]
    for row in review["sources"][:10]:
        topic = (row.get("capture") or {}).get("topic", "unclassified")
        lines.append(
            f"- `{row['id']}` · {source_kind(row)} · {topic} · {row['status']} · "
            f"observed {row['observed_on']}"
        )
    if not review["sources"]:
        lines.append("- No public source was captured; ICP and market claims stay hypotheses.")
    lines.append("")
    return lines


def _competitive_lines(package):
    topic_of = {
        row["id"]: (row.get("capture") or {}).get("topic")
        for row in package["evidence_review"]["sources"]
    }
    locator = {row["id"]: row["url"] for row in package["evidence_review"]["sources"]}
    rows = [
        item
        for item in package["provenance"]["external_evidence"]
        if topic_of.get(item.get("source_id")) == "competitor"
    ]
    lines = ["## Competitive landscape", ""]
    if not rows:
        lines += [
            "- No mapped competitor evidence is available. Treat named comparisons as hypotheses.",
            "",
        ]
    for item in rows[:10]:
        url = _text(locator.get(item["source_id"], "unavailable"))
        lines.append(f"- {_text(item['label'])[:500]} · semantic support: {_text(item['semantic_support'])}")
        lines.append(f"  - Source `{_text(item.get('source_id', 'unknown'))}` · {url}")
    lines.append("")
    return lines


def _kpi_lines(package):
    contract = (package.get("decision") or {}).get("contract") or {}
    lines = ["## KPI and measurement framework", ""]
    approved = []
    for field in ("target_value", "sample_size", "observation_window", "budget_constraints"):
        slot = contract.get(field)
        if isinstance(slot, dict) and slot.get("state") == "decided":
            approved.append(_slot_label(field, slot))
    if approved:
        lines += [f"- Approved · {_text(item)}" for item in approved]
    else:
        lines.append(
            "- No measurement slot is approved yet; do not present an experiment result as validated."
        )
    metrics = []
    for _, action in _all_actions(package):
        if action.get("metric") not in metrics:
            metrics.append(action["metric"])
    if metrics:
        lines += [f"- Action metric · {_text(metric)}" for metric in metrics[:10]]
    lines.append("")
    return lines


def _action_lines(package):
    rows = _all_actions(package)
    lines = ["## Action register", ""]
    if not rows:
        lines += [
            "- No structured actions were returned. Convert the prose into owned actions with "
            "prerequisites, resources, metrics and a next step before execution.",
            "",
        ]
        return lines
    for kind, action in rows[:20]:
        prerequisites = ", ".join(_text(item) for item in action.get("prerequisites") or []) or "none"
        resources = ", ".join(_text(item) for item in action.get("resources") or []) or "none"
        lines += [
            f"### {_text(action['title'])} · {kind}",
            "",
            f"- Owner role · {_text(action['owner_role'])}",
            f"- Prerequisites · {prerequisites}",
            f"- Resources · {resources}",
            f"- Metric · {_text(action['metric'])}",
            f"- Next step · {_text(action['next_step'])}",
            "",
        ]
    return lines


def _brief_lines(package):
    brief = package.get("decision_brief") or {}
    lines = ["## GTM decision register", ""]
    summary = brief.get("summary") or {}
    lines.append(
        f"- Areas {summary.get('areas', 0)} · needs internal review {summary.get('needs_internal_review', 0)} · "
        f"needs evidence {summary.get('needs_evidence', 0)}"
    )
    lines.append(_text(brief.get("policy", "")))
    for area in brief.get("areas") or []:
        basis = ", ".join(
            f"{item['kind']}:{item['ref']}" for item in area.get("basis") or []
        ) or "none"
        lines.append(f"- **{area['area']}** · `{area['status']}` · basis {basis}")
        lines.append(f"  - {_text(area['question'])}")
        lines.append(f"  - Guardrail · {_text(area['guardrail'])}")
        for item in area.get("unresolved") or []:
            lines.append(f"  - Open · {_text(item)}")
    lines.append("")
    return lines


def markdown(package):
    context = package["context"]
    sources = {row["id"]: row for row in package["evidence_review"]["sources"]}
    lines = [
        "# GTM Package",
        "",
        f"Project `{context['project_id']}` · revision {context['revision']} · run `{package['run_id']}`",
        f"Execution `{package['execution']}` · {package['status']}",
        "",
        "Internal review. Validate any proposed action and any factual assertion outside the evidence log before reuse.",
        "",
        *_executive_lines(package),
        "## Project and workflow",
        "",
    ]
    for field in ("product", "market", "audience", "goal", "budget"):
        if field in context["values"]:
            lines.append(f"- **{field}** · {_text(_field_value(context['values'][field]))}")
    lines += ["", *[f"- `{t['stage']}` · {t['status']}" for t in package["tasks"]], ""]
    lines += _market_lines(package)
    lines += _competitive_lines(package)
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
            *_claim_lines(decision, sources),
            *_note_lines(decision),
            "",
        ]
    lines += _brief_lines(package)
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
            *_claim_lines(a, sources),
            *_note_lines(a),
            "",
        ]
    lines += _kpi_lines(package)
    lines += _action_lines(package)
    lines += markdown_lines(package["quality"], format_text=_text) + [""]
    provenance = package.get("provenance") or {}
    if any(
        provenance.get(key)
        for key in ("operator_input", "external_evidence", "external_signal", "inference", "proposal")
    ):
        lines += ["## Provenance and source classes", ""]
        for key, label in (
            ("operator_input", "Operator input"),
            ("external_evidence", "External evidence"),
            ("external_signal", "External signal (discussion or repository activity)"),
            ("inference", "Inference (unverified)"),
            ("proposal", "Proposal (unapproved)"),
        ):
            items = provenance.get(key) or []
            lines.append(f"- {label} · {len(items)}")
            for entry in items[:5]:
                detail = ""
                if "semantic_support" in entry:
                    provider = entry.get("source_provider") or "unspecified provider"
                    detail = f" · {_text(provider)} · semantic support: {_text(entry['semantic_support'])}"
                lines.append(f"  - {_text(entry['label'])}{detail}")
            if len(items) > 5:
                lines.append(f"  - … {len(items) - 5} more")
        lines.append("")
    lines += ["## Evidence and decision register", ""]
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
            f"- `{row['id']}` · {source_kind(row)} · {row['status']} · "
            f"observed {row['observed_on']} · valid through {row['valid_until']}",
            f"  - Locator `{_text(row['url']).replace(chr(96), '&#96;')}`",
            f"  - Observation {_text(row['excerpt'])}",
        ]
    return "\n".join(lines) + "\n"
