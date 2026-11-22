"""JSON Schema v1 validation and a deterministic encoding for stored records."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/v1/harness.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)


class HarnessError(Exception):
    """An actionable failure, safe to print without customer input."""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def validate(kind, value):
    validator = Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{kind}"})
    error = next(validator.iter_errors(value), None)
    if error is not None:
        pointer = "/".join(str(part) for part in error.absolute_path) or "(root)"
        raise HarnessError(f"{kind} validation failed at {pointer} ({error.validator})")
    return value
