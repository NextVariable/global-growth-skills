"""Versioned decision contract and deterministic cross-skill drift gate.

A downstream draft may copy the approved constraints or propose new ones. It
cannot change an approved constraint without an operator-approved revision.
The deterministic gate validates declarations. Draft prose requires independent review.
"""

import math

from .contracts import HarnessError

TEXT_FIELDS = ("objective", "primary_metric", "metric_definition", "unit", "comparator")
NUMBER_FIELDS = ("target_value", "sample_size")
INTEGER_FIELDS = {"sample_size"}
LIST_FIELDS = ("independence_conditions",)
WINDOW_FIELDS = ("observation_window",)
BUDGET_FIELDS = ("budget_constraints",)
FIELDS = TEXT_FIELDS + NUMBER_FIELDS + LIST_FIELDS + WINDOW_FIELDS + BUDGET_FIELDS
COMPARATORS = {"at_least", "at_most", "exactly", "within"}
STATES = {"decided", "unknown", "proposed"}
META_KEYS = {
    "decision_id",
    "decision_revision",
    "evidence_refs",
    "assumptions",
    "approval_status",
    "change_reason",
    "approved_by",
    "supersedes",
}


def _blank(value):
    return not isinstance(value, str) or not value.strip()


def _allowed_keys(name):
    if name in TEXT_FIELDS:
        return {"state", "value", "unit", "reason"}
    if name in NUMBER_FIELDS:
        return {"state", "value", "unit", "reason"}
    if name in LIST_FIELDS:
        return {"state", "values", "reason"}
    if name in WINDOW_FIELDS:
        return {"state", "value", "unit", "description", "reason"}
    return {"state", "amount_minor", "currency", "unit", "reason"}


def _slot(name, raw):
    if not isinstance(raw, dict):
        raise HarnessError(f"decision contract {name} must be an object")
    extra = set(raw) - _allowed_keys(name)
    if extra:
        raise HarnessError(
            f"decision contract {name} has unknown fields: {', '.join(sorted(extra))}"
        )
    state = raw.get("state")
    if state not in STATES:
        raise HarnessError(f"decision contract {name} needs state decided, unknown or proposed")
    out = {"state": state}
    if state == "unknown":
        if any(key in raw for key in _allowed_keys(name) - {"state", "reason"}):
            raise HarnessError(
                f"{name} must stay empty while unknown; propose a value instead of deciding it"
            )
    else:
        out.update(_value(name, raw))
    if "reason" in raw:
        if _blank(raw["reason"]):
            raise HarnessError(f"decision contract {name} reason must be non-blank")
        out["reason"] = raw["reason"].strip()
    return out


def _value(name, raw):
    if name in BUDGET_FIELDS:
        for key in ("amount_minor", "currency", "unit"):
            if key not in raw:
                raise HarnessError(f"decided {name} needs {key}")
        if type(raw["amount_minor"]) is not int or raw["amount_minor"] < 0:
            raise HarnessError(f"decided {name} amount_minor must be a non-negative integer")
        if not isinstance(raw["currency"], str) or len(raw["currency"]) != 3:
            raise HarnessError(f"decided {name} currency must be a three-letter code")
        if _blank(raw["unit"]):
            raise HarnessError(f"decided {name} unit must be non-blank")
        return {
            "amount_minor": raw["amount_minor"],
            "currency": raw["currency"].upper(),
            "unit": raw["unit"].strip(),
        }
    if name in LIST_FIELDS:
        values = raw.get("values")
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value.strip() for value in values)
        ):
            raise HarnessError(f"decided {name} needs non-blank values")
        return {"values": [value.strip() for value in values]}
    if name in NUMBER_FIELDS:
        value = raw.get("value")
        if name in INTEGER_FIELDS:
            if type(value) is not int or value < 0:
                raise HarnessError(f"decided {name} needs a non-negative integer value")
        elif (
            type(value) not in {int, float} or value < 0
            or (type(value) is float and not math.isfinite(value))
        ):
            raise HarnessError(f"decided {name} needs a non-negative number value")
        out = {"value": value}
    elif name in WINDOW_FIELDS:
        value = raw.get("value")
        if type(value) is not int or value < 1:
            raise HarnessError(f"decided {name} needs a positive integer value")
        unit = raw.get("unit", "days")
        if unit not in {"days", "weeks"}:
            raise HarnessError(f"decided {name} unit must be days or weeks")
        out = {"value": value, "unit": unit}
        if raw.get("description") is not None:
            if _blank(raw["description"]):
                raise HarnessError(f"decided {name} description must be non-blank")
            out["description"] = raw["description"].strip()
        return out
    else:
        if _blank(raw.get("value")):
            raise HarnessError(f"decided {name} needs a non-blank value")
        out = {"value": raw["value"].strip()}
        if name == "comparator" and out["value"] not in COMPARATORS:
            raise HarnessError("decided comparator must be " + ", ".join(sorted(COMPARATORS)))
    if raw.get("unit") is not None:
        if _blank(raw["unit"]):
            raise HarnessError(f"decided {name} unit must be non-blank")
        out["unit"] = raw["unit"].strip()
    return out


def build(raw, decision_id, values, claims=(), assumptions=()):
    """Build revision 1 from operator inputs plus an optional model proposal.

    Only values already stated by the operator become ``decided``. Everything
    else stays ``unknown`` so no threshold is fabricated.
    """
    contract = {field: {"state": "unknown"} for field in FIELDS}
    if raw:
        if not isinstance(raw, dict):
            raise HarnessError("decision contract must be an object")
        extra = set(raw) - set(FIELDS)
        if extra:
            raise HarnessError(
                "decision contract has unknown fields: " + ", ".join(sorted(extra))
            )
        for name, slot in raw.items():
            normalized = _slot(name, slot)
            if normalized["state"] == "decided":
                normalized["state"] = "proposed"
            contract[name] = normalized
    # Operator inputs override model guesses for the constraints they actually supplied.
    goal = values.get("goal")
    if not _blank(goal):
        contract["objective"] = {"state": "decided", "value": goal.strip()}
    budget = values.get("budget")
    if isinstance(budget, dict) and all(
        key in budget for key in ("amount_minor", "currency", "unit")
    ):
        contract["budget_constraints"] = _slot(
            "budget_constraints", {"state": "decided", **budget}
        )
    return {
        "decision_id": decision_id,
        "decision_revision": 1,
        **contract,
        "evidence_refs": sorted({claim["source_id"] for claim in claims}),
        "assumptions": [str(item) for item in assumptions][:20],
        "approval_status": "pending",
        "change_reason": None,
        "change_initiator": "model",
        "approved_by": None,
        "supersedes": None,
    }


def revise(contract, patch, *, reason, actor):
    """Create the next revision. The caller must already hold operator approval."""
    if not isinstance(patch, dict):
        raise HarnessError("decision patch must be an object")
    extra = set(patch) - set(FIELDS)
    if extra:
        raise HarnessError("decision patch has unknown fields: " + ", ".join(sorted(extra)))
    if _blank(reason):
        raise HarnessError("a decision revision requires a change reason")
    if _blank(actor):
        raise HarnessError("a decision revision requires the approving operator")
    updated = {
        field: _slot(field, patch[field]) if field in patch else dict(contract[field])
        for field in FIELDS
    }
    return {
        "decision_id": contract["decision_id"],
        "decision_revision": contract["decision_revision"] + 1,
        **updated,
        "evidence_refs": list(contract["evidence_refs"]),
        "assumptions": list(contract["assumptions"]),
        "approval_status": "approved",
        "change_reason": reason.strip(),
        "change_initiator": "human",
        "approved_by": actor.strip(),
        "supersedes": contract["decision_id"],
    }


def declaration(contract):
    """The copy-only constraint handoff a conforming downstream draft echoes."""
    return {
        "decision_id": contract["decision_id"],
        "decision_revision": contract["decision_revision"],
        "constraints": {
            field: dict(contract[field])
            for field in FIELDS
            if contract[field]["state"] == "decided"
        },
    }


def _window_days(slot):
    return slot.get("value") * (7 if slot.get("unit") == "weeks" else 1)


def _same(field, expected, actual):
    if field in BUDGET_FIELDS:
        return (
            expected.get("amount_minor") == actual.get("amount_minor")
            and str(expected.get("currency", "")).upper()
            == str(actual.get("currency", "")).upper()
            and str(expected.get("unit", "")).casefold()
            == str(actual.get("unit", "")).casefold()
        )
    if field in LIST_FIELDS:
        return sorted(
            value.casefold() for value in expected.get("values") or []
        ) == sorted(value.casefold() for value in actual.get("values") or [])
    if field in WINDOW_FIELDS:
        if type(actual.get("value")) is not int or actual.get("unit") not in {"days", "weeks"}:
            return False
        return (
            _window_days(expected) == _window_days(actual)
            and expected.get("description") == actual.get("description")
        )
    if field in NUMBER_FIELDS:
        value = actual.get("value")
        if field in INTEGER_FIELDS:
            if type(value) is not int:
                return False
        elif type(value) not in {int, float} or type(value) is bool:
            return False
        return (
            expected.get("value") == value
            and str(expected.get("unit", "")).casefold()
            == str(actual.get("unit", "")).casefold()
        )
    return (
        isinstance(actual.get("value"), str)
        and expected.get("value", "").casefold() == actual["value"].strip().casefold()
        and str(expected.get("unit", "")).casefold()
        == str(actual.get("unit", "")).casefold()
    )


def _summary(name, slot):
    if name in BUDGET_FIELDS:
        return {
            "amount_minor": slot.get("amount_minor"),
            "currency": slot.get("currency"),
            "unit": slot.get("unit"),
        }
    if name in LIST_FIELDS:
        return {"values": slot.get("values")}
    if name in WINDOW_FIELDS:
        return {"value": slot.get("value"), "unit": slot.get("unit")}
    return {"value": slot.get("value"), "unit": slot.get("unit")}


def markdown_lines(contract, *, format_text=str):
    """Render the contract without turning proposals into approved standards."""
    lines = []
    for field in FIELDS:
        slot = contract[field]
        if slot["state"] != "decided":
            lines.append(f"- **{field}** · {slot['state']}")
            continue
        if field in BUDGET_FIELDS:
            detail = f"{slot['amount_minor']} minor units {slot['currency']} · {slot['unit']}"
        elif field in LIST_FIELDS:
            detail = "; ".join(slot["values"])
        elif field in WINDOW_FIELDS:
            detail = f"{slot['value']} {slot['unit']}"
            if slot.get("description"):
                detail += f" · {slot['description']}"
        else:
            detail = str(slot["value"])
            if slot.get("unit"):
                detail += f" ({slot['unit']})"
        lines.append(f"- **{field}** · {format_text(detail)}")
    return lines


def check(contract, declared):
    """Compare a downstream declaration against the approved contract."""
    if declared is None:
        declared = {}
    if not isinstance(declared, dict):
        raise HarnessError("constraint_refs must be an object")
    if not declared:
        return {
            "status": "not_declared",
            "declared": False,
            "decision_revision": contract["decision_revision"],
            "drift": [{"field": "decision_id", "kind": "not_declared"}],
            "proposals": [],
        }
    if (
        declared.get("decision_id") != contract["decision_id"]
        or declared.get("decision_revision") != contract["decision_revision"]
    ):
        return {
            "status": "stale_version",
            "declared": bool(declared),
            "decision_revision": contract["decision_revision"],
            "drift": [
                {
                    "field": "decision_revision",
                    "kind": "stale",
                    "expected": contract["decision_revision"],
                    "actual": declared.get("decision_revision"),
                }
            ],
            "proposals": [],
        }
    constraints = declared.get("constraints") or {}
    if not isinstance(constraints, dict):
        raise HarnessError("constraint_refs constraints must be an object")
    extra = set(constraints) - set(FIELDS)
    if extra:
        raise HarnessError("constraint_refs has unknown fields: " + ", ".join(sorted(extra)))
    drift = []
    for field in FIELDS:
        expected = contract[field]
        actual = constraints.get(field)
        if expected["state"] == "decided":
            if actual is None:
                drift.append({"field": field, "kind": "omitted"})
            elif (
                not isinstance(actual, dict)
                or actual.get("state") != "decided"
                or not _same(field, expected, actual)
            ):
                drift.append(
                    {
                        "field": field,
                        "kind": "changed",
                        "expected": _summary(field, expected),
                        "actual": _summary(field, actual if isinstance(actual, dict) else {}),
                    }
                )
        elif actual is not None:
            drift.append(
                {
                    "field": field,
                    "kind": "fabricated",
                    "contract_state": expected["state"],
                    "actual": _summary(field, actual),
                }
            )
    proposals = []
    for item in declared.get("proposals") or []:
        if not isinstance(item, dict) or _blank(item.get("field")):
            raise HarnessError("constraint proposal needs a field")
        if item["field"] not in FIELDS:
            raise HarnessError("constraint proposal field is not a decision constraint")
        proposals.append(
            {
                "field": item["field"],
                "reason": item.get("reason"),
                "value": item.get("value"),
            }
        )
    return {
        "status": "drifted" if drift else ("proposal_only" if proposals else "consistent"),
        "declared": bool(declared),
        "decision_revision": contract["decision_revision"],
        "drift": drift,
        "proposals": proposals,
    }
