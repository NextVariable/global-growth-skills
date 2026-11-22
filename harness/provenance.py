"""Classify figures in a draft by provenance.

Only operator-supplied context and operator-authenticated decision revisions
create ``operator_input`` facts. Draft prose cannot promote its own figures to
operator input, and a mapped source cannot turn an internal constraint into an
external fact. External market assertions still need a claim and a source.
"""

from decimal import Decimal, InvalidOperation
import re

# ISO 4217 minor-unit precision for money spellings recognized below.
# Unknown codes stay in minor units and are not eligible for numeric exemption.
MINOR_DIGITS = dict.fromkeys(("USD", "EUR", "GBP", "CNY", "CAD", "AUD", "CHF"), 2)
MINOR_DIGITS.update(dict.fromkeys(("JPY", "KRW", "VND", "CLP"), 0))
MINOR_DIGITS.update(dict.fromkeys(("KWD", "BHD", "JOD", "OMR", "TND", "IQD", "LYD"), 3))
AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
CODES = "|".join(MINOR_DIGITS) + r"|RMB|dollars?|euros?|pounds?|yuan|yen|美元|欧元|日元|人民币|英镑"
MONEY_PATTERN = re.compile(
    rf"(?P<symbol>[$€£¥])\s*(?P<symbol_amount>{AMOUNT})(?P<suffix>[kKmMbB])?(?!\d|[.,]\d)"
    rf"|\b(?P<prefix>{'|'.join(MINOR_DIGITS)})\s*(?P<prefix_amount>{AMOUNT})(?!\d|[.,]\d)"
    rf"|(?<![\d.,])(?P<code_amount>{AMOUNT})\s*(?P<code>{CODES})(?![a-z])",
    re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*[%％]")
SYMBOL_CURRENCY = {"$": {"USD"}, "€": {"EUR"}, "£": {"GBP"}, "¥": {"CNY", "JPY"}}
CURRENCY_ALIASES = {
    "rmb": "CNY", "dollar": "USD", "dollars": "USD", "euro": "EUR", "euros": "EUR",
    "pound": "GBP", "pounds": "GBP", "yuan": "CNY", "yen": "JPY",
    "美元": "USD", "欧元": "EUR", "日元": "JPY", "人民币": "CNY", "英镑": "GBP",
}
EXTERNAL_SUBJECT = re.compile(
    r"\b(?:competitors?|rivals?|vendors?|third.party|market size|TAM|paying customers?)\b"
    r"|竞品|竞争对手|供应商|第三方|市场规模|付费客户", re.I,
)
CLAUSE_BOUNDARY = re.compile(r"[\n;；。！？|]|[.!?](?=\s|$)|,(?=\s)|，|\b(?:and|but|while)\b", re.I)

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


def format_money(amount_minor, currency):
    digits = MINOR_DIGITS.get(currency)
    if digits is None:
        return f"{amount_minor} {currency} minor units"
    major = Decimal(amount_minor).scaleb(-digits)
    return f"{major.normalize():f} {currency}"


def _money_fact(field, value):
    amount = value.get("amount_minor")
    currency = value.get("currency")
    if type(amount) is not int or not isinstance(currency, str) or not currency.strip():
        return None
    currency = currency.strip().upper()
    label = f"{field} = {format_money(amount, currency)}"
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
        raw = match.group("prefix_amount") or match.group("code_amount")
        code = match.group("prefix") or match.group("code")
        suffix = ""
        currencies = {CURRENCY_ALIASES.get(code.casefold(), code.upper())}
    try:
        amount = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    if suffix:
        amount *= SUFFIX[suffix]
    return amount, currencies


def _clause(text, match):
    start = 0
    for separator in CLAUSE_BOUNDARY.finditer(text, 0, match.start()):
        start = separator.end()
    following = CLAUSE_BOUNDARY.search(text, match.end())
    end = following.start() if following else len(text)
    before = text[start:match.start()].strip().casefold()
    after = text[match.end():end].strip().casefold()
    return before, after


def _money_role(text, match):
    before, after = _clause(text, match)
    if EXTERNAL_SUBJECT.search(before + " " + after):
        return None
    if (
        re.search(r"(?:试点|本轮|本项目|推广)?(?:总|现金|投放|推广)?预算\s*(?:为|是|上限为|[:：=])?\s*$", before)
        or re.search(r"(?:^|\b(?:our|the|this|approved|pilot|total|cash|trial|promotion) )"
                     r"(?:(?:our|the|this|approved|pilot|total|cash|trial|promotion|project) ){0,4}budget\s*(?:(?:is|of|at)\b|[:=])?\s*$", before)
        or (
            re.search(r"^\s*(?:(?:cash|total|pilot|promotion)\s+)*budget\b", after)
            and re.search(r"^(?:a |the |our |approved |keep |run |with |use |set )|\b(?:pilot|budget)\b", before)
        )
        or (
            re.search(r"^\s*(?:pilot|trial)\b", after)
            and re.search(r"\b(?:run|plan|propose|design|use|our|approved)\b", before)
        )
        or re.search(r"^(?:试点|推广|现金|总)*预算", after)
    ):
        return "budget"
    if (
        re.search(r"^(?:[-#> ]+)?(?:开源软件许可|软件许可|本产品(?:定价|价格|订阅)|许可费用)"
                  r"[^0-9.,;]{0,20}$", before)
        or re.search(r"\bour (?:price|pricing|licen[cs]e|subscription)[^0-9.,;]{0,25}$", before)
        or re.search(r"^(?:[-#> ]+)?(?:the )?(?:open.source software |software |open.source )"
                     r"licen[cs]e[^0-9.,;]{0,25}$", before)
        or (
            re.search(r"^\s*(?:for\s+)?(?:our|this project's)\s+(?:software\s+)?licen[cs]e\b", after)
            and not re.search(r"[a-z]", before)
        )
    ):
        return "price"
    return None


def _match_money(token, facts, role):
    if token is None or role is None:
        return None
    amount, currencies = token
    fields = {"budget", "budget_constraints"} if role == "budget" else {"price"}
    candidates = [f for f in facts if f["kind"] == "money" and f["field"] in fields]
    for fact in candidates:
        currency = fact["currency"]
        if currency in currencies and currency in MINOR_DIGITS and (
            Decimal(fact["amount_minor"]) == amount.scaleb(MINOR_DIGITS[currency])
        ):
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
    pattern = rf"(?<!\d)(?P<number>\d+|{'|'.join(NUMBER_WORDS)})[\s-]*(?P<unit>days?|weeks?|周|天)"
    for match in re.finditer(pattern, text, re.IGNORECASE):
        number = match.group("number").casefold()
        duration = int(number) if number.isdecimal() else NUMBER_WORDS[number]
        if match.group("unit").casefold() in {"week", "weeks", "周"}:
            duration *= 7
        if duration == fact["days"] and not EXTERNAL_SUBJECT.search(" ".join(_clause(text, match))):
            return _normalize(match.group(0))
    return None


def _number_token(fact, text):
    value = fact["value"]
    if type(value) is not int:
        return None
    pattern = _number_pattern(value)
    for match in re.finditer(pattern, text, re.IGNORECASE):
        nearby = text[max(0, match.start() - 40) : match.end() + 40]
        if PARTICIPANT.search(nearby) and not EXTERNAL_SUBJECT.search(" ".join(_clause(text, match))):
            return _normalize(match.group(0))
    return None


def classify(text, flags, facts):
    """Split prose flags into explained operator inputs and external facts."""
    text = re.sub(r"[*`_]", "", text or "")
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
                fact = _match_money(token, facts, _money_role(text, match))
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
                before, after = _clause(text, match)
                fact = None
                if not EXTERNAL_SUBJECT.search(before + " " + after) and re.search(
                    r"approved.{0,35}(?:target|threshold|gate)|已批准.{0,20}(?:门槛|目标)",
                    before,
                ):
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
