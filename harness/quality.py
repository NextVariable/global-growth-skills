"""Deterministic quality checks for GTM package deliverables."""

from collections import Counter
import re

CHECKS = {
    "strategy": {
        "market_or_icp": r"(?:ICP|segment|audience|market|customer|市场|细分|客户)",
        "constraints": r"(?:constraint|budget|limit|assumption|约束|预算|限制|假设)",
        "decision": r"(?:recommend|decision|choose|enter|recommendation|建议|决策|选择)",
    },
    "positioning": {
        "value_proposition": r"(?:value|benefit|why|outcome|价值|收益|为什么)",
        "audience": r"(?:team|founder|developer|buyer|customer|audience|团队|开发者|客户|用户)",
        "call_to_action": r"(?:CTA|call to action|sign up|start|book|register|download|预约|注册|开始|试用)",
    },
    "pricing": {
        "price": r"(?:price|pricing|USD|EUR|GBP|CNY|\\$|€|£|¥|价格|定价)",
    },
    "capabilities": {
        "capabilities": r"(?:support|capabilit|feature|workflow|支持|能力|功能)",
    },
    "launch": {
        "channel": r"(?:channel|community|channel|渠道|社区)",
        "owner": r"(?:owner|responsible|operator|负责|负责人)",
        "measurement": r"(?:metric|measure|track|observe|KPI|指标|衡量|观察)",
    },
    "sales": {
        "discovery": r"(?:discovery|qualif|need|需求|资格|访谈)",
        "activation": r"(?:activation|onboard|first value|采用|激活|上手)",
        "retention": r"(?:retention|renew|churn|expansion|续费|留存|流失|扩展)",
    },
    "experiments": {
        "primary_metric": r"(?:KPI|metric|primary outcome|指标|主指标)",
        "denominator_or_source": r"(?:denominator|source|cohort|sample|分母|来源|样本|队列)",
        "guardrail": r"(?:guardrail|safety|护栏|安全)",
        "decision_rule": r"(?:decision rule|stop|threshold|ship|revert|判定|停止|阈值|上线|回滚)",
        "time_window": r"(?:day|week|month|window|天|周|月|窗口)",
    },
}

ASSUMPTION_LABEL = r"(?:assumption|hypothesis|assume|假设|推断|未验证)"
FORMULA = r"[A-Za-z_\u4e00-\u9fff]+\s*=\s*[^\n]{2,}"
EXTERNAL_BLOCKING = {"missing_claims"}
KIND_CATEGORY = {
    "launch-plan": "launch",
    "sales-plan": "sales",
    "experiment-plan": "experiments",
}


def _category(kind):
    return KIND_CATEGORY.get(kind, kind)


def _checks(kind, text):
    rules = CHECKS.get(_category(kind), {})
    found = []
    for name, pattern in rules.items():
        found.append({"name": name, "ok": bool(re.search(pattern, text, re.I))})
    return found


def _metrics(kind, text):
    if _category(kind) not in {"launch", "sales", "experiments"}:
        return []
    checks = []
    checks.append(
        {
            "name": "quantified_target",
            "ok": bool(
                re.search(
                    r"\b\d+(?:\.\d+)?\s*(?:%|percent|days?|weeks?|[- ]day|[- ]week|users?|teams?|天|周|用户|团队)"
                    r"|\b\d+(?:\.\d+)?\s+[A-Za-z\u4e00-\u9fff ]{2,24}\b(?:users?|teams?|customers?|用户|团队|客户)\b",
                    text,
                    re.I,
                )
            ),
        }
    )
    checks.append({"name": "metric_formula", "ok": bool(re.search(FORMULA, text))})
    return checks


def _item(kind, text, item):
    checks = _checks(kind, text) + _metrics(kind, text)
    assumptions = item.get("assumptions") or []
    checks.append(
        {
            "name": "assumptions_separated",
            "ok": bool(assumptions) or bool(re.search(ASSUMPTION_LABEL, text, re.I)),
        }
    )
    audit = item.get("evidence_audit") or {}
    evidence_status = audit.get("status", "not_applicable")
    checks.append(
        {
            "name": "evidence_gate",
            "ok": evidence_status not in EXTERNAL_BLOCKING,
        }
    )
    passed = sum(check["ok"] for check in checks)
    score = round(100 * passed / len(checks)) if checks else 100
    status = "fail" if score < 60 or evidence_status in EXTERNAL_BLOCKING else "warn" if score < 85 else "pass"
    return {
        "kind": kind,
        "score": score,
        "status": status,
        "checks": checks,
        "evidence_status": evidence_status,
        "assumptions": len(assumptions),
        "evidence_gaps": list(item.get("evidence_gaps") or []),
    }


def _tokens(text):
    return {word.casefold() for word in re.findall(r"[A-Za-z\u4e00-\u9fff]{4,}", text)}


def _consistency(state, items):
    values = state["context"]["values"]
    texts = {item["kind"]: item.get("text", "") for item in items}
    findings = []
    audience = _tokens(values.get("audience", ""))
    if audience:
        for kind in ("positioning", "launch-plan", "sales-plan", "experiment-plan"):
            if kind not in texts:
                continue
            shared = audience & _tokens(texts[kind])
            findings.append(
                {
                    "check": f"audience_reused_in_{kind}",
                    "ok": bool(shared),
                    "detail": ", ".join(sorted(shared))[:200] or "no shared audience term",
                }
            )
    price = values.get("price")
    if price:
        amount = str(price["amount_minor"])
        for kind in ("pricing", "sales-plan", "experiment-plan"):
            if kind in texts:
                findings.append(
                    {
                        "check": f"price_consistent_in_{kind}",
                        "ok": amount in texts[kind] or price["currency"] in texts[kind],
                        "detail": f"{amount} {price['currency']}",
                    }
                )
    budget = values.get("budget")
    if budget:
        amount = str(budget["amount_minor"])
        for kind in ("launch-plan", "sales-plan", "experiment-plan"):
            if kind in texts:
                findings.append(
                    {
                        "check": f"budget_respected_in_{kind}",
                        "ok": amount in texts[kind] or budget["currency"] in texts[kind],
                        "detail": f"{amount} {budget['currency']}",
                    }
                )
    return findings


def assess(state):
    records = []
    decision = next(
        (item for item in state["decisions"] if item["id"] == state["active_decision_id"]),
        None,
    )
    if decision:
        records.append(
            ("strategy", decision.get("recommendation", ""), decision)
        )
    for artifact in state["artifacts"]:
        if artifact["status"] == "draft":
            records.append((artifact["kind"], artifact.get("markdown", ""), artifact))
    items = [_item(kind, text, item) for kind, text, item in records]
    for item, (kind, text, _) in zip(items, records):
        item["text"] = text
    consistency = _consistency(state, items)
    for item in items:
        item.pop("text", None)
    statuses = Counter(item["status"] for item in items)
    overall = (
        "fail"
        if statuses["fail"]
        else "warn"
        if statuses["warn"] or any(not finding["ok"] for finding in consistency)
        else "pass"
    )
    return {
        "status": overall,
        "score": round(sum(item["score"] for item in items) / len(items)) if items else 0,
        "items": items,
        "consistency": consistency,
        "counts": dict(statuses),
    }


def markdown_lines(quality):
    lines = [
        "## Quality scorecard",
        "",
        f"Overall `{quality['status']}` · score {quality['score']}/100. "
        "Deterministic structural checks only; they do not grade factual truth or business results.",
        "",
    ]
    for item in quality["items"]:
        missing = [check["name"] for check in item["checks"] if not check["ok"]]
        lines.append(
            f"- `{item['kind']}` · {item['status']} · {item['score']}/100 · "
            f"evidence `{item['evidence_status']}` · missing {', '.join(missing) or 'none'}"
        )
        for gap in item["evidence_gaps"]:
            lines.append(f"  - gap · {gap}")
    if quality["consistency"]:
        lines.append("")
        for finding in quality["consistency"]:
            label = "ok" if finding["ok"] else "check"
            lines.append(f"- {label} · {finding['check']} · {finding['detail']}")
    return lines
