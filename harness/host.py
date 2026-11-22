"""Host-neutral task contract and replaceable adapter boundary.

The harness owns workflow state, evidence and approvals. A host only executes
one bounded task and returns a structured result. Hosts differ in tool policy,
context assembly and skill loading, so every adapter declares those limits
instead of pretending they are identical.
"""

from dataclasses import asdict, dataclass
from typing import Protocol

from .adapters import FixtureAdapter
from .contracts import HarnessError, validate

TASK_FIELDS = (
    "project_id",
    "run_id",
    "stage",
    "skill",
    "context",
    "evidence",
    "tool_policy",
    "artifact_kind",
    "decision",
    "handoffs",
    "market_review",
    "decision_brief",
)
OPTIONAL_FIELDS = {"artifact_kind", "decision", "handoffs", "market_review", "decision_brief"}


@dataclass(frozen=True)
class TaskInput:
    project_id: str
    run_id: str
    stage: str
    skill: dict
    context: dict
    evidence: list
    tool_policy: dict
    artifact_kind: str | None = None
    decision: dict | None = None
    handoffs: list | None = None
    market_review: dict | None = None
    decision_brief: dict | None = None

    @classmethod
    def from_request(cls, request):
        if not isinstance(request, dict):
            raise HarnessError("task input must be an object")
        validate("task-input", request)
        return cls(**{key: request[key] for key in TASK_FIELDS if key in request})

    def to_request(self):
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class TaskResult:
    status: str
    result: dict
    error: str | None = None

    def __post_init__(self):
        if self.status not in {"succeeded", "failed"}:
            raise HarnessError("task result status must be succeeded or failed")
        if not isinstance(self.result, dict):
            raise HarnessError("task result payload must be an object")
        if self.status == "failed" and not self.error:
            raise HarnessError("a failed task result needs an error code or message")

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if value is not None}


class HostAdapter(Protocol):
    name: str
    capabilities: dict

    def execute(self, task: TaskInput) -> TaskResult: ...


class FixtureHost:
    name = "fixture"
    capabilities = {
        "execution": "fixture",
        "tool_policy": "not_enforced",
        "context": "serialized_task_input",
        "skills": "none",
        "structured_output": "adapter_result",
    }

    def __init__(self):
        self.delegate = FixtureAdapter()

    def execute(self, task):
        return TaskResult("succeeded", self.delegate.execute(task.to_request()))


class CodexHost:
    name = "codex"
    capabilities = {
        "execution": "model",
        "tool_policy": "enforced_by_host",
        "context": "pinned_skill_documents",
        "skills": "pinned_blobs",
        "structured_output": "json_schema",
        "resumable": "rerun_safe",
    }

    def __init__(self, adapter):
        self.delegate = adapter

    def execute(self, task):
        try:
            result = self.delegate.execute(task.to_request())
        except Exception as exc:
            receipt = getattr(self.delegate, "last_receipt", None) or {}
            detail = (
                str(exc)
                if isinstance(exc, HarnessError)
                else receipt.get("error_code") or type(exc).__name__
            )
            return TaskResult("failed", {}, detail)
        return TaskResult("succeeded", result)


HOSTS = {"fixture": FixtureHost, "codex": CodexHost}


def host(name, **kwargs):
    found = HOSTS.get(name)
    if found is None:
        raise HarnessError("unknown host adapter")
    return found(**kwargs)


def capability_matrix():
    return [
        {"name": name, "capabilities": dict(HOSTS[name].capabilities)}
        for name in sorted(HOSTS)
    ]
