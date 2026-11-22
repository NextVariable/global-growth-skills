"""Token, byte and duration accounting for one workflow run.

The report only aggregates host receipts that an adapter actually returned.
It never estimates a monetary cost without an approved pricing table, so an
unknown price stays explicitly unknown instead of becoming a fake number.
"""

TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
BYTE_KEYS = ("prompt_bytes", "skill_document_bytes", "skill_package_bytes")


def cost_report(state):
    stages = {}
    totals = {
        "calls": 0,
        "duration_ms": 0,
        **dict.fromkeys(TOKEN_KEYS, 0),
        **dict.fromkeys(BYTE_KEYS, 0),
    }
    receipts = 0
    for event in state.get("history", []):
        data = event.get("data")
        receipt = data.get("host_receipt") if isinstance(data, dict) else None
        if not receipt:
            continue
        receipts += 1
        stage = event.get("stage", "unknown")
        row = stages.setdefault(
            stage,
            {
                "attempts": 0,
                "calls": 0,
                "duration_ms": 0,
                "statuses": [],
                **dict.fromkeys(TOKEN_KEYS, 0),
                "prompt_bytes": 0,
            },
        )
        row["attempts"] += 1
        row["statuses"].append(receipt.get("status"))
        row["calls"] += receipt.get("calls", 0)
        row["duration_ms"] += receipt.get("duration_ms", 0)
        row["prompt_bytes"] += receipt.get("prompt_bytes", 0)
        tokens = receipt.get("tokens") or {}
        for key in TOKEN_KEYS:
            row[key] += tokens.get(key, 0)
            totals[key] += tokens.get(key, 0)
        for key in ("calls", "duration_ms", *BYTE_KEYS):
            totals[key] += receipt.get(key, 0)
    totals["model_executed"] = bool(receipts)
    return {
        "run_id": state.get("run_id"),
        "execution": state.get("execution"),
        "stages": stages,
        "totals": totals,
        "cost": {
            "status": "not_estimated",
            "reason": "no approved per-model pricing table is configured",
        },
        "boundary": (
            "Receipt totals describe this run only. They are not a benchmark against other "
            "agents and do not measure business outcomes."
        ),
    }
