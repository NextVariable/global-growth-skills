"""Read-only evidence bridge and single-use, local operator grants for mock writes."""

from contextlib import nullcontext
import json
import os
import time

from .contracts import HarnessError, digest, encode, validate
from .research import review


class MockExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, operation):
        self.calls += 1
        return {
            "executor": "mock",
            "status": "confirmed",
            "target": operation["target"],
        }


class Gateway:
    """The caller must be a trusted local operator. Never expose grants to an agent."""

    def __init__(self, harness, *, readers=None, clock=time.time):
        self.harness = harness
        self.readers = dict(readers or {})
        self.clock = clock
        self.mock = MockExecutor()

    def _actor(self):
        if not hasattr(os, "getuid"):
            raise HarnessError("mock approvals require a POSIX local operator identity")
        return f"uid:{os.getuid()}"

    def _event(self, ident, event, data):
        self.harness.db.execute(
            "INSERT INTO tool_events(operation_id,event,data) VALUES (?,?,?)",
            (ident, event, encode(data)),
        )

    def _verify(self, operation):
        validate("operation", operation)
        if operation["project_id"] != self.harness._project()["id"]:
            raise HarnessError("operation belongs to a different project")
        return operation["id"]

    def _digest(self, operation):
        return digest(
            {
                "operation": operation,
                "context_revision": self.harness._project()["revision"],
            }
        )

    def approve(self, operation, ttl):
        with self.harness.transaction():
            ident = self._verify(operation)
            if type(ttl) is not int or not 1 <= ttl <= 3600:
                raise HarnessError("approval TTL must be 1–3600 seconds")
            actor = self._actor()
            if self.harness.db.execute(
                "SELECT 1 FROM approvals WHERE id=?", (ident,)
            ).fetchone():
                raise HarnessError("operation already has an approval history")
            expires = int(self.clock()) + ttl
            self.harness.db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,'approved')",
                (ident, actor, self._digest(operation), expires),
            )
            self._event(
                ident,
                "approved",
                {"actor": actor, "expires": expires, "digest": self._digest(operation)},
            )

    def revoke(self, ident):
        with self.harness.transaction():
            result = self.harness.db.execute(
                "UPDATE approvals SET state='revoked' WHERE id=? AND actor=? AND state='approved'",
                (ident, self._actor()),
            )
            if result.rowcount != 1:
                raise HarnessError("no revocable approval for this operator")
            self._event(ident, "revoked", {})

    def write(self, operation):
        with self.harness.transaction():
            ident = self._verify(operation)
            grant = self.harness.db.execute(
                "SELECT * FROM approvals WHERE id=?", (ident,)
            ).fetchone()
            if (
                not grant
                or grant["actor"] != self._actor()
                or grant["state"] != "approved"
                or grant["operation_digest"] != self._digest(operation)
                or grant["expires"] <= self.clock()
            ):
                raise HarnessError(
                    "write denied: exact unexpired unused approval required"
                )
            self.harness.db.execute(
                "UPDATE approvals SET state='consumed' WHERE id=?", (ident,)
            )
            self._event(
                ident,
                "outcome_unknown",
                {"executor": "mock", "digest": self._digest(operation)},
            )
        try:
            receipt = self.mock.execute(operation)
            validate("mock-receipt", receipt)
            if receipt["target"] != operation["target"]:
                raise HarnessError("receipt target mismatch")
        except Exception:
            raise HarnessError(
                "mock result unknown; do not retry this operation ID"
            ) from None
        with self.harness.transaction():
            self._event(ident, "confirmed", receipt)
        return receipt

    def read(self, tool, query):
        if tool not in self.readers:
            raise HarnessError("source is not a registered read-only provider")
        validate("run-id", tool)
        try:
            records = self.readers[tool](query)
            review(records)
        except Exception:
            with self.harness.transaction():
                self._event(tool, "read_failed", {"query_digest": digest(query)})
            raise HarnessError(
                "read-only provider failed or returned invalid evidence"
            ) from None
        with self.harness.transaction():
            self._event(
                tool,
                "read_confirmed",
                {"query_digest": digest(query), "source_count": len(records)},
            )
        return records

    def receipts(self):
        scope = (
            nullcontext()
            if self.harness.db.in_transaction
            else self.harness.transaction()
        )
        with scope:
            return [
                {**dict(row), "data": json.loads(row["data"])}
                for row in self.harness.db.execute(
                    "SELECT operation_id,event,data FROM tool_events ORDER BY id"
                )
            ]
