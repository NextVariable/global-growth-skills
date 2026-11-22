"""Classify figures in a draft by provenance.

Only operator-supplied context and operator-authenticated decision revisions
create ``operator_input`` facts. Draft prose cannot promote its own figures to
operator input, and a mapped source cannot turn an internal constraint into an
external fact. External market assertions still need a claim and a source.
"""

from decimal import Decimal, InvalidOperation
import re

MONEY_PATTERN = re.compile(
    r"(?P<symbol>[$€£¥])\s?(?P<symbol_amount>\d[\d,.]*)\s?(?P<suffix>[kKmMbB])?"
    r"|\b(?P<code_amount>\d[\d,.]*)\s*"
    r"(?P<code>USD|EUR|GBP|CNY|RMB|dollars?|euros?|pounds?|yuan)\b",
    re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
SYMBOL_CURRENCY = {"$": {"USD"}, "€": {"EUR"}, "£": {"GBP"}, "¥": {"CNY", "JPY"}}
WORD_CURRENCY = {
    "usd": {"USD"},
    "eur": {"EUR"},
    "gbp": {"GBP"},
    "cny": {"CNY"},
    "rmb": {"CNY"},
    "dollar": {"USD"},
    "dollars": {"USD"},
    "euro": {"EUR"},
    "euros": {"EUR"},
    "pound": {"GBP"},
    "pounds": {"GBP"},
    "yuan": {"CNY"},
}
SUFFIX = {"k": Decimal(1000), "m": Decimal(1000000), "b": Decimal(1000000000)}
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
PARTICIPANT = re.compile(
    r"participant|completer|person|people|team|user|customer|用户|客户|完成者|团队|人",
    re.IGNORECASE,
)
PERCENT_UNITS = {"%", "percent", "percentage", "pct"}
APPROVED_SLOTS = (
    "target_value",
    "sample_size",
    "observation_window",
    "independence_conditions",
)


def _normalize(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def _format_money(amount_minor, currency):
    major = Decimal(amount_minor) / Decimal(100)
    if major == major.to_integral():
        return f"{int(major)} {currency}"
    return f"{major.normalize():f} {currency}"


def _money_fact(field, value):
    amount = value.get("amount_minor")
    currency = value.get("currency")
    if type(amount) is not int or not isinstance(currency, str) or not currency.strip():
        return None
    currency = currency.strip().upper()
    label = f"{field} = {_format_money(amount, currency)}"
    unit = value.get("unit")
    if isinstance(unit, str) and unit.strip():
        label += f" ({unit.strip()})"
    return {
        "kind": "money",
        "field": field,
        "amount_minor": amount,
        "currency": currency,
        "label": label,
    }


def _slot_fact(field, slot):
    if field == "observation_window":
        value = slot.get("value")
        unit = slot.get("unit")
        if type(value) is not int or unit not in {"days", "weeks"}:
            return None
        days = value * (7 if unit == "weeks" else 1)
        return {
            "kind": "window",
            "field": field,
            "days": days,
            "value": value,
            "unit": unit,
            "label": f"{field} = {value} {unit}",
        }
    if field == "independence_conditions":
        values = slot.get("values")
        if not isinstance(values, list) or not values:
            return None
        return {
            "kind": "list",
            "field": field,
            "values": [str(item) for item in values],
            "label": f"{field} = " + "; ".join(str(item) for item in values),
        }
    value = slot.get("value")
    if type(value) not in {int, float} or type(value) is bool:
        return None
    unit = slot.get("unit")
    label = f"{field} = {value}"
    if isinstance(unit, str) and unit.strip():
        label += f" {unit.strip()}"
    return {
        "kind": "number",
        "field": field,
        "value": value,
        "unit": unit,
        "label": label,
    }


def internal_facts(context=None, contract=None):
    """Return figures the operator supplied or approved, never model claims."""
    facts = []
    context = context or {}
    for field in ("budget", "price"):
        value = context.get(field)
        if isinstance(value, dict):
            fact = _money_fact(field, value)
            if fact:
                facts.append(fact)
    goal = context.get("goal")
    if isinstance(goal, str) and goal.strip():
        facts.append(
            {
                "kind": "text",
                "field": "goal",
                "label": f"goal = {_normalize(goal)[:200]}",
            }
        )
    if isinstance(contract, dict):
        budget = contract.get("budget_constraints")
        if isinstance(budget, dict) and budget.get("state") == "decided":
            fact = _money_fact("budget_constraints", budget)
            if fact:
                facts.append(fact)
        if contract.get("approval_status") == "approved":
            for field in APPROVED_SLOTS:
                slot = contract.get(field)
                if isinstance(slot, dict) and slot.get("state") == "decided":
                    fact = _slot_fact(field, slot)
                    if fact:
                        facts.append(fact)
    return facts


def _money_token(match):
    if match.group("symbol"):
        raw = match.group("symbol_amount")
        suffix = (match.group("suffix") or "").casefold()
        currencies = SYMBOL_CURRENCY[match.group("symbol")]
    else:
        raw = match.group("code_amount")
        suffix = ""
        currencies = WORD_CURRENCY[match.group("code").casefold()]
    try:
        amount = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    if suffix:
        amount *= SUFFIX[suffix]
    return {"amount_minor": amount * 100, "currencies": currencies}


def _match_money(token, facts):
    for fact in facts:
        if fact["kind"] != "money" or fact["currency"] not in token["currencies"]:
            continue
        if Decimal(fact["amount_minor"]) == token["amount_minor"]:
            return fact
    return None


def _match_percent(match, facts):
    value = Decimal(match.group("value"))
    for fact in facts:
        if fact["kind"] != "number":
            continue
        if str(fact.get("unit") or "").casefold() not in PERCENT_UNITS:
            continue
        if Decimal(str(fact["value"])) == value:
            return fact
    return None


def _number_pattern(value):
    words = [word for word, number in NUMBER_WORDS.items() if number == value]
    return r"\b(?:" + "|".join([re.escape(str(value))] + words) + r")\b"


def _window_token(fact, text):
    days = fact["days"]
    pattern = rf"\b(?:\d+|{'|'.join(NUMBER_WORDS)})\b[\s-]*(?:days?|weeks?|周|天)"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        token = _normalize(match.group(0))
        if re.search(rf"\b{days}\b", token):
            return token
        if days % 7 == 0 and re.search(rf"\b{days // 7}\b", token):
            return token
        words = [w for w, n in NUMBER_WORDS.items() if n in {days, days // 7}]
        if words and any(re.search(rf"\b{word}\b", token, re.IGNORECASE) for word in words):
            return token
    return None


def _number_token(fact, text):
    value = fact["value"]
    if type(value) is not int:
        return None
    pattern = _number_pattern(value)
    for match in re.finditer(pattern, text, re.IGNORECASE):
        nearby = text[max(0, match.start() - 40) : match.end() + 40]
        if PARTICIPANT.search(nearby):
            return _normalize(match.group(0))
    return None


def classify(text, flags, facts):
    """Split prose flags into explained operator inputs and external facts."""
    text = text or ""
    operator = []
    external = []
    external_flags = set()
    seen = set()

    def explain(fact, token, flag):
        key = (fact["field"], _normalize(token).casefold())
        if key in seen:
            return
        seen.add(key)
        operator.append(
            {
                "category": "operator_input",
                "label": f'{fact["label"]} · matched "{_normalize(token)[:120]}"',
                "field": fact["field"],
                "flag": flag,
            }
        )

    for flag in flags:
        if flag == "price_in_prose":
            found = list(MONEY_PATTERN.finditer(text))
            if not found:
                external_flags.add(flag)
                continue
            for match in found:
                token = _money_token(match)
                fact = _match_money(token, facts) if token else None
                if fact:
                    explain(fact, match.group(0), flag)
                else:
                    token_text = _normalize(match.group(0))
                    external.append(
                        {
                            "category": "external_evidence",
                            "label": f'unmatched amount "{token_text[:120]}"',
                            "flag": flag,
                        }
                    )
                    external_flags.add(flag)
        elif flag == "percentage_claim_in_prose":
            found = list(PERCENT_PATTERN.finditer(text))
            if not found:
                external_flags.add(flag)
                continue
            for match in found:
                fact = _match_percent(match, facts)
                if fact:
                    explain(fact, match.group(0), flag)
                else:
                    token_text = _normalize(match.group(0))
                    external.append(
                        {
                            "category": "external_evidence",
                            "label": f'unmatched percentage "{token_text[:120]}"',
                            "flag": flag,
                        }
                    )
                    external_flags.add(flag)
        else:
            external_flags.add(flag)

    for fact in facts:
        if fact["kind"] == "window":
            token = _window_token(fact, text)
            if token:
                explain(fact, token, "observation_window")
        elif fact["kind"] == "number" and fact.get("field") in {
            "target_value",
            "sample_size",
        }:
            token = _number_token(fact, text)
            if token:
                explain(fact, token, fact["field"])
    return {
        "operator_input": operator,
        "external": external,
        "external_flags": sorted(external_flags),
    }
